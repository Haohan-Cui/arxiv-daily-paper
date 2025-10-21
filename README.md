# 🎓 ArXiv Daily Institutional Paper Collector

> Automated daily downloader for arXiv **Computer Science** papers.  
> 每日自动下载并分类 arXiv **计算机科学** 论文。

---

<details>
<summary>🌐 English Version (click to expand)</summary>

## ✨ What’s New (Optimized)

- **Sharded Baseline**: Baseline crawl now supports **per-subcategory shards** (e.g., `cs.CV`, `cs.CL`, `cs.LG`…), avoiding `cat:cs.*` pagination limits on some mirrors.  
- **Endpoint Priority**: Prefer `https://arxiv.org/api/query` to fix the “10 results only” issue.  
- **Rich Diagnostics**: Page-level logs, per-org fallback stats, and time window coverage check.  
- **PDF-Based Classification**: Detect affiliations from PDF author blocks.  
- **Configurable Depth**: Adjustable per-org search and baseline crawl size.

---

## 📌 Core Features

| Feature | Description |
|----------|--------------|
| 🕒 Daily Schedule | Filters papers by **yesterday (Beijing time)** |
| 🏛 Real Affiliation Detection | Extracts institution info from **PDF** (not title/abstract) |
| 🎯 Organization Classification | Supports **Big Tech, Universities, Chinese AI Labs, Institutes** |
| 📂 Auto Folder Structure | `output_org_pdfs/YYYY-MM-DD/<ORG>/paper.pdf` |
| 🧠 Smart Fallback | Org-specific API search when baseline misses |
| 💾 Caching | Unified `cache_pdfs/` to prevent re-downloads |
| 🧩 Sharded Crawl | Multiple CS subcategories for better coverage |

---

## 🗂 Structure

```

DailyPaper/
├── app.py
├── config.py
├── fetch_arxiv.py          # sharded baseline + robust session
├── filters.py
├── classify.py
├── pdf_affil.py
├── prefetch.py
├── affil_classify.py
├── utils.py
└── output_org_pdfs/
└── YYYY-MM-DD/
├── Google/
├── OpenAI/
└── ...

````

---

## ⚙️ Installation

```bash
git clone https://github.com/<yourname>/arxiv-daily-paper.git
cd arxiv-daily-paper
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
pip install -r requirements.txt
````

---

## 🔍 Configuration (`config.py`)

### Time Window

```python
WINDOW_FIELD = "updated"    # "updated" | "published" | "both"
```

| Mode        | Meaning                          |
| ----------- | -------------------------------- |
| `updated`   | Papers updated yesterday         |
| `published` | Papers first submitted yesterday |
| `both`      | Must satisfy both conditions     |

### PDF Affiliation Extraction

```python
CLASSIFY_FROM_PDF = True
MAX_PDF_PAGES_TO_SCAN = 2
```

### Baseline Crawl

```python
USE_SHARDED_BASELINE = True
MAX_RESULTS_PER_PAGE = 200
MAX_PAGES = 10
```

### Per-Org Fallback

```python
PER_ORG_SEARCH_LIMIT_PAGES = 5
PER_ORG_SEARCH_PAGE_SIZE   = 200
```

---

## 🚀 Run

```bash
python app.py
```

### Dry Run (No File Output)

```python
# config.py
DRY_RUN = True
LIMIT_PER_ORG = 2
```

---

## 🧪 Example Output

```
output_org_pdfs/
└── 2025-10-20/
    ├── Google/
    │   └── 2510.13778v1.pdf
    ├── OpenAI/
    │   └── 2510.13724v1.pdf
    └── ETH/
        └── 2510.11448v2.pdf
```

---

## 🧠 Why PDF-Based Classification?

| Title/Abstract-Based     | PDF Author Block-Based       |
| ------------------------ | ---------------------------- |
| ❌ Often inaccurate       | ✅ Reliable                   |
| Misses real affiliations | Captures printed author info |
| Ignores lab names        | Detects institutes clearly   |

---

## ⚙️ GitHub Actions (Optional)

```yaml
schedule:
  - cron: "0 0 * * *"   # Run daily 08:00 BJT
```

---

## 📜 License

MIT License – free to modify, fork, and automate.

🌟 If this tool saves your time, please star the repo!

</details>

---

<details open>
<summary>🇨🇳 中文版本 (点击展开)</summary>

## ✨ 新特性（优化版）

* **分片抓取**：按 `cs.AI`, `cs.CL`, `cs.CV`, `cs.LG` 等子类分页，避免 `cat:cs.*` 分页失效。
* **主站优先**：默认使用 `https://arxiv.org/api/query`，避免 `export.arxiv.org` 限制返回 10 条。
* **调试日志**：提供页级/分片级抓取日志与机构回退统计。
* **PDF 分类**：基于论文 PDF 作者单位区块识别真实机构。
* **可配置深度**：支持调整 baseline 与机构回退的页数与大小。

---

## 📌 核心功能

| 功能         | 说明                                           |
| ---------- | -------------------------------------------- |
| 🕒 每日过滤    | 按北京时间筛选“昨日论文”                                |
| 🏛 实体识别    | 从 PDF 作者栏提取机构信息                              |
| 🎯 自动分类    | 支持科技公司、高校、研究院、AI 实验室                         |
| 📂 自动文件夹结构 | `output_org_pdfs/YYYY-MM-DD/<ORG>/paper.pdf` |
| 🧠 智能补全    | 当 baseline 漏检时按机构关键词直搜补齐                     |
| 💾 缓存机制    | `cache_pdfs/` 避免重复下载                         |
| 🧩 分片爬取    | 遍历多个 CS 子类以确保覆盖率                             |

---

## 🗂 项目结构

```
DailyPaper/
├── app.py
├── config.py
├── fetch_arxiv.py          # 分片+稳健 session
├── filters.py
├── classify.py
├── pdf_affil.py
├── prefetch.py
├── affil_classify.py
├── utils.py
└── output_org_pdfs/
    └── YYYY-MM-DD/
        ├── Google/
        ├── OpenAI/
        └── ...
```

---

## ⚙️ 安装步骤

```bash
git clone https://github.com/<你的用户名>/arxiv-daily-paper.git
cd arxiv-daily-paper
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
pip install -r requirements.txt
```

---

## 🔍 主要配置（config.py）

### 时间窗口

```python
WINDOW_FIELD = "updated"    # "updated" | "published" | "both"
```

| 模式          | 含义             |
| ----------- | -------------- |
| `updated`   | 昨日有更新（v2/v3 等） |
| `published` | 昨日首次提交         |
| `both`      | 同时满足两者         |

### PDF 作者单位识别

```python
CLASSIFY_FROM_PDF = True
MAX_PDF_PAGES_TO_SCAN = 2
```

### 基础抓取

```python
USE_SHARDED_BASELINE = True
MAX_RESULTS_PER_PAGE = 200
MAX_PAGES = 10
```

### 按机构补全搜索

```python
PER_ORG_SEARCH_LIMIT_PAGES = 5
PER_ORG_SEARCH_PAGE_SIZE   = 200
```

---

## 🚀 运行

```bash
python app.py
```

### 测试模式（不写文件）

```python
# config.py
DRY_RUN = True
LIMIT_PER_ORG = 2
```

---

## 🧪 输出示例

```
output_org_pdfs/
└── 2025-10-20/
    ├── Google/
    │   └── 2510.13778v1.pdf
    ├── OpenAI/
    │   └── 2510.13724v1.pdf
    └── ETH/
        └── 2510.11448v2.pdf
```

---

## 🧠 为什么要从 PDF 识别机构？

| 标题/摘要分类  | PDF 作者栏分类      |
| -------- | -------------- |
| ❌ 错误率高   | ✅ 精确           |
| 难检测实验室名称 | 直接包含真实单位/实验室名称 |

---

## 🔧 自动化运行（可选）

```yaml
schedule:
  - cron: "0 0 * * *"   # 每天 08:00（北京时间）
```

---

## 📜 许可证

MIT License – 可自由修改、复用与自动化。

🌟 如果这个项目对你有帮助，请为仓库点个 ⭐！

</details> ```



