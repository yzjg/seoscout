"""
Web 搜索和提取模块

支持并行搜索和内容提取
"""

import asyncio
import re
import aiohttp
import time
from typing import List, Dict, Tuple, Optional
from urllib.parse import urlparse, unquote, quote

from .config import Config
from .models import WebItem
from .utils import is_blocked_domain, load_cache, save_cache, get_url_hash, source_problem
from .cleaner import ContentCleaner


class TokenBucket:
    """Token Bucket 速率限制器"""

    def __init__(self, rpm: int):
        """
        初始化速率限制器

        Args:
            rpm: 每分钟请求数
        """
        self.rpm = rpm
        self.tokens = rpm
        self.last_update = time.time()
        self.lock = asyncio.Lock()

    async def acquire(self):
        """获取令牌（阻塞直到有令牌可用）"""
        async with self.lock:
            while self.tokens < 1:
                await asyncio.sleep(0.1)
                self._refill()
            self.tokens -= 1

    def _refill(self):
        """补充令牌"""
        now = time.time()
        elapsed = now - self.last_update

        # 每秒补充 rpm/60 个令牌
        self.tokens = min(self.rpm, self.tokens + elapsed * (self.rpm / 60))
        self.last_update = now


def fandom_api_url(url: str) -> Optional[str]:
    """Fandom wiki 页面 → MediaWiki parse API 地址（Jina 抓 fandom 只返回 ~500 字符拦截页）；非 fandom 返回 None"""
    p = urlparse(url)
    host = p.netloc.lower()
    if not (host.endswith(".fandom.com") and p.path.startswith("/wiki/")):
        return None
    title = unquote(p.path[len("/wiki/"):])
    if not title:
        return None
    return (f"{p.scheme or 'https'}://{p.netloc}/api.php?action=parse&format=json&formatversion=2"
            f"&redirects=1&prop=text&disableeditsection=1&page={quote(title, safe='')}")


def fandom_html_to_text(html: str) -> str:
    """parse API 返回的 HTML → 纯文本（去掉导航框、目录、脚注标记）"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style, .navbox, .toc, #toc, .mw-editsection, sup.reference, .reference"):
        tag.decompose()
    # 只在块级元素处换行，避免句子被链接/加粗拆成多行
    for tag in soup.find_all(["td", "th"]):
        tag.insert_after(" | ")
    for tag in soup.find_all(["p", "li", "tr", "br", "div", "h1", "h2", "h3", "h4", "h5", "dd", "dt", "caption", "figcaption"]):
        tag.insert_after("\n")
    lines = (re.sub(r"[ \t\xa0]+", " ", line).strip(" |") for line in soup.get_text().splitlines())
    return "\n".join(line for line in lines if line)


def fandom_subpages(html: str, title: str, limit: int = 3) -> List[str]:
    """导航页（如 Malbear → Malbear/Alpha、Malbear/Star）里链接到的子页面标题"""
    from bs4 import BeautifulSoup
    prefix = "/wiki/" + quote(title.replace(" ", "_"), safe="/") + "/"
    subs = []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = a["href"].split("#")[0].split("?")[0]
        if href.startswith(prefix):
            sub = unquote(href[len("/wiki/"):])
            if sub not in subs:
                subs.append(sub)
    return subs[:limit]


def _template(name: str) -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / "templates" / name).read_text(encoding="utf-8").strip()


def _gemini_log(kind: str, name: str):
    from pathlib import Path
    log_dir = Path(Config.LOG_DIR or ".") / kind
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / (re.sub(r"[^\w.-]+", "_", name)[:120] + ".log")


async def _ask_gemini(prompt: str, extract: str, max_wait: int, log_file, rnd: int):
    """跑一次 gemini-browser/query.py（9222 上开自己的新 tab，tab 按 targetId 绑定到这个进程，
    出错换新 tab 退避重试 GEMINI_WEB_ATTEMPTS 次）。返回 (result_dict, "") 或 (None, 失败原因)。"""
    import json
    cfg = Config
    payload = {"question": prompt, "cdp_port": cfg.GEMINI_WEB_CDP_PORT, "attempts": cfg.GEMINI_WEB_ATTEMPTS,
               "extract": extract, "max_wait": max_wait}
    if cfg.GEMINI_MODEL:
        payload["model"] = cfg.GEMINI_MODEL
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            cfg.GEMINI_PYTHON, cfg.GEMINI_QUERY_SCRIPT,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode()),
                                          timeout=cfg.GEMINI_SEARCH_TIMEOUT)
    except asyncio.TimeoutError:
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()
        return None, f"超时 {cfg.GEMINI_SEARCH_TIMEOUT}s"
    except Exception as e:
        return None, f"启动失败 {e}"
    with open(log_file, "ab") as fh:
        fh.write(f"=== round {rnd}\n".encode() + (err or b""))
    try:
        result = json.loads(out.decode("utf-8", "replace").strip().splitlines()[-1])
    except Exception:
        return None, "输出不是 JSON"
    if result.get("error"):
        return None, str(result["error"])[:200]
    return result, ""


# Gemini 说自己打不开链接时，后面常跟一段凭记忆编的"大纲"——这种不能当资料
GEMINI_REFUSAL_RE = re.compile(
    r"无法(直接)?(访问|打开|浏览|抓取|获取|读取)|不能(直接)?(访问|打开|浏览)|没有办法(访问|打开)|"
    r"can(no|')t (directly )?(access|browse|open)|unable to (access|browse|open)", re.I)


class Web:
    """Web 搜索和提取（支持并行）"""

    def __init__(self):
        self.config = Config
        self.cleaner = ContentCleaner()  # 初始化内容清理器
        self._gemini_sem = asyncio.Semaphore(max(1, Config.GEMINI_WEB_CONCURRENCY))

    async def search_batch(self, keywords: List[str], topic_name: str = '') -> Dict[str, List[WebItem]]:
        """
        并行搜索多个关键词

        Args:
            keywords: 关键词列表
            topic_name: 主题名，用于过滤不相关结果（可选）

        Returns:
            {keyword: [WebItem, ...]}
        """
        print(f"\n🔍 Web 搜索: {len(keywords)} 个关键词")
        if topic_name:
            print(f"   主题名过滤: \"{topic_name}\"")

        # 创建信号量限制并发
        semaphore = asyncio.Semaphore(self.config.WEB_SEARCH_CONCURRENCY)
        if self.config.GEMINI_WEB_SEARCH:
            print(f"   先用 Gemini 网页端搜索（CDP {self.config.GEMINI_WEB_CDP_PORT}），失败再用 Serper")

        # 并行搜索（带并发控制）
        tasks = [self._search_single(kw, semaphore, topic_name) for kw in keywords]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 构建结果字典
        result_dict = {}
        for keyword, result in zip(keywords, results):
            if isinstance(result, Exception):
                print(f"  ✗ {keyword}: {result}")
                result_dict[keyword] = []
            else:
                result_dict[keyword] = result
                print(f"  ✓ {keyword}: {len(result)} 个页面")

        return result_dict

    async def _search_single(self, keyword: str, semaphore, topic_name: str = '') -> List[WebItem]:
        """
        搜索单个关键词

        Args:
            keyword: 关键词
            semaphore: 并发控制信号量

        Returns:
            WebItem 列表
        """
        if self.config.GEMINI_WEB_SEARCH:
            items = await self._search_gemini(keyword)
            if items:
                return items

        async with semaphore:
            # 添加小延迟避免触发速率限制
            await asyncio.sleep(0.3)

            try:
                # 调用 Serper API
                url = "https://google.serper.dev/search"
                headers = {
                    "X-API-KEY": self.config.SERPER_API_KEY,
                    "Content-Type": "application/json"
                }
                payload = {
                    "q": keyword,
                    "num": self.config.WEB_SEARCH_TOP_N
                }

                # 获取搜索阶段代理配置
                proxy_url = self.config.get_proxy_url_for_stage("search")

                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, headers=headers, timeout=30, proxy=proxy_url) as response:
                        if response.status != 200:
                            raise Exception(f"Serper API 返回错误: {response.status}")

                        data = await response.json()
                        results = data.get("organic", [])

                # 过滤屏蔽域名
                filtered = [
                    r for r in results
                    if not is_blocked_domain(r.get('link', ''), self.config.BLOCKED_DOMAINS)
                ]

                # Web results are NOT filtered by topic_name
                # (only YouTube results are topic-filtered)

                # 转换为 WebItem
                items = []
                for r in filtered[:self.config.WEB_SEARCH_TOP_N]:
                    domain = urlparse(r.get('link', '')).netloc
                    items.append(WebItem(
                        title=r.get('title', ''),
                        url=r.get('link', ''),
                        domain=domain,
                        snippet=r.get('snippet', ''),
                        selected=True
                    ))

                return items

            except Exception as e:
                raise Exception(f"搜索失败: {e}")

    async def _search_gemini(self, keyword: str) -> List[WebItem]:
        """Gemini 网页端搜索：让 Gemini 在 Google 搜这个关键词、列出结果链接（gemini-browser/query.py，
        extract=links 读回答里超链接的真实地址）。query.py 每次开自己的新 tab（按 targetId 认领、只关自己的），
        页面出错时自己换新 tab 退避重试；这里再对“链接太少”的回答整轮重问一次。
        拿到至少 GEMINI_SEARCH_MIN_LINKS 条可用链接才返回，否则返回 [] 交给 Serper。"""
        cfg = self.config
        prompt = _template("web-search-gemini.md").replace("{keyword}", keyword)
        log_file = _gemini_log("gemini-search", keyword)
        reason = ""
        async with self._gemini_sem:
            for rnd in range(1, 3):
                result, reason = await _ask_gemini(prompt, "links", cfg.GEMINI_SEARCH_MAX_WAIT, log_file, rnd)
                if result is None:
                    if reason.startswith("启动失败"):
                        break
                    continue
                items, seen = [], set()
                for url in (result.get("answer") or "").split():
                    p = urlparse(url)
                    host = p.netloc.lower()
                    key = url.rstrip("/")
                    if (p.scheme not in ("http", "https") or not host or key in seen
                            or host.endswith(("google.com", "gemini.google.com"))
                            or is_blocked_domain(url, cfg.BLOCKED_DOMAINS)):
                        continue
                    seen.add(key)
                    items.append(WebItem(title=self._title_from_url(url), url=url, domain=host,
                                         snippet="", selected=True))
                items = items[:cfg.GEMINI_SEARCH_MAX_LINKS]
                if len(items) >= cfg.GEMINI_SEARCH_MIN_LINKS:
                    print(f"  🌐 Gemini 搜索 {keyword}: {len(items)} 条链接")
                    return items
                reason = f"只拿到 {len(items)} 条可用链接"
        print(f"  ↩️  Gemini 搜索失败（{reason}），改用 Serper: {keyword} (log {log_file})")
        return []

    async def _read_gemini(self, item: WebItem) -> str:
        """Gemini 网页端读链接：提示词 "{链接}将这链接内容转换成markdown格式输出出来的"，取回答里的 markdown 代码块
        （extract=code，没代码块时 query.py 换新 tab 重试）。代码块前的话里出现"无法访问"之类 = 拒答 + 编造，整轮重问；
        两轮都不行返回 ""，交给原来的 Fandom API / Jina。"""
        cfg = self.config
        prompt = _template("web-read-gemini.md").replace("{url}", item.url)
        log_file = _gemini_log("gemini-read", item.url.split("://", 1)[-1])
        reason = ""
        async with self._gemini_sem:
            for rnd in range(1, 3):
                result, reason = await _ask_gemini(prompt, "code", cfg.GEMINI_READ_MAX_WAIT, log_file, rnd)
                if result is None:
                    if reason.startswith("启动失败"):
                        break
                    continue
                md = (result.get("answer") or "").strip()
                text = result.get("text") or ""
                head = text[:max(0, text.find(md[:40]))] if md[:40] and md[:40] in text else text[:300]
                if GEMINI_REFUSAL_RE.search(head):
                    reason = f"拒答: {head.strip()[:80]!r}"
                    continue
                if len(md) < cfg.GEMINI_READ_MIN_CHARS:
                    reason = f"内容过短 {len(md)} 字符"
                    continue
                print(f"  🌐 Gemini 读取 {len(md)} 字符: {item.url[:80]}")
                return md
        print(f"  ↩️  Gemini 读取失败（{reason}），改用 Fandom API / Jina: {item.url[:80]}")
        return ""

    @staticmethod
    def _title_from_url(url: str) -> str:
        """Gemini 只给链接没有标题：用路径最后一段 + 域名拼一个可读标题（缓存文件名和资料标题用）"""
        p = urlparse(url)
        seg = unquote([s for s in p.path.split("/") if s][-1]) if p.path.strip("/") else ""
        seg = re.sub(r"[_-]+", " ", seg).strip()
        return f"{seg} | {p.netloc}" if seg else p.netloc

    def _log_filtered(self, topic_name: str, items: list, source: str = "web"):
        """记录被过滤掉的条目到日志文件，便于后期审查"""
        import json
        from pathlib import Path

        log_dir = Path(self.config.DATA_DIR) / "out" / "filter_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"filtered_{source}.jsonl"

        entry = {
            "topic_name": topic_name,
            "source": source,
            "filtered_count": len(items),
            "items": [{"title": r.get("title", ""), "link": r.get("link", "")} for r in items]
        }

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    async def extract_batch(self, items: List[WebItem]) -> List[Tuple[WebItem, str]]:
        """
        并行提取多个页面内容

        Args:
            items: WebItem 列表

        Returns:
            [(item, content), ...]
        """
        print(f"\n📥 Web 提取: {len(items)} 个页面")
        if self.config.GEMINI_WEB_READ:
            print(f"   先用 Gemini 网页端转 markdown（CDP {self.config.GEMINI_WEB_CDP_PORT}），失败再用 Fandom API / Jina")

        # 创建信号量和速率限制器
        semaphore = asyncio.Semaphore(self.config.JINA_CONCURRENCY)
        rate_limiter = TokenBucket(self.config.JINA_RPM)

        # 并行提取
        tasks = [self._extract_single(item, semaphore, rate_limiter) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计成功和失败
        success_count = sum(1 for _, content in results if content and not isinstance(content, Exception))
        print(f"  ✓ 成功: {success_count}/{len(items)}")

        return results

    async def _extract_single(self, item: WebItem, semaphore, rate_limiter) -> Tuple[WebItem, str]:
        """
        提取单个页面内容（带缓存和重试）

        Args:
            item: WebItem 对象
            semaphore: 并发控制信号量
            rate_limiter: 速率限制器

        Returns:
            (item, content) 元组
        """
        url_hash = get_url_hash(item.url)
        if self.config.GEMINI_WEB_READ:
            cache_data = load_cache(url_hash, "web", title=item.title)
            if cache_data and cache_data.get("content") and not source_problem(cache_data["content"]):
                print(f"  💾 缓存命中: {item.title[:50]}...")
                return (item, cache_data["content"])
            content = await self._read_gemini(item)
            if content and not source_problem(content):
                cleaned_content = self.cleaner.clean(content)
                save_cache(url_hash, "web", {"title": item.title, "url": item.url, "domain": item.domain,
                                             "content": cleaned_content, "source_type": "web",
                                             "extractor": "gemini-web"}, title=item.title)
                return (item, cleaned_content)

        async with semaphore:
            # 1. 检查缓存
            url_hash = get_url_hash(item.url)
            cache_data = load_cache(url_hash, "web", title=item.title)
            if cache_data and cache_data.get("content") and not source_problem(cache_data["content"]):
                print(f"  💾 缓存命中: {item.title[:50]}...")
                return (item, cache_data["content"])

            # 2. 缓存未命中，提取内容（带重试）
            for attempt in range(self.config.WEB_EXTRACT_RETRIES):
                # 速率限制
                await rate_limiter.acquire()

                try:
                    # fandom 走 MediaWiki API，其余使用 Jina Reader
                    fandom_url = fandom_api_url(item.url)
                    source = "Fandom API" if fandom_url else "Jina"
                    jina_url = fandom_url or f"https://r.jina.ai/{item.url}"
                    headers = {}

                    if self.config.JINA_API_KEY and not fandom_url:
                        headers["Authorization"] = f"Bearer {self.config.JINA_API_KEY}"

                    # 获取提取阶段代理配置
                    proxy_url = self.config.get_proxy_url_for_stage("extract")

                    # trust_env：没有配置 seoscout 代理时沿用系统的 HTTP(S)_PROXY（r.jina.ai 直连会超时）
                    async with aiohttp.ClientSession(trust_env=True) as session:
                        async with session.get(jina_url, headers=headers, timeout=30, proxy=proxy_url) as response:
                            # HTTP 错误处理
                            if response.status != 200:
                                if attempt < self.config.WEB_EXTRACT_RETRIES - 1:
                                    await asyncio.sleep(2 ** attempt)  # 指数退避：2s, 4s, 8s
                                    continue
                                print(f"    ⚠️ {source} HTTP {response.status}: {item.url[:80]}")
                                return (item, "")

                            if fandom_url:
                                data = await response.json(content_type=None)
                                if "error" in data:
                                    print(f"    ⚠️ Fandom API 错误 {data['error'].get('code')}: {item.url[:80]}")
                                    return (item, "")
                                html = data.get("parse", {}).get("text", "")
                                content = fandom_html_to_text(html)
                                if len(content.strip()) < 500:
                                    # 导航页：正文在子页面，逐个抓取并标注来源
                                    parts = []
                                    for sub in fandom_subpages(html, data.get("parse", {}).get("title", "")):
                                        sub_api = fandom_api_url(f"https://{item.domain}/wiki/{quote(sub, safe='/')}")
                                        async with session.get(sub_api, timeout=30, proxy=proxy_url) as sub_resp:
                                            sub_data = await sub_resp.json(content_type=None)
                                        sub_text = fandom_html_to_text(sub_data.get("parse", {}).get("text", ""))
                                        if sub_text:
                                            parts.append(f"## {sub}\n{sub_text}")
                                    if parts:
                                        content = "\n\n".join(parts)
                            else:
                                content = await response.text()

                            # 拦截页 / 内容过短：重试，仍不行就当抓取失败（不缓存，下次重抓）
                            problem = source_problem(content)
                            if problem:
                                if attempt < self.config.WEB_EXTRACT_RETRIES - 1:
                                    await asyncio.sleep(2 ** attempt)
                                    continue
                                print(f"    ⚠️ {source} {problem}: {item.url[:80]}")
                                return (item, "")

                            # 清理内容（移除导航链接、广告等）
                            cleaned_content = self.cleaner.clean(content)

                            # 3. 保存到缓存
                            save_cache(url_hash, "web", {
                                "title": item.title,
                                "url": item.url,
                                "domain": item.domain,
                                "content": cleaned_content,  # 保存清理后的内容
                                "source_type": "web"
                            }, title=item.title)

                            return (item, cleaned_content)

                except Exception as e:
                    if attempt == self.config.WEB_EXTRACT_RETRIES - 1:
                        # 最后一次重试失败，返回空内容
                        print(f"    ⚠️ {source} 提取失败 {type(e).__name__}: {str(e)[:120]} — {item.url[:80]}")
                        return (item, "")
                    await asyncio.sleep(2 ** attempt)  # 指数退避

            return (item, "")

