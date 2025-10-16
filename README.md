# 🎓 ArXiv Daily Institution Paper Collector

> Automatically collect the latest Computer Science papers from arXiv, filter by date, classify by research institutions (Google, OpenAI, MIT, etc.), and download full PDFs into folders by **date → organization**.

---

## 🔍 Key Features

✅ Fetches **latest arXiv CS papers** (auto pagination)  
✅ Filters by **Beijing local date** (Published / Updated mode selectable)  
✅ Classifies papers by **institutions / universities / labs**  
✅ Downloads **full original PDFs** (no merge required)  
✅ Folder structure:

```

output_org_pdfs/
└── YYYY-MM-DD/
├── Google/
├── OpenAI/
├── MIT/
└── ...

```

✅ Supports **fallback per-organization search** to ensure maximum coverage  
✅ Easily expandable to new organizations (Microsoft, Tsinghua, Berkeley, etc.)

---

## 🗂 Project Structure

```

arxiv_daily_org_pdfs/
├─ app.py                # Main entry – fetch, filter, classify, download
├─ config.py             # Settings: timezone, org regex, paging, window mode
├─ fetch_arxiv.py        # arXiv API caller with retry & fallback endpoints
├─ filters.py            # Time-window filtering (published/updated)
├─ classify.py           # Regex-based institution grouping
├─ downloader.py         # Concurrent PDF downloader (with ID fix)
├─ utils.py              # Time helpers, folder path utils
├─ requirements.txt      # Python dependencies
└─ README.md             # Documentation

````

---

## ⚙️ Installation

```bash
git clone https://github.com/yourname/arxiv-daily-institutions.git
cd arxiv-daily-institutions
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
````

---

## 🕒 Configuration (`config.py`)

### 1️⃣ Control how many papers to fetch (pagination)

```python
MAX_RESULTS_PER_PAGE = 200    # per API page
MAX_PAGES = 2                 # 2 pages = ~400 recent papers
```

### 2️⃣ Time Window Mode (IMPORTANT)

```python
WINDOW_FIELD = "updated"   # "updated" | "published" | "both"
```

| Mode        | Meaning                                                  |
| ----------- | -------------------------------------------------------- |
| `updated`   | Catch papers with **any update yesterday (v2, v3)**      |
| `published` | Only papers **first submitted yesterday**                |
| `both`      | Very strict: papers both *published & updated* yesterday |

### 3️⃣ Add / Expand Institutions

```python
INSTITUTIONS_PATTERNS = {
    "Google":  [...],
    "MIT":     [...],
    "OpenAI":  [...],
}
```

---

## 🚀 Run the Collector

```bash
python app.py
```

---

## 🧪 DRY-RUN Mode (Only simulate, don't download)

In `config.py`:

```python
DRY_RUN = True
LIMIT_PER_ORG = 2   # Only show 2 papers per org (for testing)
```

---

## 📁 Output Example

```
output_org_pdfs/
└── 2025-10-14/
    ├── Google/
    │   ├── 2503.12345v2.pdf
    ├── OpenAI/
    │   ├── 2504.09876v1.pdf
    ├── MIT/
    │   ├── 2504.19176v2.pdf
```

---

## 🛡️ Network Resilience

* Custom **User-Agent**
* Automatic retry with **fallback URLs**
* Supports **NO_PROXY** for direct arXiv access

---

## 🔧 Automation (Optional)

### Cron (Linux server)

```
0 8 * * *  /usr/bin/python3 /path/to/app.py
```

### GitHub Actions (UTC 00:00 → Beijing 08:00)

```yaml
schedule:
  - cron: "0 0 * * *"
```

---

## 🧩 Extending Institutions

Track any combination of:

| Category      | Examples                  |
| ------------- | ------------------------- |
| Big Tech      | OpenAI, Anthropic, Amazon |
| China AI Labs | Huawei, Baidu, SenseTime  |
| Universities  | MIT, Stanford, Tsinghua   |
| Research Orgs | AI2, LAION, EleutherAI    |

Just edit:

```
INSTITUTIONS_PATTERNS
ORG_SEARCH_TERMS
```

---

## 🐛 Troubleshooting

| Issue           | Fix                                     |
| --------------- | --------------------------------------- |
| 404 on PDF      | Canonical `.pdf` fallback enabled       |
| SSL timeout     | Uses HTTP fallback + retry              |
| No papers found | Increase MAX_PAGES & check WINDOW_FIELD |

---

## 🤝 Contributions

Feel free to submit:

* Better institution regex
* New organization tracking
* Feature requests (like mailing, Web UI)

---

## 📜 License

MIT License – You are free to modify and automate.

---

### 🌟 Enjoy research without manual filtering!

If this project saves you time, consider starring ⭐ or sharing it!

```
