try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:
    ZoneInfo = None
    class ZoneInfoNotFoundError(Exception): ...
from datetime import timezone, timedelta

def get_beijing_tz():
    if ZoneInfo:
        try:
            return ZoneInfo("Asia/Shanghai")
        except ZoneInfoNotFoundError:
            pass
    return timezone(timedelta(hours=8))  # 兜底

LOCAL_TZ = get_beijing_tz()

# -------------------------------
# 调试 / 行为
# -------------------------------
DEBUG = True
DRY_RUN = False                 # 先干跑
LIMIT_PER_ORG = 0
DOWNLOAD_CONCURRENCY = 4
CONNECT_TIMEOUT_SEC = 30
READ_TIMEOUT_SEC = 120

# 时间窗口依据： 'updated'（昨天有任何更新就算）| 'published'（昨天首次投稿）| 'both'
WINDOW_FIELD = "published"       # ← 新增：用来解决“跨月编号”带来的困惑

# -------------------------------
# PDF 分类相关
# -------------------------------
CLASSIFY_FROM_PDF = True          # True=按 PDF 作者/单位区匹配；False=沿用摘要/标题
PDF_CACHE_DIR = "cache_pdfs"      # 统一缓存目录
USE_HARDLINKS = True              # Windows若无权限会自动回退为复制
MAX_PDF_PAGES_TO_SCAN = 2         # 只扫前2页（作者/单位通常在首页/次页）
PDF_EXTRACT_ENGINE = "pymupdf"    # "pymupdf"（推荐）| "pypdf"（备选）

# （可选）作者/单位区“关键词”提示，用于简单启发式筛行
AFFIL_HINT_KEYWORDS = [
    "University", "Institute", "Laboratory", "Lab", "Dept", "Department",
    "College", "School", "Center", "Centre"
]

# -------------------------------
# arXiv API & 网络
# -------------------------------
ARXIV_API_ENDPOINTS = [
    "https://arxiv.org/api/query",       # ← 先用主站
    "https://export.arxiv.org/api/query",
    "http://export.arxiv.org/api/query",
]
REQUEST_TIMEOUT = (20, 120)   # (connect_timeout, read_timeout)

RETRY_TOTAL = 7               # ↑稍微加大重试次数更稳
RETRY_BACKOFF = 1.5

REQUESTS_UA = "DailyPaper/1.0 (+contact: your_email@example.com)"

PROXIES = None
RESPECT_ENV_PROXIES = True
NO_PROXY_HOSTS = ["arxiv.org", "export.arxiv.org"]

# 拉取范围 / 分页
MAX_RESULTS_PER_PAGE = 100     # 每页上限 200
MAX_PAGES = 5                # 10 页≈2000条（足够覆盖昨天窗口）

# 直搜（fallback）分页（给 app.py 的 per-org 直搜使用）
PER_ORG_SEARCH_LIMIT_PAGES = 5       # ← 新增：每个机构直搜最多扫几页
PER_ORG_SEARCH_PAGE_SIZE   = 200     # ← 新增：每页多少条（建议 200）

# -------------------------------
# 输出 & 匹配
# -------------------------------
OUT_BASE_DIR = "output_org_pdfs"

INSTITUTIONS_PATTERNS = {
    # ---- 国际公司 ----
    "Apple":        [r"\bApple(?:\s+Research)?\b"],
    "Meta":         [r"\bMeta(?:\s+AI)?\b", r"\bFAIR\b", r"\bFacebook\s*AI\s*Research\b"],
    "Google":       [r"\bGoogle(?:\s*Research)?\b", r"\bGoogle\s*DeepMind\b", r"\bDeepMind\b"],
    "NVIDIA":       [r"\bNVIDIA\b", r"\bNVidia\b"],

    # ---- 中国公司 ----
    "Tencent":      [r"\bTencent\b", r"腾讯"],
    "ByteDance":    [r"\bByteDance\b", r"字节跳动"],
    "Alibaba":      [r"\bAlibaba\b", r"\bAliyun\b", r"阿里巴巴"],

    # ---- 顶尖高校 ----
    "MIT":          [r"\bMIT\b", r"\bMassachusetts\s*Institute\s*of\s*Technology\b", r"\bCSAIL\b"],
    "Stanford":     [r"\bStanford\b", r"\bStanford\s*University\b"],

    # ---- 国际科技公司 ----
    "Microsoft":    [r"\bMicrosoft\b", r"\bMicrosoft\s*Research\b", r"\bMSR\b",
                     r"\bMSRA\b", r"\bMicrosoft\s*Research\s*Asia\b"],
    "OpenAI":       [r"\bOpenAI\b"],
    "Anthropic":    [r"\bAnthropic\b"],
    "IBM":          [r"\bIBM\b", r"\bIBM\s*Research\b"],
    "Amazon":       [r"\bAmazon\b", r"\bAWS\b", r"\bAmazon\s*AI\b", r"\bAWS\s*AI\b",
                     r"\bAmazon\s*Science\b", r"\bAWS\s*AI\s*Labs?\b"],

    # ---- 中国大厂 ----
    "Huawei":       [r"\bHuawei\b", r"\bHuawei\s*Noah'?s\s*Ark\s*Lab\b", r"华为", r"诺亚方舟"],
    "Baidu":        [r"\bBaidu\b", r"百度"],
    "SenseTime":    [r"\bSenseTime\b", r"商汤"],
    "Megvii":       [r"\bMegvii\b", r"旷视"],
    "Yitu":         [r"\bYitu\b", r"依图"],

    # ---- 开源/研究组织 ----
    "AI2":          [r"\bAllen\s*Institute\s*for\s*AI\b", r"\bAllen\s*Institute\b", r"\bAI2\b", r"\bAllen\s*AI\b"],
    "HuggingFace":  [r"\bHugging\s*Face\b", r"\bHuggingFace\b"],
    "LAION":        [r"\bLAION\b"],
    "EleutherAI":   [r"\bEleuther\s*AI\b", r"\bEleutherAI\b"],

    # ---- 高校扩展 ----
    "CMU":          [r"\bCMU\b", r"\bCarnegie\s*Mellon\b", r"\bCarnegie\s*Mellon\s*University\b"],
    "Berkeley":     [r"\bUC\s*Berkeley\b", r"\bUCB\b", r"\bBerkeley\b", r"\bUniversity\s*of\s*California,\s*Berkeley\b"],
    "Tsinghua":     [r"\bTsinghua\b", r"清华", r"\bTsinghua\s*University\b"],
    "PekingU":      [r"\bPeking\s*University\b", r"\bPKU\b", r"北京大学"],
    "Oxford":       [r"\bOxford\b", r"\bUniversity\s*of\s*Oxford\b"],
    "Cambridge":    [r"\bCambridge\b", r"\bUniversity\s*of\s*Cambridge\b"],
    "ETH":          [r"\bETH\b", r"\bETH\s*Z(?:u|ü)rich\b", r"\bETH\s*Zurich\b", r"\bETH\s*Zürich\b"],
}

ORG_SEARCH_TERMS = {
    "Apple":    ['"Apple"', '"Apple Research"'],
    "Meta":     ['"Meta"', '"Meta AI"', '"FAIR"', '"Facebook AI Research"'],
    "Google":   ['"Google"', '"Google Research"', '"Google DeepMind"', '"DeepMind"'],
    "NVIDIA":   ['"NVIDIA"'],
    "Tencent":  ['"Tencent"', '腾讯'],
    "ByteDance":['"ByteDance"', '字节跳动'],
    "Alibaba":  ['"Alibaba"', '"Aliyun"', '阿里巴巴'],
    "MIT":      ['"MIT"', '"Massachusetts Institute of Technology"', '"CSAIL"'],
    "Stanford": ['"Stanford"', '"Stanford University"'],
    "Microsoft": ['"Microsoft"', '"Microsoft Research"', '"MSR"', '"MSRA"', '"Microsoft Research Asia"'],
    "OpenAI":    ['"OpenAI"'],
    "Anthropic": ['"Anthropic"'],
    "IBM":       ['"IBM"', '"IBM Research"'],
    "Amazon":    ['"Amazon"', '"AWS"', '"Amazon AI"', '"AWS AI"', '"Amazon Science"', '"AWS AI Labs"'],
    "Huawei":    ['"Huawei"', '"Noah\'s Ark Lab"', '华为', '诺亚方舟'],
    "Baidu":     ['"Baidu"', '百度'],
    "SenseTime": ['"SenseTime"', '商汤'],
    "Megvii":    ['"Megvii"', '旷视'],
    "Yitu":      ['"Yitu"', '依图'],
    "AI2":          ['"Allen Institute for AI"', '"Allen Institute"', '"AI2"', '"Allen AI"'],
    "HuggingFace":  ['"Hugging Face"', '"HuggingFace"'],
    "LAION":        ['"LAION"'],
    "EleutherAI":   ['"Eleuther AI"', '"EleutherAI"'],
    "CMU":       ['"CMU"', '"Carnegie Mellon"', '"Carnegie Mellon University"'],
    "Berkeley":  ['"UC Berkeley"', '"UCB"', '"Berkeley"', '"University of California, Berkeley"'],
    "Tsinghua":  ['"Tsinghua"', '清华', '"Tsinghua University"'],
    "PekingU":   ['"Peking University"', '"PKU"', '北京大学'],
    "Oxford":    ['"Oxford"', '"University of Oxford"'],
    "Cambridge": ['"Cambridge"', '"University of Cambridge"'],
    "ETH":       ['"ETH"', '"ETH Zurich"', '"ETH Zürich"'],
}

# 只看计算机领域（兜底）
ARXIV_CATEGORIES = ["cs."]

