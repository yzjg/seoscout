"""
LLM API Client — async batch generation with retry logic.

Shared by generate and translate stages. All config from Config class (.env).
LLM_PROVIDER=api uses the OpenAI-compatible HTTP API; LLM_PROVIDER=claude_cli runs
`claude -p` on the Claude Code subscription. Both are capped at GENERATE_CONCURRENT_LIMIT
requests in flight.
"""

import asyncio
import aiohttp
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import Config

SYSTEM_PROMPT = "You are a professional SEO content writer."
# Subscription quota used up: retrying on the same account cannot succeed until the window resets.
# Same rule as claude-dispatch/account-pool.sh pool_pane_usage_limited ("You've hit your 5-hour limit").
USAGE_LIMIT_RE = re.compile(r"hit your (?:[^ ]+ )?limit|usage limit reached", re.I)
# Login no longer valid on this account (seen: "Failed to authenticate: OAuth session expired and could
# not be refreshed", "Not logged in · Please run /login"). Same rule as claude-dispatch/claude-p.sh AUTH_FAIL_RE.
AUTH_FAIL_RE = re.compile(r"login expired|failed to authenticate|oauth (?:session|token)(?: has)? (?:expired|been revoked|revoked)"
                          r"|could not be refreshed|not logged in|please run /login|invalid api key"
                          r"|authentication_error", re.I)
# Multi-account pool (one CLAUDE_CONFIG_DIR per account); on a usage limit we switch to another account
ACCOUNT_POOL_SH = os.getenv("ACCOUNT_POOL_SH",
                            "/Users/yuzhijian/.openclaw/skills/claude-dispatch/account-pool.sh")

# Web-page answers (arena.ai / gemini.google.com in a resident Chrome) are read from the rendered page, so
# Markdown survives only inside a code block: ask for the whole answer in one ```mdx block and read its raw text.
WEB_FORMAT_NOTE = (
    "\n\n---\n"
    "OUTPUT FORMAT (this overrides any earlier instruction about code blocks): put your ENTIRE answer "
    "inside ONE single fenced code block that starts with ```mdx and ends with ```. "
    "Write nothing before or after that code block, and never use ``` inside the answer itself. "
    "Do NOT write a `# ` H1 title line: the page renders metadata.title as the H1, so the body starts "
    "directly with text or `## ` sections. Plain Markdown only: no JSX/HTML components such as <Carousel>, "
    "<Image>, <Video>, <Step> or <Sequence>, and no image placeholders."
)
_HEADING_RE = re.compile(r"^(#{1,6})\s", re.M)


def strip_leading_h1(text: str) -> str:
    """Gemini web often repeats the title as a `# ` line right after the metadata block; drop only that one
    line (an H1 anywhere else is left in place for mdx_shape_error to reject)."""
    m = re.match(r"(export const metadata = \{.*?\n\}\s*\n)(\s*)# [^\n]*\n+", text or "", re.S)
    return m.group(1).rstrip("\n") + "\n\n" + text[m.end():] if m else text


_METADATA_RE = re.compile(r"export const metadata = \{.*?\n\}\s*\n", re.S)
# English function words that do not exist in the other site languages; an English paragraph has
# well over 12% of them, a translated one only the odd game title ("The Wolf Among Us")
_EN_STOPWORDS = frozenset(("the", "and", "with", "for", "that", "this", "you", "your", "are",
                           "from", "when", "which", "have"))


def _body(text: str) -> str:
    m = _METADATA_RE.match(text or "")
    return (text or "")[m.end():] if m else (text or "")


def body_word_count(text: str) -> int:
    """Words in the article body: metadata block, link URLs and table rulers (`:---`) are not counted."""
    body = re.sub(r"\]\([^)\s]*\)", "]", _body(text))
    return len(re.findall(r"[A-Za-z0-9À-ÿ][A-Za-z0-9À-ÿ'’-]*", body))


def english_paragraphs(text: str) -> Tuple[int, int]:
    """(still English, total) long prose paragraphs of a translated body. Headings, tables and short
    blocks are skipped; a paragraph needs 30+ Latin words and 3+ different English function words, so
    one that only repeats an English game title ("The …") is never counted."""
    english = total = 0
    for block in re.split(r"\n\s*\n", _body(text)):
        block = block.strip()
        if len(block) < 200 or block.startswith(("|", "#", "```")):
            continue
        total += 1
        words = re.findall(r"[a-zà-ÿ]+", block.lower())
        hits = [w for w in words if w in _EN_STOPWORDS]
        if len(words) >= 30 and len(set(hits)) >= 3 and len(hits) / len(words) > 0.12:
            english += 1
    return english, total


def mdx_shape_error(text: str, min_body: int = 500, min_words: int = 0) -> str:
    """Strict shape check for one MDX article (same rules as code_before's format check). '' = OK.
    min_words > 0 also requires that many body words (GENERATE_MIN_WORDS for English articles)."""
    m = re.match(r"export const metadata = \{(.*?)\n\}\s*\n", text or "", re.S)
    if not m:
        return "does not start with a complete `export const metadata = { … }`"
    missing = [k for k in ("title", "description", "category", "date")
               if not re.search(rf"^\s*{k}\s*:", m.group(1), re.M)]
    if missing:
        return f"metadata missing {missing}"
    body = text[m.end():]
    if len(body.strip()) < min_body:
        return f"body too short ({len(body.strip())} chars)"
    if min_words and body_word_count(text) < min_words:
        return f"body too short ({body_word_count(text)} words, need at least {min_words})"
    if re.search(r"^# ", body, re.M):
        return "has an H1 heading"
    if body.lstrip().startswith("```") or text.rstrip().endswith("```"):
        return "wrapped in a code block"
    comps = sorted(set(re.findall(r"<([A-Z][A-Za-z0-9]*)", body)))
    if comps:  # code_before's format check rejects any JSX component (Gemini web adds <Carousel>/<Image>/<Step>)
        return f"uses components {comps}"
    return ""


def heading_levels(text: str) -> List[str]:
    """Heading markers outside fenced code, in order (a translation must keep the same list)."""
    out, fenced = [], False
    for line in (text or "").splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        m = None if fenced else _HEADING_RE.match(line)
        if m:
            out.append(m.group(1))
    return out


def _cdp_alive(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _pool(*args: str, stdin: str = "") -> str:
    """Run account-pool.sh <args>; return stdout ('' on failure or when the pool script is missing)."""
    if not os.path.isfile(ACCOUNT_POOL_SH):
        return ""
    try:
        r = subprocess.run(["bash", ACCOUNT_POOL_SH, *args], input=stdin, capture_output=True,
                           text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


class WebChannel:
    """One web-page model (DeepSeek / Grok / Gemini / Arena web) driven by its <skill>/query.py in a resident Chrome.
    Turned off for the rest of the run when its script / Chrome is missing or after max_consec_fails
    failures in a row, so a broken web page never slows the run down."""

    def __init__(self, spec: Dict):
        self.name = spec["name"]
        self.title = spec["title"]
        self.script = spec["script"]
        self.port = spec["port"]
        self.attempts = spec["attempts"]
        self.max_wait = spec["max_wait"]
        self.timeout = spec["timeout"]
        self.max_consec_fails = spec["max_consec_fails"]
        self.payload = dict(spec.get("payload") or {})
        self.semaphore = asyncio.Semaphore(max(1, spec["concurrency"]))
        self.consec_fails = 0
        self.ok = 0
        self.handed_on = 0
        self.disabled = ""
        if not os.path.exists(self.script):
            self.disabled = f"script not found: {self.script}"
        elif not _cdp_alive(self.port):
            self.disabled = f"Chrome CDP port {self.port} not reachable"
        if self.disabled:
            print(f"  ⚠️  {self.title} off ({self.disabled})")


class LLMClient:
    """Async LLM API client with retry, stats, and batch support."""

    def __init__(self, cli_model: str = "", cli_effort: str = "", web: List[Dict] = None):
        self.provider = Config.LLM_PROVIDER
        # Web-page models tried first, in this order (Config.web_channels('generate' | 'translate')),
        # then self.provider as the last fallback.
        self.web = [WebChannel(spec) for spec in (web or [])]
        self.cli_bin = Config.CLAUDE_CLI_BIN
        self.cli_model = cli_model or Config.CLAUDE_CLI_MODEL
        self.cli_effort = cli_effort
        self.semaphore = asyncio.Semaphore(max(1, Config.GENERATE_CONCURRENT_LIMIT))
        self.usage_limit_error = None
        # Account used by `claude -p`; '' = default ~/.claude (acc1). Starts from the inherited env.
        self.cli_config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "")
        # A preferred account was named (website-create --ACCOUNT → CLAUDE_ACCOUNT_PREFER): start from the
        # pool's pick, which puts it first and skips it while limited / logged out
        if not self.cli_config_dir and os.environ.get("CLAUDE_ACCOUNT_PREFER", "").strip():
            picked = _pool("pick")
            if "\t" in picked:
                d = picked.split("\t", 1)[1].rstrip("/")
                self.cli_config_dir = "" if d == os.path.expanduser("~/.claude") else d
        self.switch_lock = asyncio.Lock()

        self.api_key = Config.LLM_API_KEY
        self.base_url = Config.LLM_API_BASE_URL.rstrip('/')
        self.api_url = f"{self.base_url}/chat/completions"
        self.model = Config.LLM_MODEL
        self.temperature = Config.LLM_TEMPERATURE
        self.max_tokens = Config.LLM_MAX_TOKENS
        self.timeout_seconds = Config.LLM_TIMEOUT
        self.retry_attempts = Config.LLM_RETRY_ATTEMPTS
        self.retry_delay = Config.LLM_RETRY_DELAY

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'total_tokens': 0,
            'start_time': None,
            'end_time': None,
        }

    # ── single request ──────────────────────────────────────────

    async def generate_single(
        self,
        session: aiohttp.ClientSession,
        prompt: str,
        meta: Dict = None,
        validator=None,
        skip_web: Tuple[str, ...] = (),
    ) -> Optional[str]:
        """Send a single prompt, return content string or None.

        Order: each web channel (except those named in skip_web), then LLM_PROVIDER.
        validator(content) -> '' when OK / error text: only used on web answers; a failing answer goes
        to the next one in the order (the caller still runs its own checks on whatever comes back).
        """
        async with self.semaphore:
            self.stats['total_requests'] += 1
            label = self._label(meta)
            channels = [ch for ch in self.web if ch.name not in skip_web]
            for i, ch in enumerate(channels):
                if ch.disabled:
                    continue
                content = await self._try_web(ch, prompt, label, validator)
                if content is not None:
                    self.stats['successful_requests'] += 1
                    if meta is not None:
                        meta['source'] = ch.title   # 这次回答来自哪个模型；修复轮会覆盖成最后一次的来源
                    return content
                later = [c.title for c in channels[i + 1:] if not c.disabled]
                print(f"  ↩️  Falling back to {later[0] if later else self.provider}: {label}")
            if meta is not None:
                meta['source'] = self.provider
            if self.provider == "claude_cli":
                return await self._generate_cli(prompt, meta, label)
            return await self._generate_api(session, prompt, meta, label)

    @staticmethod
    def _label(meta: Optional[Dict]) -> str:
        label = (meta or {}).get('keyword', 'unknown')
        if (meta or {}).get('language'):
            label = f"[{meta['language']}] {label}"
        return label

    def web_on(self, name: str) -> bool:
        """True while the named web channel is configured and not turned off."""
        return any(ch.name == name and not ch.disabled for ch in self.web)

    async def web_single(self, name: str, prompt: str, meta: Dict = None, validator=None) -> Optional[str]:
        """Ask ONE web channel only (no fallback): its checked answer, or None. For callers that put
        their own step between two channels (translate: Arena web → Google Translate → Gemini web …)."""
        for ch in self.web:
            if ch.name == name and not ch.disabled:
                return await self._try_web(ch, prompt, self._label(meta), validator)
        return None

    async def _try_web(self, ch: "WebChannel", prompt: str, label: str, validator=None) -> Optional[str]:
        """One question to one web channel; the answer when it passes the validator, else None."""
        content = await self._ask_web(ch, prompt, label)
        err = "" if content is None else (validator(content) if validator else "")
        if content is not None and not err:
            ch.consec_fails = 0
            ch.ok += 1
            print(f"  🌐 {ch.title} ok: {label}")
            return content
        if err:
            print(f"  ⚠️  {ch.title} answer rejected for {label}: {err}")
        ch.handed_on += 1
        ch.consec_fails += 1
        if ch.consec_fails >= ch.max_consec_fails and not ch.disabled:
            ch.disabled = f"{ch.consec_fails} failures in a row"
            print(f"  ⛔ {ch.title} off for the rest of this run ({ch.disabled})")
        return None

    async def _generate_cli(self, prompt: str, meta: Optional[Dict], label: str) -> Optional[str]:
        """`claude -p` on the subscription: no tools, no saved session, no user settings / MCP."""
        if self.usage_limit_error:
            self.stats['failed_requests'] += 1
            return None
        cmd = [self.cli_bin, "-p", "--model", self.cli_model, "--tools", "",
               "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "",
               "--system-prompt", SYSTEM_PROMPT, "--output-format", "json"]
        if self.cli_effort:
            cmd += ["--effort", self.cli_effort]

        attempt = 0
        while attempt < self.retry_attempts:
            proc = None
            config_dir = self.cli_config_dir
            env = dict(os.environ)
            if config_dir:
                env["CLAUDE_CONFIG_DIR"] = config_dir
            else:
                env.pop("CLAUDE_CONFIG_DIR", None)
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdin=asyncio.subprocess.PIPE, env=env,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                out, err = await asyncio.wait_for(proc.communicate(prompt.encode('utf-8')),
                                                  timeout=self.timeout_seconds)
                try:
                    data = json.loads(out.decode('utf-8', 'replace'))
                except ValueError:
                    raise RuntimeError(f"claude exit {proc.returncode}, non-JSON output: "
                                       f"{(err or out).decode('utf-8', 'replace')[:300]}")
                self._save_debug(meta or {}, data)
                content = data.get('result')
                if data.get('is_error') or data.get('subtype') != 'success':
                    msg = str(content or data.get('subtype') or 'unknown error')
                    if USAGE_LIMIT_RE.search(msg):
                        kind = "limit"
                    elif AUTH_FAIL_RE.search(msg) or data.get('api_error_status') == 401:
                        kind = "auth"
                    else:
                        kind = ""
                    if kind:
                        # Switched to another account: retry right away without using up an attempt
                        if await self._switch_account(config_dir, msg, kind):
                            continue
                        break
                    raise RuntimeError(f"claude error: {msg[:300]}")

                usage = data.get('usage') or {}
                self.stats['total_tokens'] += sum(usage.get(k) or 0 for k in (
                    'input_tokens', 'output_tokens',
                    'cache_creation_input_tokens', 'cache_read_input_tokens'))

                if not content or not content.strip():
                    print(f"  ⚠️  Empty response for {label} (attempt {attempt+1}/{self.retry_attempts})")
                else:
                    self.stats['successful_requests'] += 1
                    return content

            except asyncio.TimeoutError:
                if proc and proc.returncode is None:
                    proc.kill()
                    await proc.wait()
                print(f"  ⏱️  Timeout for {label} (attempt {attempt+1}/{self.retry_attempts})")
            except Exception as e:
                print(f"  ❌ claude -p failed for {label} (attempt {attempt+1}/{self.retry_attempts}): {e}")

            if attempt < self.retry_attempts - 1:
                await asyncio.sleep(self.retry_delay * (attempt + 1))
            attempt += 1

        self.stats['failed_requests'] += 1
        return None

    async def _ask_web(self, ch: "WebChannel", prompt: str, label: str) -> Optional[str]:
        """One question to a web page via the channel's query.py (it opens its own new tab, reads only
        that tab, and retries with backoff and a fresh tab on its own). Returns the raw text of the
        answer's code block, or None on any failure."""
        payload = {
            **ch.payload,
            "question": prompt + WEB_FORMAT_NOTE,
            "cdp_port": ch.port,
            "attempts": ch.attempts,
            "extract": "code",
            "max_wait": ch.max_wait,
        }
        log_dir = Path(Config.LOG_DIR or ".") / f"{ch.name}-web"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / (re.sub(r"[^\w.-]+", "_", label)[:120] + ".log")
        async with ch.semaphore:
            if ch.disabled:
                return None
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    Config.GEMINI_PYTHON, ch.script,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE)
                out, err = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode()),
                                                  timeout=ch.timeout)
            except asyncio.TimeoutError:
                if proc and proc.returncode is None:
                    proc.kill()
                    await proc.wait()
                print(f"  ⏱️  {ch.title} timeout ({ch.timeout}s) for {label}")
                return None
            except Exception as e:
                print(f"  ❌ {ch.title} failed to start for {label}: {e}")
                return None
        try:
            log_file.write_bytes(err or b"")
        except OSError:
            pass
        try:
            result = json.loads(out.decode("utf-8", "replace").strip().splitlines()[-1])
        except Exception:
            print(f"  ❌ {ch.title} output not JSON for {label} (log {log_file})")
            return None
        answer = result.get("answer") or ""
        if result.get("error") or not answer.strip():
            print(f"  ❌ {ch.title} error for {label}: {str(result.get('error'))[:200]} (log {log_file})")
            # The account's quota is used up: more questions in this run would all fail the same way
            if result.get("code") == "usage_limit" and not ch.disabled:
                ch.disabled = "account usage limit reached"
                print(f"  ⛔ {ch.title} off for the rest of this run ({ch.disabled})")
            return None
        return strip_leading_h1(answer)

    async def _switch_account(self, failed_dir: str, msg: str, kind: str = "limit") -> bool:
        """Mark the account behind failed_dir as unusable and switch `claude -p` to an available one.

        kind="limit": usage limit → mark-limited until the reset time.
        kind="auth":  login expired → mark-auth-failed (disabled until re-login + `account-pool.sh verify`).
        Returns True when requests can go on (switched, or another request already switched);
        False when no account is left — then usage_limit_error is set and remaining requests are skipped.
        """
        what = "login expired" if kind == "auth" else "usage limit"
        async with self.switch_lock:
            if self.usage_limit_error:
                return False
            if self.cli_config_dir != failed_dir:
                return True
            name = await asyncio.to_thread(_pool, "name-of", failed_dir)
            if name:
                if kind == "auth":
                    await asyncio.to_thread(_pool, "mark-auth-failed", name, msg[:200])
                else:
                    until = await asyncio.to_thread(_pool, "parse-reset", stdin=msg)
                    if not until.isdigit():
                        until = str(int(time.time()) + 3600)
                    await asyncio.to_thread(_pool, "mark-limited", name, until, msg[:200])
                picked = await asyncio.to_thread(_pool, "pick", "--exclude", name)
                if "\t" in picked:
                    new_name, new_dir = picked.split("\t", 1)
                    default_dir = os.path.expanduser("~/.claude")
                    self.cli_config_dir = "" if new_dir.rstrip("/") == default_dir else new_dir
                    print(f"  🔁 Claude {what} on {name}, switched claude -p to {new_name} ({new_dir})")
                    return True
            self.usage_limit_error = msg
            hint = " (re-login, then run account-pool.sh verify)" if kind == "auth" else ""
            print(f"  ⛔ Claude {what} on {name or failed_dir or '~/.claude'}, "
                  f"no other account available{hint}, skipping remaining requests: {msg[:200]}")
            return False

    async def _generate_api(self, session: aiohttp.ClientSession, prompt: str,
                            meta: Optional[Dict], label: str) -> Optional[str]:
        for attempt in range(self.retry_attempts):
            try:
                async with session.post(
                    self.api_url,
                    json={
                        "model": self.model,
                        "max_tokens": self.max_tokens,
                        "temperature": self.temperature,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "stream": False,
                    },
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._save_debug(meta or {}, data)
                        content = data['choices'][0]['message']['content']

                        if 'usage' in data:
                            self.stats['total_tokens'] += data['usage'].get('total_tokens', 0)

                        if not content or not content.strip():
                            print(f"  ⚠️  Empty response for {label} (attempt {attempt+1}/{self.retry_attempts})")
                            if attempt < self.retry_attempts - 1:
                                await asyncio.sleep(self.retry_delay * (attempt + 1))
                                continue
                            self.stats['failed_requests'] += 1
                            return None

                        self.stats['successful_requests'] += 1
                        return content

                    elif resp.status == 429:
                        wait = self.retry_delay * (attempt + 1) * 2
                        print(f"  ⚠️  Rate limited for {label}, waiting {wait}s...")
                        await asyncio.sleep(wait)
                        continue

                    else:
                        err = await resp.text()
                        print(f"  ❌ API {resp.status} for {label}: {err[:300]}")
                        if attempt < self.retry_attempts - 1:
                            await asyncio.sleep(self.retry_delay * (attempt + 1))
                            continue
                        self.stats['failed_requests'] += 1
                        return None

            except asyncio.TimeoutError:
                print(f"  ⏱️  Timeout for {label} (attempt {attempt+1}/{self.retry_attempts})")
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                self.stats['failed_requests'] += 1
                return None

            except Exception as e:
                print(f"  ❌ Exception for {label}: {e}")
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                self.stats['failed_requests'] += 1
                return None

        self.stats['failed_requests'] += 1
        return None

    # ── batch ───────────────────────────────────────────────────

    async def generate_batch(
        self,
        prompts: List[Tuple[str, Dict]],
        batch_size: int = None,
        validator=None,
    ) -> List[Tuple[Dict, Optional[str]]]:
        """
        Batch-generate from list of (prompt, meta) tuples.
        Returns list of (meta, content_or_None) in same order.
        """
        if batch_size is None:
            batch_size = Config.GENERATE_BATCH_SIZE

        self.stats['start_time'] = time.time()
        results: List[Tuple[Dict, Optional[str]]] = []

        async with aiohttp.ClientSession() as session:
            for i in range(0, len(prompts), batch_size):
                batch = prompts[i:i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(prompts) + batch_size - 1) // batch_size

                print(f"\n  📦 Batch {batch_num}/{total_batches} ({len(batch)} items)...")

                tasks = [
                    self.generate_single(session, prompt, meta, validator)
                    for prompt, meta in batch
                ]
                batch_results = await asyncio.gather(*tasks)

                for (prompt, meta), content in zip(batch, batch_results):
                    results.append((meta, content))

                completed = i + len(batch)
                print(f"  ✅ {completed}/{len(prompts)} done")

                if i + batch_size < len(prompts):
                    await asyncio.sleep(1)

        self.stats['end_time'] = time.time()
        return results

    # ── debug ───────────────────────────────────────────────────

    def _save_debug(self, meta: Dict, data: Dict):
        try:
            debug_dir = Path(Config.LOG_DIR) / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            keyword = meta.get('keyword', 'unknown')
            lang = meta.get('language', 'en')
            fp = debug_dir / f"{lang}_{keyword.replace(' ', '_')}_response.json"
            fp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass

    # ── stats ───────────────────────────────────────────────────

    def print_stats(self):
        s = self.stats
        duration = (s['end_time'] or time.time()) - (s['start_time'] or time.time())
        rate = s['total_requests'] / duration if duration > 0 else 0
        success_rate = (
            s['successful_requests'] / s['total_requests'] * 100
            if s['total_requests'] > 0 else 0
        )
        print(f"\n  📊 LLM {self.provider}: {s['successful_requests']}/{s['total_requests']} ok "
              f"({success_rate:.0f}%) | {s['total_tokens']} tokens | {duration:.1f}s")
        for ch in self.web:
            print(f"  🌐 {ch.title}: {ch.ok} ok, {ch.handed_on} handed on"
                  + (f" | off: {ch.disabled}" if ch.disabled else ""))
        if self.usage_limit_error:
            print(f"  ⛔ Stopped early: no usable Claude account ({self.usage_limit_error[:200]})")
