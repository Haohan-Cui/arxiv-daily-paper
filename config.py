try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:
    ZoneInfo = None

    class ZoneInfoNotFoundError(Exception):
        pass

from datetime import timedelta, timezone


def _get_tz(name: str, fallback_hours: int):
    if ZoneInfo:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            pass
    return timezone(timedelta(hours=fallback_hours))


LOCAL_TZ = _get_tz("America/New_York", -5)

DEBUG = True
DRY_RUN = False
LIMIT_PER_ORG = 0
DOWNLOAD_CONCURRENCY = 4
CONNECT_TIMEOUT_SEC = 30
READ_TIMEOUT_SEC = 120
WINDOW_FIELD = "published"
USE_SHARDED_BASELINE = True

CLASSIFY_FROM_PDF = True
PDF_CACHE_DIR = "cache_pdfs"
CACHE_REPORT_DIR = "cache_pdfs/_reports"
PRUNE_UNMATCHED_CACHED_PDFS = True
USE_HARDLINKS = True
MAX_PDF_PAGES_TO_SCAN = 1
PDF_EXTRACT_ENGINE = "pymupdf"

AFFIL_HINT_KEYWORDS = [
    "University", "Institute", "Laboratory", "Lab", "Dept", "Department",
    "College", "School", "Center", "Centre", "Academy", "Corresponding",
    "author", "Email", "@"
]

ARXIV_API_ENDPOINTS = [
    "https://arxiv.org/api/query",
    "https://export.arxiv.org/api/query",
    "http://export.arxiv.org/api/query",
]

REQUEST_TIMEOUT = (20, 120)
RETRY_TOTAL = 7
RETRY_BACKOFF = 1.5
REQUESTS_UA = "DailyPaper/1.0 (+contact: your_email@example.com)"

PROXIES = None
RESPECT_ENV_PROXIES = True
NO_PROXY_HOSTS = ["arxiv.org", "export.arxiv.org"]

RATE_LIMIT_MIN_INTERVAL_SEC = 1.2
FAILOVER_ON_429 = True

MAX_RESULTS_PER_PAGE = 100
MAX_PAGES = 5
PER_ORG_SEARCH_LIMIT_PAGES = 5
PER_ORG_SEARCH_PAGE_SIZE = 200

FALLBACK_SKIP_IF_BASELINE_AT_LEAST = 300

PRIORITY_CATEGORIES = [
    "cs.CL",
    "cs.LG",
    "cs.AI",
    "cs.CV",
    "cs.RO",
]

INSTITUTIONS_PATTERNS = {
    "Apple": [r"\bApple(?:\s+Research)?\b"],
    "Meta": [r"\bMeta(?:\s+AI)?\b", r"\bFAIR\b", r"\bFacebook\s*AI\s*Research\b"],
    "Google": [r"\bGoogle(?:\s*Research)?\b", r"\bGoogle\s*DeepMind\b", r"\bDeepMind\b"],
    "NVIDIA": [r"\bNVIDIA\b", r"\bNVidia\b"],
    "Microsoft": [r"\bMicrosoft\b", r"\bMicrosoft\s*Research\b", r"\bMSR\b", r"\bMSRA\b"],
    "OpenAI": [r"\bOpenAI\b"],
    "Anthropic": [r"\bAnthropic\b"],
    "IBM": [r"\bIBM\b", r"\bIBM\s*Research\b"],
    "Amazon": [r"\bAmazon\b", r"\bAWS\b", r"\bAmazon\s*Science\b", r"\bAWS\s*AI\b"],
    "AI2": [r"\bAllen\s*Institute\s*for\s*AI\b", r"\bAI2\b", r"\bAllen\s*AI\b"],
    "Adobe": [r"\bAdobe\b", r"\bAdobe\s*Research\b"],
    "BostonDynamics": [r"\bBoston\s*Dynamics\b"],
    "TRI": [r"\bToyota\s*Research\s*Institute\b", r"\bTRI\b"],
    "SRI": [r"\bSRI\s*International\b", r"\bSRI\b"],

    "Tencent": [r"\bTencent\b", r"腾讯"],
    "ByteDance": [r"\bByteDance\b", r"字节跳动"],
    "Alibaba": [r"\bAlibaba\b", r"\bAliyun\b", r"阿里巴巴", r"通义"],
    "AntGroup": [r"\bAnt\s*Group\b", r"\bAnt\s*Research\b", r"蚂蚁", r"蚂蚁集团"],
    "Huawei": [r"\bHuawei\b", r"\bNoah'?s\s*Ark\s*Lab\b", r"华为", r"诺亚方舟"],
    "Baidu": [r"\bBaidu\b", r"百度", r"文心"],
    "SenseTime": [r"\bSenseTime\b", r"商汤"],
    "DeepSeek": [r"\bDeepSeek\b", r"深度求索"],
    "ZhipuAI": [r"\bZhipu\s*AI\b", r"\bZhipu\b", r"智谱"],
    "MoonshotAI": [r"\bMoonshot\s*AI\b", r"\bKimi\b", r"月之暗面"],
    "MiniMax": [r"\bMiniMax\b", r"稀宇科技"],
    "StepFun": [r"\bStepFun\b", r"\bStep\s*Fun\b", r"阶跃星辰"],
    "ZeroOneAI": [r"\b01\.AI\b", r"\bZero\s*One\s*AI\b", r"零一万物"],
    "BAAI": [r"\bBAAI\b", r"\bBeijing\s*Academy\s*of\s*Artificial\s*Intelligence\b", r"智源"],
    "ShanghaiAILab": [r"\bShanghai\s*AI\s*Lab(?:oratory)?\b", r"上海人工智能实验室"],
    "PJLab": [r"\bPeng\s*Cheng\s*Lab(?:oratory)?\b", r"\bPJLab\b", r"鹏城实验室"],
    "CAS": [r"\bChinese\s*Academy\s*of\s*Sciences\b", r"\bCAS\b", r"中国科学院", r"中科院"],

    "MIT": [r"\bMIT\b", r"\bMassachusetts\s*Institute\s*of\s*Technology\b", r"\bCSAIL\b"],
    "Stanford": [r"\bStanford\b", r"\bStanford\s*University\b"],
    "CMU": [r"\bCMU\b", r"\bCarnegie\s*Mellon\b"],
    "Berkeley": [r"\bUC\s*Berkeley\b", r"\bUCB\b", r"\bBerkeley\b", r"\bUniversity\s*of\s*California,\s*Berkeley\b"],
    "UIUC": [r"\bUIUC\b", r"\bUniversity\s*of\s*Illinois\s*Urbana(?:-| )Champaign\b", r"\bUniversity\s*of\s*Illinois\s*at\s*Urbana(?:-| )Champaign\b"],
    "GeorgiaTech": [r"\bGeorgia\s*Tech\b", r"\bGeorgia\s*Institute\s*of\s*Technology\b"],
    "UTAustin": [r"\bUT\s*Austin\b", r"\bUniversity\s*of\s*Texas\s*at\s*Austin\b"],
    "UMich": [r"\bUniversity\s*of\s*Michigan\b", r"\bUMich\b", r"\bMichigan\b"],
    "UW": [r"\bUniversity\s*of\s*Washington\b", r"\bUW\b"],
    "UCSD": [r"\bUC\s*San\s*Diego\b", r"\bUniversity\s*of\s*California,\s*San\s*Diego\b", r"\bUCSD\b"],
    "Cornell": [r"\bCornell\b", r"\bCornell\s*University\b"],
    "USC": [r"\bUSC\b", r"\bUniversity\s*of\s*Southern\s*California\b"],
    "Princeton": [r"\bPrinceton\b", r"\bPrinceton\s*University\b"],
    "Oxford": [r"\bOxford\b", r"\bUniversity\s*of\s*Oxford\b"],
    "Cambridge": [r"\bCambridge\b", r"\bUniversity\s*of\s*Cambridge\b"],
    "ETH": [r"\bETH\b", r"\bETH\s*Zurich\b", r"\bETH\s*Z(?:u|u\u0308)rich\b"],
    "Tsinghua": [r"\bTsinghua\b", r"清华", r"\bTsinghua\s*University\b"],
    "PekingU": [r"\bPeking\s*University\b", r"\bPKU\b", r"北京大学"],
    "NUS": [r"\bNUS\b", r"\bNational\s*University\s*of\s*Singapore\b", r"新加坡国立大学"],
    "NTU": [r"\bNTU\b", r"\bNanyang\s*Technological\s*University\b", r"南洋理工大学"],
    "HKU": [r"\bHKU\b", r"\bThe\s*University\s*of\s*Hong\s*Kong\b", r"香港大学"],
    "CUHK": [r"\bCUHK\b", r"\bThe\s*Chinese\s*University\s*of\s*Hong\s*Kong\b", r"香港中文大学"],
    "HKUST": [r"\bHKUST\b", r"\bHong\s*Kong\s*University\s*of\s*Science\s*and\s*Technology\b", r"香港科技大学"],
    "Fudan": [r"\bFudan\b", r"\bFDU\b", r"复旦大学"],
    "SJTU": [r"\bSJTU\b", r"\bShanghai\s*Jiao\s*Tong\s*University\b", r"上海交通大学"],
    "ZhejiangU": [r"\bZJU\b", r"\bZhejiang\s*University\b", r"浙江大学", r"浙大"],
    "NanjingU": [r"\bNJU\b", r"\bNanjing\s*University\b", r"南京大学"],
    "USTC": [r"\bUSTC\b", r"\bUniversity\s*of\s*Science\s*and\s*Technology\s*of\s*China\b", r"中国科学技术大学", r"中科大"],
    "BIT": [r"\bBIT\b", r"\bBeijing\s*Institute\s*of\s*Technology\b", r"北京理工大学", r"北理工"],
    "Beihang": [r"\bBeihang\b", r"\bBeihang\s*University\b", r"北京航空航天大学", r"北航"],
    "SYSU": [r"\bSYSU\b", r"\bSun\s*Yat-sen\s*University\b", r"中山大学"],
    "HIT": [r"\bHIT\b", r"\bHarbin\s*Institute\s*of\s*Technology\b", r"哈尔滨工业大学", r"哈工大"],
}

ORG_SEARCH_TERMS = {
    "Apple": ['"Apple"', '"Apple Research"'],
    "Meta": ['"Meta"', '"Meta AI"', '"FAIR"', '"Facebook AI Research"'],
    "Google": ['"Google"', '"Google Research"', '"Google DeepMind"', '"DeepMind"'],
    "NVIDIA": ['"NVIDIA"'],
    "Microsoft": ['"Microsoft"', '"Microsoft Research"', '"MSR"', '"MSRA"'],
    "OpenAI": ['"OpenAI"'],
    "Anthropic": ['"Anthropic"'],
    "IBM": ['"IBM"', '"IBM Research"'],
    "Amazon": ['"Amazon"', '"AWS"', '"Amazon Science"', '"AWS AI"'],
    "AI2": ['"Allen Institute for AI"', '"AI2"', '"Allen AI"'],
    "Adobe": ['"Adobe"', '"Adobe Research"'],
    "BostonDynamics": ['"Boston Dynamics"'],
    "TRI": ['"Toyota Research Institute"', '"TRI"'],
    "SRI": ['"SRI International"', '"SRI"'],

    "Tencent": ['"Tencent"', '腾讯'],
    "ByteDance": ['"ByteDance"', '字节跳动'],
    "Alibaba": ['"Alibaba"', '"Aliyun"', '阿里巴巴', '通义'],
    "AntGroup": ['"Ant Group"', '"Ant Research"', '蚂蚁', '蚂蚁集团'],
    "Huawei": ['"Huawei"', '"Noah\'s Ark Lab"', '华为', '诺亚方舟'],
    "Baidu": ['"Baidu"', '百度', '文心'],
    "SenseTime": ['"SenseTime"', '商汤'],
    "DeepSeek": ['"DeepSeek"', '深度求索'],
    "ZhipuAI": ['"Zhipu AI"', '"Zhipu"', '智谱'],
    "MoonshotAI": ['"Moonshot AI"', '"Kimi"', '月之暗面'],
    "MiniMax": ['"MiniMax"', '稀宇科技'],
    "StepFun": ['"StepFun"', '"Step Fun"', '阶跃星辰'],
    "ZeroOneAI": ['"01.AI"', '"Zero One AI"', '零一万物'],
    "BAAI": ['"BAAI"', '"Beijing Academy of Artificial Intelligence"', '智源'],
    "ShanghaiAILab": ['"Shanghai AI Lab"', '"Shanghai AI Laboratory"', '上海人工智能实验室'],
    "PJLab": ['"Peng Cheng Lab"', '"PJLab"', '鹏城实验室'],
    "CAS": ['"Chinese Academy of Sciences"', '"CAS"', '中国科学院', '中科院'],

    "MIT": ['"MIT"', '"Massachusetts Institute of Technology"', '"CSAIL"'],
    "Stanford": ['"Stanford"', '"Stanford University"'],
    "CMU": ['"CMU"', '"Carnegie Mellon"'],
    "Berkeley": ['"UC Berkeley"', '"UCB"', '"Berkeley"', '"University of California, Berkeley"'],
    "UIUC": ['"UIUC"', '"University of Illinois Urbana-Champaign"', '"University of Illinois at Urbana-Champaign"'],
    "GeorgiaTech": ['"Georgia Tech"', '"Georgia Institute of Technology"'],
    "UTAustin": ['"UT Austin"', '"University of Texas at Austin"'],
    "UMich": ['"University of Michigan"', '"UMich"', '"Michigan"'],
    "UW": ['"University of Washington"', '"UW"'],
    "UCSD": ['"UC San Diego"', '"University of California, San Diego"', '"UCSD"'],
    "Cornell": ['"Cornell"', '"Cornell University"'],
    "USC": ['"USC"', '"University of Southern California"'],
    "Princeton": ['"Princeton"', '"Princeton University"'],
    "Oxford": ['"Oxford"', '"University of Oxford"'],
    "Cambridge": ['"Cambridge"', '"University of Cambridge"'],
    "ETH": ['"ETH"', '"ETH Zurich"'],
    "Tsinghua": ['"Tsinghua"', '清华', '"Tsinghua University"'],
    "PekingU": ['"Peking University"', '"PKU"', '北京大学'],
    "NUS": ['"NUS"', '"National University of Singapore"', '新加坡国立大学'],
    "NTU": ['"NTU"', '"Nanyang Technological University"', '南洋理工大学'],
    "HKU": ['"HKU"', '"The University of Hong Kong"', '香港大学'],
    "CUHK": ['"CUHK"', '"The Chinese University of Hong Kong"', '香港中文大学'],
    "HKUST": ['"HKUST"', '"Hong Kong University of Science and Technology"', '香港科技大学'],
    "Fudan": ['"Fudan"', '"FDU"', '复旦大学'],
    "SJTU": ['"SJTU"', '"Shanghai Jiao Tong University"', '上海交通大学'],
    "ZhejiangU": ['"ZJU"', '"Zhejiang University"', '浙江大学', '浙大'],
    "NanjingU": ['"NJU"', '"Nanjing University"', '南京大学'],
    "USTC": ['"USTC"', '"University of Science and Technology of China"', '中国科学技术大学', '中科大'],
    "BIT": ['"BIT"', '"Beijing Institute of Technology"', '北京理工大学', '北理工'],
    "Beihang": ['"Beihang"', '"Beihang University"', '北京航空航天大学', '北航'],
    "SYSU": ['"SYSU"', '"Sun Yat-sen University"', '中山大学'],
    "HIT": ['"HIT"', '"Harbin Institute of Technology"', '哈尔滨工业大学', '哈工大'],
}

ARXIV_PRIMARY_CATEGORY_PREFIXES = ["cs."]
ARXIV_EXCLUDED_CATEGORIES = [
    "cs.GT",
    "cs.IT",
    "cs.CY",
    "cs.SI",
    "cs.DM",
    "cs.MS",
]
