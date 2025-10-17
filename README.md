# 🎓 ArXiv Daily Institutional Paper Collector

> Automated daily downloader for arXiv **Computer Science** papers.  
> Filters by **Beijing time**, extracts **real affiliations from PDF (author/institution block)**, and organizes papers by **top research organizations & universities** (Google, MIT, OpenAI, Tsinghua, etc.).

---

## 📌 Core Features

| Feature | Description |
|---------|-------------|
| 🕒 Daily Schedule | Filters papers by **yesterday (Beijing time)** |
| 🏛 Real Affiliation Detection | Extracts **institution info from PDF** (not from title/abstract!) |
| 🎯 Organization Classification | Supports **Big Tech, Universities, Chinese AI Labs, Research Institutes** |
| 📂 Auto Folder Structure | `output_org_pdfs/YYYY-MM-DD/<ORG>/paper.pdf` |
| 🧠 Smart Fallback | Uses institution-specific API search when baseline misses papers |
| 💾 Caching | Avoids redownloading PDFs (uses `cache_pdfs/`) |

---

## 🗂 Folder Structure

```

DailyPaper/
├── app.py
├── config.py
├── fetch_arxiv.py
├── filters.py
├── classify.py
├── pdf_affil.py            # (NEW) PDF author/institution extraction
├── prefetch.py             # (NEW) Unified PDF caching
├── affil_classify.py       # (NEW) Final classification via PDF block
├── utils.py
├── requirements.txt
└── output_org_pdfs/
└── 2025-10-16/
├── Google/
├── OpenAI/
├── MIT/
└── ...

````

---

## ⚙️ Installation

```bash
git clone https://github.com/<yourname>/arxiv-daily-paper.git
cd arxiv-daily-paper

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
````

---

## 🔍 Key Configuration (`config.py`)

### Time Window Mode

```python
WINDOW_FIELD = "updated"    # "updated" | "published" | "both"
```

| Mode        | Meaning                                            |
| ----------- | -------------------------------------------------- |
| `updated`   | Papers updated yesterday (v2, v3 etc.)             |
| `published` | Only papers first submitted yesterday              |
| `both`      | Strict: must be both published & updated yesterday |

---

### Institution Detection Source

```python
CLASSIFY_FROM_PDF = True    # ← Use PDF author/affiliation data
```

### Pagination (To Explore Deep Backlog)

```python
MAX_RESULTS_PER_PAGE = 200
MAX_PAGES = 10
```

### Per-Organization Fallback Search (API search)

```python
PER_ORG_SEARCH_LIMIT_PAGES = 5
PER_ORG_SEARCH_PAGE_SIZE   = 200
```

---

## 🚀 Run

```bash
python app.py
```

### Dry-Run for Testing

```python
# config.py
DRY_RUN = True
LIMIT_PER_ORG = 2
```

---

## 🗂 Output Example

```
output_org_pdfs/
└── 2025-10-16/
    ├── Google/
    │   └── 2510.13778v1.pdf
    ├── OpenAI/
    │   └── 2510.13724v1.pdf
    └── ETH/
        └── 2510.11448v2.pdf
```

---

## 🧠 Why PDF Affiliation Classification?

| Title/Abstract-Based           | PDF Author Block-Based                      |
| ------------------------------ | ------------------------------------------- |
| ❌ Many mistakes                | ✅ Accurate                                  |
| Authors rarely mention company | Real affiliation printed under authors      |
| Hard to detect labs            | Institution logo / lab name clearly present |

---

## 🔧 Automation (Optional)

### GitHub Actions (Daily @ 08:00 Beijing)

```yaml
schedule:
  - cron: "0 0 * * *"   # 08:00 BJT
```

---

## 🤝 Future Ideas

* 📬 Email / Telegram / Slack Digest
* 🎨 Web Dashboard (Flask / FastAPI)
* 🧪 Research Topic Classification (LLM)

---

## 📜 License

MIT License. Free to modify, fork, automate.

---

🌟 If this tool saves your research time, star the repo & share it!
