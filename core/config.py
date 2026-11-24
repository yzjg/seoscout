"""
Unified configuration management.

Loads all config from a .env file in the current working directory.
Data is stored under OUTPUT_DIR/<project_name>/ for isolation.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv


class Config:
    """Unified configuration management"""

    # Paths — set by init()
    DATA_DIR = None
    OUT_DIR = None
    BASE_DIR = None
    CACHE_DIR = None
    LOG_DIR = None

    # ============================================================
    # API Keys (loaded from .env in init())
    # ============================================================
    SERPER_API_KEY = ""
    JINA_API_KEY = ""

    # ============================================================
    # Output
    # ============================================================
    OUTPUT_DIR = "./output"
    # Set by CLI --output-dir: use this directory as the project directory instead of OUTPUT_DIR/<project>
    PROJECT_DIR_OVERRIDE = None

    # ============================================================
    # Proxy configuration
    # ============================================================
    TUNNEL_HOST = ""
    TUNNEL_PORT = 18866
    TUNNEL_USER = ""
    TUNNEL_PASS = ""
    USE_PROXY = False

    TUNNEL_PROXY_FORMAT = "tagged"
    TUNNEL_CHANNEL_PREFIX = "channel"
    TUNNEL_TTL = 60

    USE_PROXY_FOR_SEARCH = ""
    USE_PROXY_FOR_EXTRACT = ""

    # ============================================================
    # YouTube configuration
    # ============================================================
    YOUTUBE_INITIAL_RESULTS = 2
    YOUTUBE_MAX_RESULTS = 1
    YOUTUBE_MAX_DURATION = 3600
    YOUTUBE_EXTRACT_TOP_K = 1

    YOUTUBE_SEARCH_WORKERS = 10
    YOUTUBE_EXTRACT_WORKERS = 15
    YOUTUBE_RETRIES = 3
    YOUTUBE_TIMEOUT = 180

    # 字幕优先走 Gemini 网页（gemini-browser/query.py），失败再回退 youtube_transcript_api
    GEMINI_TRANSCRIPT = True
    GEMINI_CDP_PORT = 9225           # 9225 常驻 Chrome 登录的是 Gemini Ultra 账号（英文界面）
    GEMINI_MODEL = "Auto"       # 写文章和翻译用，逗号分隔按优先级：query.py 选第一个能选上的，某次失败下次换下一个；空 = 页面当前默认
                                     # （9222 中文界面 Auto 显示为"自动"，query.py 视为同一个；该账号没有 Argon，用 Neon 兜底）
    GEMINI_TRANSCRIPT_MODEL = "Auto"  # YouTube 转写用，同上按优先级（Argon/Pro 只给摘要或无回答，Hydrogen 看不到视频）
    GEMINI_QUERY_SCRIPT = str(Path.home() / ".openclaw/skills/gemini-browser/query.py")
    GEMINI_PYTHON = sys.executable
    GEMINI_ATTEMPTS = 2
    GEMINI_TIMEOUT = 900
    # 写文章 / 翻译走 Gemini 网页（常驻 Chrome 9222，与 YouTube 转写用的 GEMINI_CDP_PORT 分开），失败再用 LLM_PROVIDER 兜底
    GEMINI_WEB_CDP_PORT = 9222
    GEMINI_WEB_GENERATE = False
    GEMINI_WEB_TRANSLATE = False
    GEMINI_WEB_CONCURRENCY = 3       # 同时开几个 Gemini tab（输入/提交由 query.py 文件锁串行）
    GEMINI_WEB_ATTEMPTS = 3          # query.py 内部重试（每次新 tab，指数退避）
    GEMINI_WEB_MAX_WAIT = 600        # 单次等回答秒数
    GEMINI_WEB_TIMEOUT = 2400        # 整个 query.py 子进程的硬超时
    GEMINI_WEB_MAX_CONSEC_FAILS = 4  # 连续失败这么多次就本轮停用网页，全部走兜底
    # 元宝网页（yuanbao-browser/query.py，常驻 Chrome 9222 上已登录的 https://yuanbao.tencent.com/chat，用页面当前默认模型）
    YUANBAO_WEB_GENERATE = False
    YUANBAO_WEB_TRANSLATE = False
    YUANBAO_CDP_PORT = 9222
    YUANBAO_QUERY_SCRIPT = str(Path.home() / ".openclaw/skills/yuanbao-browser/query.py")
    YUANBAO_WEB_URL = "https://yuanbao.tencent.com/chat"
    YUANBAO_WEB_CONCURRENCY = 3
    YUANBAO_WEB_ATTEMPTS = 3
    YUANBAO_WEB_MAX_WAIT = 600
    YUANBAO_WEB_TIMEOUT = 2400
    YUANBAO_WEB_MAX_CONSEC_FAILS = 4
    # 豆包网页（doubao-browser/query.py，常驻 Chrome 9222 上已登录的 https://www.doubao.com/chat，用页面当前默认模型）
    DOUBAO_WEB_GENERATE = False
    DOUBAO_WEB_TRANSLATE = False
    DOUBAO_CDP_PORT = 9222
    DOUBAO_QUERY_SCRIPT = str(Path.home() / ".openclaw/skills/doubao-browser/query.py")
    DOUBAO_WEB_URL = "https://www.doubao.com/chat"
    DOUBAO_WEB_CONCURRENCY = 3
    DOUBAO_WEB_ATTEMPTS = 3
    DOUBAO_WEB_MAX_WAIT = 600
    DOUBAO_WEB_TIMEOUT = 2400
    DOUBAO_WEB_MAX_CONSEC_FAILS = 4
    # 写文章 元宝 → 豆包 → Gemini 之后走 Kimi 网页（kimi-browser/query.py，常驻 Chrome 9222 上已登录的 www.kimi.com/chat/；
    # KIMI_MODEL 空 = 页面当前默认模型，不动）；失败（含格式校验不过）再走 DeepSeek 网页及后面的通道
    KIMI_WEB_GENERATE = False
    KIMI_WEB_TRANSLATE = False
    KIMI_CDP_PORT = 9222
    KIMI_QUERY_SCRIPT = str(Path.home() / ".openclaw/skills/kimi-browser/query.py")
    KIMI_WEB_URL = "https://www.kimi.com/chat/"
    KIMI_MODEL = ""
    KIMI_WEB_CONCURRENCY = 3
    KIMI_WEB_ATTEMPTS = 3
    KIMI_WEB_MAX_WAIT = 600
    KIMI_WEB_TIMEOUT = 2400
    KIMI_WEB_MAX_CONSEC_FAILS = 4
    # 然后走 DeepSeek 网页（deepseek-browser/query.py，常驻 Chrome 9222 上已登录的 chat.deepseek.com；
    # 默认关掉 DeepThink / Search，只按提问里的资料写）；失败（含格式校验不过）再走后面的通道
    DEEPSEEK_WEB_GENERATE = False
    DEEPSEEK_WEB_TRANSLATE = False
    DEEPSEEK_CDP_PORT = 9222
    DEEPSEEK_QUERY_SCRIPT = str(Path.home() / ".openclaw/skills/deepseek-browser/query.py")
    DEEPSEEK_WEB_URL = "https://chat.deepseek.com/"
    DEEPSEEK_DEEPTHINK = False
    DEEPSEEK_SEARCH = False
    DEEPSEEK_WEB_CONCURRENCY = 3
    DEEPSEEK_WEB_ATTEMPTS = 3
    DEEPSEEK_WEB_MAX_WAIT = 600
    DEEPSEEK_WEB_TIMEOUT = 2400
    DEEPSEEK_WEB_MAX_CONSEC_FAILS = 4
    # 然后走 Grok 网页（grok-browser/query.py，常驻 Chrome 9222 上已登录的 grok.com；
    # GROK_MODEL 非空时页面模型按钮必须是它，空 = 页面默认）；失败（含格式校验不过）再走后面的通道
    GROK_WEB_GENERATE = False
    GROK_WEB_TRANSLATE = False
    GROK_CDP_PORT = 9222
    GROK_QUERY_SCRIPT = str(Path.home() / ".openclaw/skills/grok-browser/query.py")
    GROK_WEB_URL = "https://grok.com/"
    GROK_MODEL = ""
    GROK_WEB_CONCURRENCY = 3         # 同时开几个 Grok tab（开页/输入/提交由 query.py 文件锁串行）
    GROK_WEB_ATTEMPTS = 3            # query.py 内部重试（每次新 tab，指数退避）
    GROK_WEB_MAX_WAIT = 600          # 单次等回答秒数
    GROK_WEB_TIMEOUT = 2400          # 整个 query.py 子进程的硬超时
    GROK_WEB_MAX_CONSEC_FAILS = 4    # 连续失败这么多次就本轮停用 Grok 网页
    # （旧）Arena 网页（arena-browser/query.py，常驻 Chrome 9222 上已登录的 arena.ai 直连对话，
    # 模型由 ARENA_WEB_URL 里的 model_a 决定）；失败（含格式校验不过）再走后面的通道。逻辑与 Gemini 网页一致
    ARENA_WEB_GENERATE = False
    ARENA_WEB_TRANSLATE = False
    ARENA_CDP_PORT = 9222
    ARENA_QUERY_SCRIPT = str(Path.home() / ".openclaw/skills/arena-browser/query.py")
    ARENA_WEB_URL = "https://arena.ai/text/direct?model_a=claude-sonnet-5-5-high"
    ARENA_WEB_CONCURRENCY = 3        # 同时开几个 Arena tab（输入/提交由 query.py 文件锁串行）
    ARENA_WEB_ATTEMPTS = 3           # query.py 内部重试（每次新 tab，指数退避）
    ARENA_WEB_MAX_WAIT = 600         # 单次等回答秒数
    ARENA_WEB_TIMEOUT = 2400         # 整个 query.py 子进程的硬超时
    ARENA_WEB_MAX_CONSEC_FAILS = 4   # 连续失败这么多次就本轮停用 Arena 网页
    # 翻译第一道：免费谷歌翻译接口（core/google_translate.py）；请求失败重试后仍不行、或译文过不了校验，
    # 再走 Grok 网页 → Gemini 网页 → LLM_PROVIDER
    GOOGLE_TRANSLATE = False
    GOOGLE_TRANSLATE_RETRIES = 3      # 单次请求失败（网络异常 / 超时 / 非 200）后的重试次数
    GOOGLE_TRANSLATE_CONCURRENCY = 4  # 同时在途的请求数
    GOOGLE_TRANSLATE_PROTECT = ""     # 额外不翻译的词，逗号分隔（游戏名、平台名、文章里的厂商名已自动保护）
    GOOGLE_TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/t"

    # ============================================================
    # Web configuration
    # ============================================================
    WEB_SEARCH_TOP_N = 10
    WEB_EXTRACT_TOP_K = 1
    WEB_EXTRACT_WORKERS = 20
    WEB_EXTRACT_RETRIES = 3
    WEB_SEARCH_CONCURRENCY = 5
    JINA_RPM = 200
    JINA_CONCURRENCY = 20

    # ============================================================
    # LLM API (generate + translate)
    # ============================================================
    LLM_API_KEY = ""
    LLM_API_BASE_URL = "https://api.apifast.tech/v1"
    LLM_MODEL = "gemini-2.5-flash"
    LLM_TEMPERATURE = 0.7
    LLM_MAX_TOKENS = 24576
    LLM_TIMEOUT = 300
    LLM_RETRY_ATTEMPTS = 2
    LLM_RETRY_DELAY = 5
    # api = OpenAI-compatible HTTP API (LLM_API_*); claude_cli = `claude -p` on the
    # Claude Code subscription (no API key; temperature / max_tokens are not applied)
    LLM_PROVIDER = "api"
    CLAUDE_CLI_BIN = "claude"
    CLAUDE_CLI_MODEL = "opus"
    # Translate step only: '' = same as CLAUDE_CLI_MODEL / claude's default effort
    CLAUDE_CLI_TRANSLATE_MODEL = ""
    CLAUDE_CLI_TRANSLATE_EFFORT = ""

    # ============================================================
    # Generate concurrency
    # ============================================================
    GENERATE_BATCH_SIZE = 100
    GENERATE_CONCURRENT_LIMIT = 10
    # English article body must have at least this many words: a shorter Gemini web answer goes to the
    # fallback provider, a shorter final draft is rewritten (0 = no length check)
    GENERATE_MIN_WORDS = 1400

    # ============================================================
    # Translate concurrency
    # ============================================================
    TRANSLATE_BATCH_SIZE = 10
    TRANSLATE_BATCH_DELAY = 1

    # ============================================================
    # General
    # ============================================================
    SEARCH_MAX_RETRIES = 3
    SEARCH_RETRY_DELAY = 2

    BLOCKED_DOMAINS = {"youtube.com", "youtu.be", "reddit.com", "discord.com"}

    _initialized = False

    @classmethod
    def init(cls, project: str):
        """
        Initialize config for a project.

        Args:
            project: Project name (e.g. "my-site"). Data will be stored
                     under OUTPUT_DIR/<project>/.
        """
        # Load .env from current working directory
        load_dotenv()

        # Sanitize project name
        project_dir = project.replace('.', '_').replace('/', '_')

        # Read output root
        cls.OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./output")

        # Set up project paths (--output-dir sets the project directory directly)
        cls.DATA_DIR = cls.PROJECT_DIR_OVERRIDE or os.path.join(cls.OUTPUT_DIR, project_dir)
        cls.OUT_DIR = os.path.join(cls.DATA_DIR, "out")
        cls.BASE_DIR = cls.OUT_DIR
        cls.CACHE_DIR = os.path.join(cls.OUT_DIR, "cache")
        cls.LOG_DIR = os.path.join(cls.DATA_DIR, "logs")

        os.makedirs(cls.OUT_DIR, exist_ok=True)
        os.makedirs(cls.CACHE_DIR, exist_ok=True)
        os.makedirs(cls.LOG_DIR, exist_ok=True)

        # API Keys
        cls.SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
        cls.JINA_API_KEY = os.getenv("JINA_API_KEY", "")

        # Proxy
        cls.TUNNEL_HOST = os.getenv("TUNNEL_HOST", "")
        cls.TUNNEL_PORT = int(os.getenv("TUNNEL_PORT", "18866"))
        cls.TUNNEL_USER = os.getenv("TUNNEL_USER", "")
        cls.TUNNEL_PASS = os.getenv("TUNNEL_PASS", "")
        cls.USE_PROXY = os.getenv("USE_PROXY", "false").lower() == "true"

        cls.TUNNEL_PROXY_FORMAT = os.getenv("TUNNEL_PROXY_FORMAT", "tagged").lower()
        cls.TUNNEL_CHANNEL_PREFIX = os.getenv("TUNNEL_CHANNEL_PREFIX", "channel")
        cls.TUNNEL_TTL = int(os.getenv("TUNNEL_TTL", "60"))

        cls.USE_PROXY_FOR_SEARCH = os.getenv("USE_PROXY_FOR_SEARCH", "").lower()
        cls.USE_PROXY_FOR_EXTRACT = os.getenv("USE_PROXY_FOR_EXTRACT", "").lower()

        # YouTube
        cls.YOUTUBE_INITIAL_RESULTS = int(os.getenv("YOUTUBE_INITIAL_SEARCH_RESULTS", "2"))
        cls.YOUTUBE_MAX_RESULTS = int(os.getenv("YOUTUBE_MAX_RESULTS_AFTER_FILTER", "1"))
        cls.YOUTUBE_MAX_DURATION = int(os.getenv("YOUTUBE_MAX_DURATION", "3600"))
        cls.YOUTUBE_EXTRACT_TOP_K = int(os.getenv("YOUTUBE_EXTRACT_TOP_K", "1"))

        cls.YOUTUBE_SEARCH_WORKERS = int(os.getenv("YOUTUBE_SEARCH_WORKERS", "10"))
        cls.YOUTUBE_EXTRACT_WORKERS = int(os.getenv("YOUTUBE_TRANSCRIPT_WORKERS", "15"))
        cls.YOUTUBE_RETRIES = int(os.getenv("YOUTUBE_TRANSCRIPT_RETRIES", "3"))
        cls.YOUTUBE_TIMEOUT = int(os.getenv("YOUTUBE_SEARCH_TIMEOUT", "180"))

        cls.GEMINI_TRANSCRIPT = os.getenv("GEMINI_TRANSCRIPT", "true").lower() == "true"
        cls.GEMINI_CDP_PORT = int(os.getenv("GEMINI_CDP_PORT", "9225"))
        cls.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "Auto").strip()
        cls.GEMINI_WEB_CDP_PORT = int(os.getenv("GEMINI_WEB_CDP_PORT", "9222"))
        cls.GEMINI_TRANSCRIPT_MODEL = os.getenv("GEMINI_TRANSCRIPT_MODEL", "Auto").strip()
        cls.GEMINI_QUERY_SCRIPT = os.path.expanduser(os.getenv("GEMINI_QUERY_SCRIPT", cls.GEMINI_QUERY_SCRIPT))
        cls.GEMINI_PYTHON = os.getenv("GEMINI_PYTHON", sys.executable)
        cls.GEMINI_ATTEMPTS = int(os.getenv("GEMINI_ATTEMPTS", "2"))
        cls.GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "900"))
        cls.GEMINI_WEB_GENERATE = os.getenv("GEMINI_WEB_GENERATE", "false").lower() == "true"
        cls.GEMINI_WEB_TRANSLATE = os.getenv("GEMINI_WEB_TRANSLATE", "false").lower() == "true"
        cls.GEMINI_WEB_CONCURRENCY = int(os.getenv("GEMINI_WEB_CONCURRENCY", "3"))
        cls.GEMINI_WEB_ATTEMPTS = int(os.getenv("GEMINI_WEB_ATTEMPTS", "3"))
        cls.GEMINI_WEB_MAX_WAIT = int(os.getenv("GEMINI_WEB_MAX_WAIT", "600"))
        cls.GEMINI_WEB_TIMEOUT = int(os.getenv("GEMINI_WEB_TIMEOUT", "2400"))
        cls.GEMINI_WEB_MAX_CONSEC_FAILS = int(os.getenv("GEMINI_WEB_MAX_CONSEC_FAILS", "4"))
        # Web 搜索先问 Gemini 网页端（GEMINI_WEB_CDP_PORT 上的 Chrome），拿不到足够链接再走 Serper
        cls.GEMINI_WEB_SEARCH = os.getenv("GEMINI_WEB_SEARCH", "true").lower() == "true"
        cls.GEMINI_SEARCH_MIN_LINKS = int(os.getenv("GEMINI_SEARCH_MIN_LINKS", "3"))
        cls.GEMINI_SEARCH_MAX_LINKS = int(os.getenv("GEMINI_SEARCH_MAX_LINKS", "20"))
        cls.GEMINI_SEARCH_MAX_WAIT = int(os.getenv("GEMINI_SEARCH_MAX_WAIT", "300"))
        cls.GEMINI_SEARCH_TIMEOUT = int(os.getenv("GEMINI_SEARCH_TIMEOUT", "1200"))
        # 网页正文先让 Gemini 网页端转 markdown，拒答/太短再走原来的 Fandom API / Jina
        cls.GEMINI_WEB_READ = os.getenv("GEMINI_WEB_READ", "true").lower() == "true"
        cls.GEMINI_READ_MAX_WAIT = int(os.getenv("GEMINI_READ_MAX_WAIT", "400"))
        cls.GEMINI_READ_MIN_CHARS = int(os.getenv("GEMINI_READ_MIN_CHARS", "500"))
        cls.YUANBAO_WEB_GENERATE = os.getenv("YUANBAO_WEB_GENERATE", "false").lower() == "true"
        cls.YUANBAO_WEB_TRANSLATE = os.getenv("YUANBAO_WEB_TRANSLATE", "false").lower() == "true"
        cls.YUANBAO_CDP_PORT = int(os.getenv("YUANBAO_CDP_PORT", "9222"))
        cls.YUANBAO_QUERY_SCRIPT = os.path.expanduser(os.getenv("YUANBAO_QUERY_SCRIPT", cls.YUANBAO_QUERY_SCRIPT))
        cls.YUANBAO_WEB_URL = os.getenv("YUANBAO_WEB_URL", cls.YUANBAO_WEB_URL)
        cls.YUANBAO_WEB_CONCURRENCY = int(os.getenv("YUANBAO_WEB_CONCURRENCY", "3"))
        cls.YUANBAO_WEB_ATTEMPTS = int(os.getenv("YUANBAO_WEB_ATTEMPTS", "3"))
        cls.YUANBAO_WEB_MAX_WAIT = int(os.getenv("YUANBAO_WEB_MAX_WAIT", "600"))
        cls.YUANBAO_WEB_TIMEOUT = int(os.getenv("YUANBAO_WEB_TIMEOUT", "2400"))
        cls.YUANBAO_WEB_MAX_CONSEC_FAILS = int(os.getenv("YUANBAO_WEB_MAX_CONSEC_FAILS", "4"))
        cls.DOUBAO_WEB_GENERATE = os.getenv("DOUBAO_WEB_GENERATE", "false").lower() == "true"
        cls.DOUBAO_WEB_TRANSLATE = os.getenv("DOUBAO_WEB_TRANSLATE", "false").lower() == "true"
        cls.DOUBAO_CDP_PORT = int(os.getenv("DOUBAO_CDP_PORT", "9222"))
        cls.DOUBAO_QUERY_SCRIPT = os.path.expanduser(os.getenv("DOUBAO_QUERY_SCRIPT", cls.DOUBAO_QUERY_SCRIPT))
        cls.DOUBAO_WEB_URL = os.getenv("DOUBAO_WEB_URL", cls.DOUBAO_WEB_URL)
        cls.DOUBAO_WEB_CONCURRENCY = int(os.getenv("DOUBAO_WEB_CONCURRENCY", "3"))
        cls.DOUBAO_WEB_ATTEMPTS = int(os.getenv("DOUBAO_WEB_ATTEMPTS", "3"))
        cls.DOUBAO_WEB_MAX_WAIT = int(os.getenv("DOUBAO_WEB_MAX_WAIT", "600"))
        cls.DOUBAO_WEB_TIMEOUT = int(os.getenv("DOUBAO_WEB_TIMEOUT", "2400"))
        cls.DOUBAO_WEB_MAX_CONSEC_FAILS = int(os.getenv("DOUBAO_WEB_MAX_CONSEC_FAILS", "4"))
        cls.KIMI_WEB_GENERATE = os.getenv("KIMI_WEB_GENERATE", "false").lower() == "true"
        cls.KIMI_WEB_TRANSLATE = os.getenv("KIMI_WEB_TRANSLATE", "false").lower() == "true"
        cls.KIMI_CDP_PORT = int(os.getenv("KIMI_CDP_PORT", "9222"))
        cls.KIMI_QUERY_SCRIPT = os.path.expanduser(os.getenv("KIMI_QUERY_SCRIPT", cls.KIMI_QUERY_SCRIPT))
        cls.KIMI_WEB_URL = os.getenv("KIMI_WEB_URL", cls.KIMI_WEB_URL)
        cls.KIMI_MODEL = os.getenv("KIMI_MODEL", "").strip()
        cls.KIMI_WEB_CONCURRENCY = int(os.getenv("KIMI_WEB_CONCURRENCY", "3"))
        cls.KIMI_WEB_ATTEMPTS = int(os.getenv("KIMI_WEB_ATTEMPTS", "3"))
        cls.KIMI_WEB_MAX_WAIT = int(os.getenv("KIMI_WEB_MAX_WAIT", "600"))
        cls.KIMI_WEB_TIMEOUT = int(os.getenv("KIMI_WEB_TIMEOUT", "2400"))
        cls.KIMI_WEB_MAX_CONSEC_FAILS = int(os.getenv("KIMI_WEB_MAX_CONSEC_FAILS", "4"))
        cls.DEEPSEEK_WEB_GENERATE = os.getenv("DEEPSEEK_WEB_GENERATE", "false").lower() == "true"
        cls.DEEPSEEK_WEB_TRANSLATE = os.getenv("DEEPSEEK_WEB_TRANSLATE", "false").lower() == "true"
        cls.DEEPSEEK_CDP_PORT = int(os.getenv("DEEPSEEK_CDP_PORT", "9222"))
        cls.DEEPSEEK_QUERY_SCRIPT = os.path.expanduser(os.getenv("DEEPSEEK_QUERY_SCRIPT", cls.DEEPSEEK_QUERY_SCRIPT))
        cls.DEEPSEEK_WEB_URL = os.getenv("DEEPSEEK_WEB_URL", cls.DEEPSEEK_WEB_URL)
        cls.DEEPSEEK_DEEPTHINK = os.getenv("DEEPSEEK_DEEPTHINK", "false").lower() == "true"
        cls.DEEPSEEK_SEARCH = os.getenv("DEEPSEEK_SEARCH", "false").lower() == "true"
        cls.DEEPSEEK_WEB_CONCURRENCY = int(os.getenv("DEEPSEEK_WEB_CONCURRENCY", "3"))
        cls.DEEPSEEK_WEB_ATTEMPTS = int(os.getenv("DEEPSEEK_WEB_ATTEMPTS", "3"))
        cls.DEEPSEEK_WEB_MAX_WAIT = int(os.getenv("DEEPSEEK_WEB_MAX_WAIT", "600"))
        cls.DEEPSEEK_WEB_TIMEOUT = int(os.getenv("DEEPSEEK_WEB_TIMEOUT", "2400"))
        cls.DEEPSEEK_WEB_MAX_CONSEC_FAILS = int(os.getenv("DEEPSEEK_WEB_MAX_CONSEC_FAILS", "4"))
        cls.GROK_WEB_GENERATE = os.getenv("GROK_WEB_GENERATE", "false").lower() == "true"
        cls.GROK_WEB_TRANSLATE = os.getenv("GROK_WEB_TRANSLATE", "false").lower() == "true"
        cls.GROK_CDP_PORT = int(os.getenv("GROK_CDP_PORT", "9222"))
        cls.GROK_QUERY_SCRIPT = os.path.expanduser(os.getenv("GROK_QUERY_SCRIPT", cls.GROK_QUERY_SCRIPT))
        cls.GROK_WEB_URL = os.getenv("GROK_WEB_URL", cls.GROK_WEB_URL)
        cls.GROK_MODEL = os.getenv("GROK_MODEL", "").strip()
        cls.GROK_WEB_CONCURRENCY = int(os.getenv("GROK_WEB_CONCURRENCY", "3"))
        cls.GROK_WEB_ATTEMPTS = int(os.getenv("GROK_WEB_ATTEMPTS", "3"))
        cls.GROK_WEB_MAX_WAIT = int(os.getenv("GROK_WEB_MAX_WAIT", "600"))
        cls.GROK_WEB_TIMEOUT = int(os.getenv("GROK_WEB_TIMEOUT", "2400"))
        cls.GROK_WEB_MAX_CONSEC_FAILS = int(os.getenv("GROK_WEB_MAX_CONSEC_FAILS", "4"))
        cls.ARENA_WEB_GENERATE = os.getenv("ARENA_WEB_GENERATE", "false").lower() == "true"
        cls.ARENA_WEB_TRANSLATE = os.getenv("ARENA_WEB_TRANSLATE", "false").lower() == "true"
        cls.ARENA_CDP_PORT = int(os.getenv("ARENA_CDP_PORT", "9222"))
        cls.ARENA_QUERY_SCRIPT = os.path.expanduser(os.getenv("ARENA_QUERY_SCRIPT", cls.ARENA_QUERY_SCRIPT))
        cls.ARENA_WEB_URL = os.getenv("ARENA_WEB_URL", cls.ARENA_WEB_URL)
        cls.ARENA_WEB_CONCURRENCY = int(os.getenv("ARENA_WEB_CONCURRENCY", "3"))
        cls.ARENA_WEB_ATTEMPTS = int(os.getenv("ARENA_WEB_ATTEMPTS", "3"))
        cls.ARENA_WEB_MAX_WAIT = int(os.getenv("ARENA_WEB_MAX_WAIT", "600"))
        cls.ARENA_WEB_TIMEOUT = int(os.getenv("ARENA_WEB_TIMEOUT", "2400"))
        cls.ARENA_WEB_MAX_CONSEC_FAILS = int(os.getenv("ARENA_WEB_MAX_CONSEC_FAILS", "4"))
        cls.GOOGLE_TRANSLATE = os.getenv("GOOGLE_TRANSLATE", "false").lower() == "true"
        cls.GOOGLE_TRANSLATE_RETRIES = int(os.getenv("GOOGLE_TRANSLATE_RETRIES", "3"))
        cls.GOOGLE_TRANSLATE_CONCURRENCY = int(os.getenv("GOOGLE_TRANSLATE_CONCURRENCY", "4"))
        cls.GOOGLE_TRANSLATE_PROTECT = os.getenv("GOOGLE_TRANSLATE_PROTECT", "")
        cls.GOOGLE_TRANSLATE_ENDPOINT = os.getenv("GOOGLE_TRANSLATE_ENDPOINT", cls.GOOGLE_TRANSLATE_ENDPOINT)

        # Web
        cls.WEB_SEARCH_TOP_N = int(os.getenv("WEB_SEARCH_TOP_N", "10"))
        cls.WEB_EXTRACT_TOP_K = int(os.getenv("WEB_EXTRACT_TOP_K", "1"))
        cls.WEB_EXTRACT_WORKERS = int(os.getenv("JINA_CONCURRENCY", "20"))
        cls.WEB_EXTRACT_RETRIES = int(os.getenv("WEB_EXTRACT_RETRIES", "3"))
        cls.WEB_SEARCH_CONCURRENCY = int(os.getenv("WEB_SEARCH_CONCURRENCY", "5"))
        cls.JINA_RPM = int(os.getenv("JINA_RPM", "200"))
        cls.JINA_CONCURRENCY = int(os.getenv("JINA_CONCURRENCY", "20"))

        # General
        cls.SEARCH_MAX_RETRIES = int(os.getenv("SEARCH_MAX_RETRIES", "3"))
        cls.SEARCH_RETRY_DELAY = int(os.getenv("SEARCH_RETRY_DELAY", "2"))

        # LLM API (generate + translate)
        cls.LLM_API_KEY = os.getenv("LLM_API_KEY", "")
        cls.LLM_API_BASE_URL = os.getenv("LLM_API_BASE_URL", "https://api.apifast.tech/v1")
        cls.LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
        cls.LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        cls.LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "24576"))
        cls.LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "300"))
        cls.LLM_RETRY_ATTEMPTS = int(os.getenv("LLM_RETRY_ATTEMPTS", "2"))
        cls.LLM_RETRY_DELAY = int(os.getenv("LLM_RETRY_DELAY", "5"))
        cls.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "api").strip().lower()
        if cls.LLM_PROVIDER not in ("api", "claude_cli"):
            raise ValueError(f"LLM_PROVIDER must be 'api' or 'claude_cli', got {cls.LLM_PROVIDER!r}")
        cls.CLAUDE_CLI_BIN = os.getenv("CLAUDE_CLI_BIN", "claude")
        cls.CLAUDE_CLI_MODEL = os.getenv("CLAUDE_CLI_MODEL", "opus")
        cls.CLAUDE_CLI_TRANSLATE_MODEL = os.getenv("CLAUDE_CLI_TRANSLATE_MODEL", "").strip() or cls.CLAUDE_CLI_MODEL
        cls.CLAUDE_CLI_TRANSLATE_EFFORT = os.getenv("CLAUDE_CLI_TRANSLATE_EFFORT", "").strip()

        # Generate concurrency
        cls.GENERATE_BATCH_SIZE = int(os.getenv("GENERATE_BATCH_SIZE", "100"))
        cls.GENERATE_CONCURRENT_LIMIT = int(os.getenv("GENERATE_CONCURRENT_LIMIT", "10"))
        cls.GENERATE_MIN_WORDS = int(os.getenv("GENERATE_MIN_WORDS", "1400"))

        # Translate concurrency
        cls.TRANSLATE_BATCH_SIZE = int(os.getenv("TRANSLATE_BATCH_SIZE", "10"))
        cls.TRANSLATE_BATCH_DELAY = int(os.getenv("TRANSLATE_BATCH_DELAY", "1"))

        cls.BLOCKED_DOMAINS = set(
            d.strip()
            for d in os.getenv("BLOCKED_DOMAINS",
                "youtube.com,youtu.be,reddit.com,discord.com").split(",")
            if d.strip()
        )

        cls._initialized = True

    @classmethod
    def web_channels(cls, step: str) -> list:
        """Web-page models to try before LLM_PROVIDER, in order, for step 'generate' or 'translate':
        generate: Yuanbao web → Doubao web → Gemini web → Kimi web → DeepSeek web → Grok web (→ Arena web if switched on);
        translate: (enabled ones of) Yuanbao/Doubao/Kimi/DeepSeek/Grok/Arena web, then Gemini web last. Each one
        is driven by its own <skill>/query.py (same JSON contract), in a resident Chrome. Translate tries Google Translate
        before all of them."""
        on = step.upper()
        channels = []
        if getattr(cls, f"YUANBAO_WEB_{on}"):
            channels.append({
                "name": "yuanbao", "title": "Yuanbao web", "script": cls.YUANBAO_QUERY_SCRIPT,
                "port": cls.YUANBAO_CDP_PORT, "concurrency": cls.YUANBAO_WEB_CONCURRENCY,
                "attempts": cls.YUANBAO_WEB_ATTEMPTS, "max_wait": cls.YUANBAO_WEB_MAX_WAIT,
                "timeout": cls.YUANBAO_WEB_TIMEOUT, "max_consec_fails": cls.YUANBAO_WEB_MAX_CONSEC_FAILS,
                "payload": {"url": cls.YUANBAO_WEB_URL},
            })
        if getattr(cls, f"DOUBAO_WEB_{on}"):
            channels.append({
                "name": "doubao", "title": "Doubao web", "script": cls.DOUBAO_QUERY_SCRIPT,
                "port": cls.DOUBAO_CDP_PORT, "concurrency": cls.DOUBAO_WEB_CONCURRENCY,
                "attempts": cls.DOUBAO_WEB_ATTEMPTS, "max_wait": cls.DOUBAO_WEB_MAX_WAIT,
                "timeout": cls.DOUBAO_WEB_TIMEOUT, "max_consec_fails": cls.DOUBAO_WEB_MAX_CONSEC_FAILS,
                "payload": {"url": cls.DOUBAO_WEB_URL},
            })
        gemini = None
        if getattr(cls, f"GEMINI_WEB_{on}"):
            gemini = {
                "name": "gemini", "title": "Gemini web", "script": cls.GEMINI_QUERY_SCRIPT,
                "port": cls.GEMINI_WEB_CDP_PORT, "concurrency": cls.GEMINI_WEB_CONCURRENCY,
                "attempts": cls.GEMINI_WEB_ATTEMPTS, "max_wait": cls.GEMINI_WEB_MAX_WAIT,
                "timeout": cls.GEMINI_WEB_TIMEOUT, "max_consec_fails": cls.GEMINI_WEB_MAX_CONSEC_FAILS,
                "payload": {"model": cls.GEMINI_MODEL} if cls.GEMINI_MODEL else {},
            }
            # 写文章 Gemini 排在元宝、豆包之后；翻译仍按原顺序放最后（Grok → Gemini）
            if step == "generate":
                channels.append(gemini)
        if getattr(cls, f"KIMI_WEB_{on}"):
            channels.append({
                "name": "kimi", "title": "Kimi web", "script": cls.KIMI_QUERY_SCRIPT,
                "port": cls.KIMI_CDP_PORT, "concurrency": cls.KIMI_WEB_CONCURRENCY,
                "attempts": cls.KIMI_WEB_ATTEMPTS, "max_wait": cls.KIMI_WEB_MAX_WAIT,
                "timeout": cls.KIMI_WEB_TIMEOUT, "max_consec_fails": cls.KIMI_WEB_MAX_CONSEC_FAILS,
                "payload": {"url": cls.KIMI_WEB_URL, **({"model": cls.KIMI_MODEL} if cls.KIMI_MODEL else {})},
            })
        if getattr(cls, f"DEEPSEEK_WEB_{on}"):
            channels.append({
                "name": "deepseek", "title": "DeepSeek web", "script": cls.DEEPSEEK_QUERY_SCRIPT,
                "port": cls.DEEPSEEK_CDP_PORT, "concurrency": cls.DEEPSEEK_WEB_CONCURRENCY,
                "attempts": cls.DEEPSEEK_WEB_ATTEMPTS, "max_wait": cls.DEEPSEEK_WEB_MAX_WAIT,
                "timeout": cls.DEEPSEEK_WEB_TIMEOUT, "max_consec_fails": cls.DEEPSEEK_WEB_MAX_CONSEC_FAILS,
                "payload": {"url": cls.DEEPSEEK_WEB_URL, "deepthink": cls.DEEPSEEK_DEEPTHINK,
                            "search": cls.DEEPSEEK_SEARCH},
            })
        if getattr(cls, f"GROK_WEB_{on}"):
            channels.append({
                "name": "grok", "title": "Grok web", "script": cls.GROK_QUERY_SCRIPT,
                "port": cls.GROK_CDP_PORT, "concurrency": cls.GROK_WEB_CONCURRENCY,
                "attempts": cls.GROK_WEB_ATTEMPTS, "max_wait": cls.GROK_WEB_MAX_WAIT,
                "timeout": cls.GROK_WEB_TIMEOUT, "max_consec_fails": cls.GROK_WEB_MAX_CONSEC_FAILS,
                "payload": {"url": cls.GROK_WEB_URL, **({"model": cls.GROK_MODEL} if cls.GROK_MODEL else {})},
            })
        if getattr(cls, f"ARENA_WEB_{on}"):
            channels.append({
                "name": "arena", "title": "Arena web", "script": cls.ARENA_QUERY_SCRIPT,
                "port": cls.ARENA_CDP_PORT, "concurrency": cls.ARENA_WEB_CONCURRENCY,
                "attempts": cls.ARENA_WEB_ATTEMPTS, "max_wait": cls.ARENA_WEB_MAX_WAIT,
                "timeout": cls.ARENA_WEB_TIMEOUT, "max_consec_fails": cls.ARENA_WEB_MAX_CONSEC_FAILS,
                "payload": {"url": cls.ARENA_WEB_URL},
            })
        if gemini and step != "generate":
            channels.append(gemini)
        return channels

    @classmethod
    def llm_label(cls, translate: bool = False) -> str:
        """Model name actually used for generate / translate."""
        if cls.LLM_PROVIDER == "claude_cli":
            if translate:
                effort = f" --effort {cls.CLAUDE_CLI_TRANSLATE_EFFORT}" if cls.CLAUDE_CLI_TRANSLATE_EFFORT else ""
                return f"claude -p --model {cls.CLAUDE_CLI_TRANSLATE_MODEL}{effort}"
            return f"claude -p --model {cls.CLAUDE_CLI_MODEL}"
        return cls.LLM_MODEL

    @classmethod
    def get_proxy_url(cls) -> str:
        if not cls.USE_PROXY or not cls.TUNNEL_HOST:
            return None

        if cls.TUNNEL_PROXY_FORMAT == "tagged":
            channel = f"{cls.TUNNEL_CHANNEL_PREFIX}-default"
            return f"http://{cls.TUNNEL_USER}:{cls.TUNNEL_PASS}:{channel}:{cls.TUNNEL_TTL}@{cls.TUNNEL_HOST}:{cls.TUNNEL_PORT}"
        else:
            return f"http://{cls.TUNNEL_USER}:{cls.TUNNEL_PASS}@{cls.TUNNEL_HOST}:{cls.TUNNEL_PORT}"

    @classmethod
    def use_proxy_for_stage(cls, stage: str) -> bool:
        if stage == "search":
            if cls.USE_PROXY_FOR_SEARCH in ("true", "false"):
                return cls.USE_PROXY_FOR_SEARCH == "true"
            return cls.USE_PROXY
        elif stage == "extract":
            if cls.USE_PROXY_FOR_EXTRACT in ("true", "false"):
                return cls.USE_PROXY_FOR_EXTRACT == "true"
            return cls.USE_PROXY
        else:
            return cls.USE_PROXY

    @classmethod
    def get_proxy_url_for_stage(cls, stage: str) -> str:
        if not cls.use_proxy_for_stage(stage) or not cls.TUNNEL_HOST:
            return None

        if cls.TUNNEL_PROXY_FORMAT == "tagged":
            channel = f"{cls.TUNNEL_CHANNEL_PREFIX}-{stage}"
            return f"http://{cls.TUNNEL_USER}:{cls.TUNNEL_PASS}:{channel}:{cls.TUNNEL_TTL}@{cls.TUNNEL_HOST}:{cls.TUNNEL_PORT}"
        else:
            return f"http://{cls.TUNNEL_USER}:{cls.TUNNEL_PASS}@{cls.TUNNEL_HOST}:{cls.TUNNEL_PORT}"

    @classmethod
    def validate(cls) -> bool:
        errors = []

        if not cls.SERPER_API_KEY:
            errors.append("SERPER_API_KEY not set")

        if not cls.JINA_API_KEY:
            errors.append("JINA_API_KEY not set (optional, but recommended for higher rate limits)")

        if cls.USE_PROXY and not cls.TUNNEL_HOST:
            errors.append("USE_PROXY=true but TUNNEL_HOST not set")

        if errors:
            print("⚠️  Config warnings:")
            for error in errors:
                print(f"  - {error}")
            return False

        return True

    @classmethod
    def print_summary(cls):
        print("\n" + "=" * 70)
        print("  Configuration")
        print("=" * 70)
        print(f"Data dir:    {cls.DATA_DIR}")
        print(f"Output dir:  {cls.OUT_DIR}")
        print(f"\nYouTube:")
        print(f"  - Initial results: {cls.YOUTUBE_INITIAL_RESULTS}")
        print(f"  - Max results:     {cls.YOUTUBE_MAX_RESULTS}")
        print(f"  - Max duration:    {cls.YOUTUBE_MAX_DURATION}s")
        print(f"  - Extract top-k:   {cls.YOUTUBE_EXTRACT_TOP_K}")
        print(f"  - Search workers:  {cls.YOUTUBE_SEARCH_WORKERS}")
        print(f"  - Extract workers: {cls.YOUTUBE_EXTRACT_WORKERS}")
        print(f"\nWeb:")
        print(f"  - Search results:  {cls.WEB_SEARCH_TOP_N}")
        print(f"  - Search workers:  {cls.WEB_SEARCH_CONCURRENCY}")
        print(f"  - Extract top-k:   {cls.WEB_EXTRACT_TOP_K}")
        print(f"  - Jina RPM:        {cls.JINA_RPM}")
        print(f"  - Jina concurrency:{cls.JINA_CONCURRENCY}")
        print(f"\nGeneral:")
        print(f"  - Blocked domains: {len(cls.BLOCKED_DOMAINS)}")
        print(f"  - Use proxy:       {'yes' if cls.USE_PROXY else 'no'}")
        print(f"  - Search retries:  {cls.SEARCH_MAX_RETRIES}")
        print(f"\nLLM:")
        print(f"  - Provider:        {cls.LLM_PROVIDER} ({cls.llm_label()})")
        if cls.LLM_PROVIDER == "claude_cli":
            print(f"  - Claude CLI:      {cls.CLAUDE_CLI_BIN} (model {cls.CLAUDE_CLI_MODEL})")
        else:
            print(f"  - Model:           {cls.LLM_MODEL}")
            print(f"  - API base:        {cls.LLM_API_BASE_URL}")
            print(f"  - Max tokens:      {cls.LLM_MAX_TOKENS}")
        print(f"  - Concurrency:     {cls.GENERATE_CONCURRENT_LIMIT}")
        print(f"  - Gen batch size:  {cls.GENERATE_BATCH_SIZE}")
        print(f"  - Xlate batch:     {cls.TRANSLATE_BATCH_SIZE}")
        print("=" * 70 + "\n")
