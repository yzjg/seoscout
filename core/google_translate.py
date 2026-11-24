"""
Google Translate (free `translate_a/t` endpoint, HTML mode) as the first translator of an MDX article.

The article is never sent as one blob. It is split into text units (metadata title / description /
summary, headings, paragraphs, list items, table cells); every unit becomes a small piece of HTML so
Google leaves alone what must not change, and the translated units go back into the English lines:

    inline code, `\\x` escapes, bare URLs, game / platform / studio names →  <span translate="no">…</span>
    **bold** / *italic*                                           →  <b>…</b> / <i>…</i>
    [text](url)                                                   →  <a href="N">text</a>

Heading levels, tables, lists, code fences and the other metadata keys are therefore the English ones
by construction. translate.py still runs its usual checks on the result, and a failed article goes on
to Gemini web / the fallback provider.
"""

import asyncio
import html
import json
import re
from typing import Dict, List, Optional, Tuple

import aiohttp

from .config import Config

# One POST carries many units (13,800 chars / 50 units worked in tests; smaller requests lose less on a retry)
CHUNK_CHARS = 4500
CHUNK_UNITS = 40
REQUEST_TIMEOUT = 40
# Articles in a row lost to request failures (network, HTTP 429 …) before Google is turned off for the run
MAX_CONSEC_FAILS = 4
TRANSLATED_KEYS = ("title", "description", "summary")
# seoscout code → Google code, where they differ
GOOGLE_LANG = {"zh": "zh-CN", "zh-tw": "zh-TW", "he": "iw"}

# Names Google would otherwise translate or respell ("Steam" → "Vapeur"). Matched case-sensitively as whole words.
PLATFORM_TERMS = (
    "Steam Deck", "Steam", "Epic Games Store", "GOG", "PC", "Windows", "macOS", "Linux",
    "PlayStation 5", "PlayStation 4", "PlayStation Store", "PlayStation Plus", "PlayStation", "PS5", "PS4",
    "Xbox Series X|S", "Xbox Series X", "Xbox Series S", "Xbox One", "Xbox Game Pass", "Game Pass", "Xbox",
    "Microsoft Store", "Nintendo Switch 2", "Nintendo Switch", "Nintendo eShop", "Nintendo", "Switch 2",
    "eShop", "Android", "iOS",
)
# "Switch" alone is the console unless it is the verb ("Switch to Russian", "Switch the language")
_SWITCH = r"Switch(?! (?:to|the|your|between|off|back|from|it|over)\b)"
# "<Game> Remastered" is also written without the edition word, so the bare title is protected too
_EDITION_RE = re.compile(
    r"\s+(?:Remastered|Remaster|Remake|Redux|Reloaded|HD|Director's Cut|"
    r"(?:Definitive|Enhanced|Deluxe|Complete|Anniversary|Special|GOTY|Game of the Year) Edition)$")

_LETTER_RE = re.compile(r"[^\W\d_]")
_PREFIX_RE = re.compile(r"^(\s*(?:>\s?)*(?:#{1,6}\s+|[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)?)(.*?)(\s*)$")
_META_LINE_RE = re.compile(r"^(\s*(?:%s)\s*:\s*)(\".*\")(,?\s*)$" % "|".join(TRANSLATED_KEYS))
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_SPAN_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.S)


class GoogleTranslateError(Exception):
    """This article cannot be taken from Google Translate (the caller moves on to the next translator)."""


class GoogleRequestError(GoogleTranslateError):
    """The endpoint did not answer properly after all retries."""


def protected_terms(topic_name: str = "", extra: str = "") -> List[str]:
    """Game name (with and without its edition word), GOOGLE_TRANSLATE_PROTECT extras and platform names,
    longest first so "Steam Deck" wins over "Steam"."""
    terms = [t.strip() for t in (extra or "").split(",")]
    topic = (topic_name or "").strip()
    if topic:
        terms.append(topic)
        bare = _EDITION_RE.sub("", topic)
        if bare != topic and len(bare.split()) >= 2:
            terms.append(bare)
    terms.extend(PLATFORM_TERMS)
    return sorted({t for t in terms if t}, key=lambda t: (-len(t), t))


_STUDIO_RE = re.compile(r"\b([A-Z][A-Za-z0-9&'-]+) (Games|Studios?|Entertainment|Interactive|Software|Publishing)\b")


def studio_terms(texts: List[str]) -> List[str]:
    """Studio / publisher names in the English articles ("Telltale Games", "PM Studios"): Google reads
    a name such as Telltale as the dictionary word. A name counts when it is written 2+ times outside
    headings; its first word alone ("Telltale") is protected too when the articles use it that way."""
    prose = "\n".join(l for t in texts for l in t.split("\n") if not l.lstrip().startswith("#"))
    count: Dict[Tuple[str, str], int] = {}
    for m in _STUDIO_RE.finditer(prose):
        count[m.groups()] = count.get(m.groups(), 0) + 1
    terms = []
    for (name, kind), n in count.items():
        if n < 2:
            continue
        terms.append(f"{name} {kind}")
        if len(re.findall(rf"(?<=[a-z,] ){re.escape(name)}(?![\w-]| {kind})", prose)) >= 2:
            terms.append(name)
    return sorted(set(terms))


def _inline_re(terms: List[str]) -> re.Pattern:
    term_alt = "|".join([re.escape(t) for t in terms] + [_SWITCH])
    return re.compile(
        r"(?P<keep>(?P<tick>`+).+?(?P=tick)"                    # inline code
        r"|!\[[^\]\n]*\]\([^)\n]*\)"                             # image
        r"|\\[^\sA-Za-z0-9]"                                     # \{ \} \< \| …
        r"|https?://[^\s<>)\]]+"                                 # bare URL
        rf"|(?<!\w)(?:{term_alt})(?!\w))"                        # game / platform / studio name ("Telltale-era" too)
        r"|(?P<link>\[(?P<ltext>[^\]\n]*)\]\((?P<lurl>[^)\n]+)\))"
        r"|(?P<bold>\*\*(?P<btext>.+?)\*\*)"
        r"|(?P<ital>(?<![\w*])\*(?P<itext>[^*\s](?:[^*]*[^*\s])?)\*(?![\w*]))"
    )


class GoogleTranslator:
    """One per translate run: shared HTTP session, request concurrency cap, stats and the off switch."""

    def __init__(self, topic_name: str = "", english_articles: List[str] = ()):
        self.studios = studio_terms(list(english_articles))
        self.terms = protected_terms(topic_name, ",".join([Config.GOOGLE_TRANSLATE_PROTECT, *self.studios]))
        topic = (topic_name or "").strip()
        self.game_names = [t for t in {topic, _EDITION_RE.sub("", topic)} if t]
        self.inline_re = _inline_re(self.terms)
        self.retries = max(0, Config.GOOGLE_TRANSLATE_RETRIES)
        self.semaphore = asyncio.Semaphore(max(1, Config.GOOGLE_TRANSLATE_CONCURRENCY))
        self.session: Optional[aiohttp.ClientSession] = None
        self.disabled = ""
        self.consec_fails = 0
        self.stats = {"ok": 0, "rejected": 0, "failed": 0, "requests": 0, "retries": 0}

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    # ── one article ─────────────────────────────────────────────

    async def translate_article(self, en_content: str, lang: str, label: str, validator=None) -> Optional[str]:
        """Translated MDX, or None when Google could not deliver a valid article (request failures after
        all retries, protected text lost, or validator(content) returned an error)."""
        try:
            content = await self._translate(en_content, lang)
        except GoogleRequestError as e:
            self.stats["failed"] += 1
            self.consec_fails += 1
            print(f"  ⚠️  Google Translate failed for {label}: {e}")
            if self.consec_fails >= MAX_CONSEC_FAILS and not self.disabled:
                self.disabled = f"{self.consec_fails} articles in a row failed"
                print(f"  ⛔ Google Translate off for the rest of this run ({self.disabled})")
            return None
        except GoogleTranslateError as e:
            self.consec_fails = 0   # the endpoint answered; only this article is unusable
            self.stats["rejected"] += 1
            print(f"  ⚠️  Google Translate result rejected for {label}: {e}")
            return None
        self.consec_fails = 0
        err = validator(content) if validator else ""
        if err:
            self.stats["rejected"] += 1
            print(f"  ⚠️  Google Translate result rejected for {label}: {err}")
            return None
        self.stats["ok"] += 1
        print(f"  🔤 Google Translate ok: {label}")
        return content

    async def _translate(self, text: str, lang: str) -> str:
        pieces, units = self._split(text)
        # identical units (repeated table headers …) are sent once
        sources: Dict[str, Tuple[str, List[str]]] = {}
        for unit in units:
            if unit not in sources:
                urls: List[str] = []
                sources[unit] = (self._to_html(unit, urls), urls)
        todo = [u for u, (h, _) in sources.items() if _LETTER_RE.search(_TAG_RE.sub("", _SPAN_RE.sub("", h)))]
        batches, batch, size = [], [], 0
        for u in todo:
            n = len(sources[u][0])
            if batch and (size + n > CHUNK_CHARS or len(batch) >= CHUNK_UNITS):
                batches.append(batch)
                batch, size = [], 0
            batch.append(u)
            size += n
        if batch:
            batches.append(batch)
        results = await asyncio.gather(
            *[self._post([sources[u][0] for u in b], lang) for b in batches], return_exceptions=True)
        translated: Dict[str, str] = {}
        for b, res in zip(batches, results):
            if isinstance(res, BaseException):
                raise res
            for u, out in zip(b, res):
                translated[u] = self._from_html(out, sources[u][0], sources[u][1], lang)
        title = next((p[1] for p in pieces if not isinstance(p, str) and p[0] == "meta"), "")
        left = self._title_keyword_left(title, translated.get(title, title))
        if left:
            raise GoogleTranslateError(f"title keyword left in English: {left!r}")
        out = []
        for piece in pieces:
            if isinstance(piece, str):
                out.append(piece)
                continue
            kind, unit = piece
            t = translated.get(unit, unit)   # nothing translatable in it (only names / code): kept as is
            if kind == "meta":
                t = json.dumps(t, ensure_ascii=False)
            elif kind == "cell":
                t = _CELL_SPLIT_RE.sub(r"\\|", t)
            out.append(t)
        return "".join(out)

    def _title_keyword_left(self, en_title: str, title: str) -> str:
        """Titles are "<Game> <Keyword>: …". Google sometimes takes the Title Case keyword for part of
        the name and keeps it ("… Remastered Russian Language : sous-titres"). Returns that keyword when
        2+ capitalised words right after the game name came back unchanged (platform names do not count)."""
        for name in sorted(self.game_names, key=len, reverse=True):
            m = re.search(re.escape(name) + r" ((?:[A-Z][\w'-]*)(?: [A-Z][\w'-]*)+)", en_title)
            if not m:
                continue
            keyword = m.group(1)
            rest = self.inline_re.sub(lambda k: "" if k.group("keep") is not None else k.group(0), keyword)
            if len(re.findall(r"[A-Z][\w'-]*", rest)) >= 2 and re.search(
                    re.escape(f"{name} {keyword}") + r"(?!\w)", title):
                return keyword
            return ""
        return ""

    # ── MDX ↔ units ─────────────────────────────────────────────

    def _split(self, text: str) -> Tuple[list, List[str]]:
        """Article → pieces: literal strings and (kind, unit text) for what gets translated."""
        lines = text.split("\n")
        if not text.startswith("export const metadata = {"):
            raise GoogleTranslateError("English article does not start with `export const metadata = {`")
        end = next((i for i, l in enumerate(lines) if l.strip() in ("}", "};")), None)
        if end is None:
            raise GoogleTranslateError("English article metadata block never closes")
        pieces, units = [], []

        def unit(kind: str, s: str):
            pieces.append((kind, s))
            units.append(s)

        fenced = False
        for i, line in enumerate(lines):
            nl = "\n" if i < len(lines) - 1 else ""
            stripped = line.strip()
            if i <= end:
                m = _META_LINE_RE.match(line)
                if m:
                    try:
                        value = json.loads(m.group(2))
                    except ValueError:
                        raise GoogleTranslateError(f"metadata line {i + 1} is not a plain double-quoted string")
                    pieces.append(m.group(1))
                    unit("meta", value)
                    pieces.append(m.group(3) + nl)
                elif re.match(r"\s*(?:%s)\s*:" % "|".join(TRANSLATED_KEYS), line):
                    raise GoogleTranslateError(f"metadata line {i + 1} is not a plain double-quoted string")
                else:
                    pieces.append(line + nl)
            elif stripped.startswith(("```", "~~~")):
                fenced = not fenced
                pieces.append(line + nl)
            elif fenced or not _LETTER_RE.search(line) or stripped.startswith("<"):
                pieces.append(line + nl)   # code, blank lines, table rulers, `---`, raw HTML
            elif stripped.startswith("|"):
                for j, cell in enumerate(_CELL_SPLIT_RE.split(line)):
                    if j:
                        pieces.append("|")
                    core = cell.strip()
                    if _LETTER_RE.search(core):
                        lead = cell[:len(cell) - len(cell.lstrip())]
                        pieces.append(lead)
                        unit("cell", core)
                        pieces.append(cell[len(lead) + len(core):])
                    else:
                        pieces.append(cell)
                pieces.append(nl)
            else:
                prefix, core, tail = _PREFIX_RE.match(line).groups()
                pieces.append(prefix)
                if _LETTER_RE.search(core):
                    unit("text", core)
                else:
                    pieces.append(core)
                pieces.append(tail + nl)
        return pieces, units

    def _to_html(self, text: str, urls: List[str]) -> str:
        out, pos = [], 0
        for m in self.inline_re.finditer(text):
            out.append(html.escape(text[pos:m.start()], quote=False))
            if m.group("keep") is not None:
                out.append('<span translate="no">' + html.escape(m.group("keep"), quote=False) + "</span>")
            elif m.group("link") is not None:
                urls.append(m.group("lurl"))
                out.append(f'<a href="{len(urls) - 1}">' + self._to_html(m.group("ltext"), urls) + "</a>")
            elif m.group("bold") is not None:
                out.append("<b>" + self._to_html(m.group("btext"), urls) + "</b>")
            else:
                out.append("<i>" + self._to_html(m.group("itext"), urls) + "</i>")
            pos = m.end()
        out.append(html.escape(text[pos:], quote=False))
        return "".join(out)

    def _from_html(self, got: str, sent: str, urls: List[str], lang: str) -> str:
        """Google's HTML → Markdown. Raises when protected text or a link did not come back intact."""
        kept_sent = sorted(html.unescape(s) for s in _SPAN_RE.findall(sent))
        s = got.replace("\n", " ")
        # Google puts a space between an inline tag and the punctuation next to it ("</span> ." / "( <b>")
        closers = r".,)\]" if lang.lower().startswith("fr") else r".,)\]:;!?“”"
        s = re.sub(rf"((?:</[a-z]+>)+)\s+(?=[{closers}])", r"\1", s)
        s = re.sub(r"(?<=[(\[¿¡])\s+(?=<[a-z])", "", s)
        s = re.sub(r"(</[a-z]+>)\s+-(?=\w)", r"\1-", s)     # </span> -Trophäen → </span>-Trophäen
        s = re.sub(r"(?<=\w['’])\s+(?=<[a-z])", "", s)   # l' <span>Xbox</span> → l'<span>Xbox</span>
        kept: List[str] = []

        def stash(m):
            kept.append(html.unescape(m.group(1)))
            return f"\x00{len(kept) - 1}\x00"
        s = _SPAN_RE.sub(stash, s)
        if sorted(kept) != kept_sent:
            raise GoogleTranslateError(f"protected text changed: sent {kept_sent}, got {sorted(kept)}")
        seen = set()

        def link(m):
            idx, inner = int(m.group(1)), m.group(2).strip()
            if idx >= len(urls) or not inner:
                raise GoogleTranslateError("link came back broken")
            seen.add(idx)
            return f"{m.group(2)[:len(m.group(2)) - len(m.group(2).lstrip())]}[{inner}]({urls[idx]})" \
                   f"{m.group(2)[len(m.group(2).rstrip()):]}"
        # spaces just inside a tag move outside it: `** text **` is not bold in Markdown
        for tag, mark in (("b", "**"), ("i", "*")):
            s = re.sub(rf"<{tag}>(\s*)(.*?)(\s*)</{tag}>",
                       lambda m, mark=mark: f"{m.group(1)}{mark}{m.group(2)}{mark}{m.group(3)}" if m.group(2) else "",
                       s, flags=re.S)
        s = re.sub(r'<a href="(\d+)">(.*?)</a>', link, s, flags=re.S)
        if len(seen) != len(urls):
            raise GoogleTranslateError(f"{len(urls) - len(seen)} of {len(urls)} links lost")
        if _TAG_RE.search(s):
            raise GoogleTranslateError(f"unexpected tag in translation: {_TAG_RE.search(s).group(0)}")
        s = html.unescape(s)
        s = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], s)
        s = re.sub(r"[ \t]{2,}", " ", s).strip()
        if not s:
            raise GoogleTranslateError("empty translation")
        return s

    # ── HTTP ────────────────────────────────────────────────────

    async def _post(self, texts: List[str], lang: str) -> List[str]:
        """One POST of HTML units; retried GOOGLE_TRANSLATE_RETRIES times on network errors, timeouts,
        non-200 answers (429 = rate limited) and malformed bodies."""
        if self.session is None:
            # trust_env: go through HTTP(S)_PROXY like the rest of the machine's tools
            self.session = aiohttp.ClientSession(trust_env=True,
                                                 timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT))
        params = {"client": "gtx", "sl": "en", "tl": GOOGLE_LANG.get(lang.lower(), lang), "format": "html"}
        last = ""
        for attempt in range(self.retries + 1):
            if attempt:
                self.stats["retries"] += 1
                await asyncio.sleep(2 * attempt)
            try:
                async with self.semaphore:
                    self.stats["requests"] += 1
                    async with self.session.post(Config.GOOGLE_TRANSLATE_ENDPOINT, params=params,
                                                 data=[("q", t) for t in texts]) as r:
                        status, body = r.status, await r.text()
                if status != 200:
                    raise GoogleRequestError(f"HTTP {status}")
                data = json.loads(body)
                out = [d[0] if isinstance(d, list) and d else d for d in data] if isinstance(data, list) else []
                if len(out) != len(texts) or not all(isinstance(o, str) and o.strip() for o in out):
                    raise GoogleRequestError(f"{len(out)} usable translations for {len(texts)} texts")
                return out
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, GoogleRequestError) as e:
                last = f"{type(e).__name__}: {e}".rstrip(": ")
                print(f"  ⚠️  Google Translate request failed (try {attempt + 1}/{self.retries + 1}): {last}")
        raise GoogleRequestError(f"no answer after {self.retries} retries ({last})")

    def print_stats(self):
        s = self.stats
        print(f"  🔤 Google Translate: {s['ok']} ok, {s['rejected']} rejected, {s['failed']} failed "
              f"| {s['requests']} requests, {s['retries']} retries"
              + (f" | off: {self.disabled}" if self.disabled else ""))
