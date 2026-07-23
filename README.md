# DailyPaper Desktop

[中文说明](README.zh-CN.md) | [Release Guide](RELEASE.md)

DailyPaper Desktop is a Windows desktop and headless CLI tool for collecting Computer Science papers from arXiv, caching PDFs, filtering papers by target institutions, and writing structured local reports. It processes papers by arXiv server date, prioritizes AI, LLM, vision, and robotics categories, extracts affiliation clues from PDF author blocks, and produces JSON files that can be reviewed manually or consumed by another local application.

Repository:

```text
https://github.com/Haohan-Cui/arxiv-daily-paper
```

## Use Cases

- Collect arXiv Computer Science papers for a specific server-side date.
- Track papers from selected universities, labs, companies, or research institutes.
- Run the workflow from a desktop GUI with editable institution aliases.
- Run a one-shot command from another local control center or scheduled task.
- Cache PDFs and structured reports for later reading, filtering, or downstream processing.

## Features

- Desktop GUI based on Tkinter and tkcalendar.
- Calendar-based arXiv server date selection.
- Complete calendar-day CS baseline before PDF caching and affiliation filtering.
- Priority ranking for `cs.CL`, `cs.LG`, `cs.AI`, `cs.CV`, and `cs.RO`.
- Date-based PDF cache under `cache_pdfs/YYYY-MM-DD/`.
- PDF author block extraction from common top and bottom page layouts.
- Target institution filtering by configurable aliases and regex patterns.
- Editable institution list in the GUI, persisted to the local user profile.
- Real-time progress, pause, resume, and cancel controls.
- Baseline checkpointing and complete baseline cache.
- Structured `pipeline_report.json` and `cache_manifest.json` outputs.
- Headless `--run-once` mode for local integration.
- Single-file Windows executable packaging with PyInstaller.

## Project Layout

```text
DailyPaper/
|- desktop_app.py          # Desktop GUI and headless CLI entry point
|- app.py                  # Main pipeline orchestration
|- fetch_arxiv.py          # arXiv API fetcher, rate limiting, proxy handling, PDF URL parsing
|- prefetch.py             # PDF download, cache reuse, file-size validation
|- affil_classify.py       # Institution matching for extracted affiliation text
|- pdf_affil.py            # PDF author block and affiliation text extraction
|- filters.py              # Date window and Computer Science category filters
|- config.py               # Runtime defaults, categories, institutions, proxy and cache paths
|- runtime_control.py      # Pause, resume, and cancel controller
|- pipeline_report.py      # Structured stage report models
|- classify.py             # Legacy metadata-based matching helper
|- live_smoke_test.py      # Live network smoke test
|- tests/                  # Unit tests
|- build_exe.ps1           # Windows PyInstaller build script
|- README.md               # English documentation
|- README.zh-CN.md         # Chinese documentation
`- RELEASE.md              # Release and packaging notes
```

## Requirements

- Windows 10/11.
- Python 3.11 or a compatible Python version.
- Network access to `arxiv.org` and `export.arxiv.org`.
- PyMuPDF for PDF affiliation extraction.
- PyInstaller for executable packaging.

Install dependencies from [requirements.txt](requirements.txt).

## Install

Run in PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

If PowerShell blocks activation scripts, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Run The Desktop App

```powershell
.\venv\Scripts\python desktop_app.py
```

Typical GUI workflow:

1. Select the target arXiv server date.
2. Edit the institution list. Each line uses `Institution: Alias1, Alias2`.
3. Save the institution list if you want it loaded on the next launch.
4. Start the collection pipeline.
5. Watch progress, warnings, and stage status in the right panel.
6. Open the report directory or PDF cache directory after the run finishes.

## Headless One-Shot Mode

The same entry point supports a headless mode for local orchestration tools.

Python example:

```powershell
.\venv\Scripts\python desktop_app.py --run-once --target-day 2026-04-01 --output-json .\out\result.json --output-summary .\out\summary.txt
```

Packaged executable example:

```powershell
.\dist\DailyPaperDesktopLauncher.exe --run-once --target-day 2026-04-01 --output-json .\out\result.json --output-summary .\out\summary.txt
```

Absolute path example:

```powershell
C:\Users\BW\Desktop\Haohan_Cui\DailyPaper\dist\DailyPaperDesktopLauncher.exe --run-once --target-day 2026-04-01 --output-json C:\Work\ControlCenter\temp\dailypaper_result.json --output-summary C:\Work\ControlCenter\temp\dailypaper_summary.txt --quiet
```

Arguments:

- `--run-once`: run one pipeline job without opening the GUI.
- `--target-day YYYY-MM-DD`: process one arXiv server date.
- `--institutions-file path.txt`: load institution definitions from a UTF-8 file.
- `--institutions-text "Org: Alias1, Alias2"`: pass institution definitions inline.
- `--output-json path.json`: write machine-readable result JSON.
- `--output-summary path.txt`: write human-readable summary text.
- `--quiet`: suppress stdout summary output.

Without `--run-once`, the executable starts the desktop GUI.

## Institution Configuration

Institution definition format:

```text
OpenAI: OpenAI
Microsoft: Microsoft, Microsoft Research, MSR
Tsinghua: Tsinghua, Tsinghua University, 清华
RenminU: Renmin University of China, RUC, 中国人民大学, 人大
```

Rules:

- The left side of `:` is the institution label shown in reports.
- The right side contains aliases, abbreviations, and multilingual names.
- One institution per line.
- Empty lines are ignored.
- GUI-saved institutions are loaded automatically on the next launch.
- Default institution regex patterns are defined in `config.py`.

## Outputs

Default runtime outputs:

```text
cache_pdfs/
|- YYYY-MM-DD/                         # PDF cache for the report date
|  `- <arxiv_id>.pdf
`- _reports/
   `- YYYY-MM-DD/
      |- pipeline_report.json          # Stage status, metrics, warnings, and errors
      |- cache_manifest.json           # Filtered papers, PDF paths, institution matches
      |- baseline_fetch_checkpoint.json
      `- baseline_entries_cache.json
```

Common `result.json` fields:

- `status`: `ok`, `error`, or `cancelled`.
- `report_date`: processed arXiv server date.
- `candidate_count`: baseline candidate count.
- `ordered_candidate_count`: sorted candidate count.
- `filtered_candidate_count`: final institution-filtered paper count.
- `cached_count`: available PDF count.
- `json_outputs`: report file paths.
- `report`: structured stage report.
- `filtered_candidates`: final paper entries.

Each paper in `cache_manifest.json` can include:

- `arxiv_id`
- `title`
- `authors`
- `summary`
- `published`
- `updated`
- `primary_category`
- `categories`
- `cached_pdf`
- `matched_orgs`

## Pipeline

1. Resolve the arXiv server-day time window.
2. Query the arXiv API for papers in the target window.
3. Filter out non-target categories and out-of-window entries.
4. Use the complete CS baseline as the candidate set.
5. Rank candidates by priority category and publish time.
6. Download PDFs or reuse existing cached PDFs.
7. Extract author and affiliation text from the first PDF page.
8. Match extracted text against institution regex patterns.
9. Optionally prune PDFs that did not pass the affiliation filter.
10. Write JSON reports and a human-readable summary.

## Network, Proxy, And Rate Limiting

Network behavior is configured in [config.py](config.py):

- `ARXIV_API_ENDPOINTS`: arXiv API endpoints.
- `REQUEST_TIMEOUT`: request timeout.
- `REQUEST_CONCURRENCY_LIMIT`: request concurrency.
- `SESSION_RATE_LIMIT_PER_MIN`: per-session rate limit.
- `RATE_LIMIT_MIN_INTERVAL_SEC`: minimum gap between requests.
- `ARXIV_429_COOLDOWN_SEC`: cooldown after HTTP 429.
- `PROXIES`: explicit proxy settings.
- `ARXIV_API_USE_PROXY`: force API requests through the configured proxy.
- `RESPECT_ENV_PROXIES`: read proxy settings from environment variables.
- `NO_PROXY_HOSTS`: hosts that should bypass proxy settings.

When arXiv returns HTTP 429, the app persists request state and enters a cooldown window to avoid repeated rate-limit hits.

## Build Windows EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Current output:

```text
dist\DailyPaperDesktopLauncher.exe
```

Build artifacts, virtual environments, PDF caches, and reports are ignored by Git.

## Test

Run all unit tests:

```powershell
.\venv\Scripts\python -m unittest discover -s tests -v
```

Run one test module:

```powershell
.\venv\Scripts\python -m unittest tests.test_app_pipeline -v
```

Live network smoke test:

```powershell
.\venv\Scripts\python live_smoke_test.py
```

## Troubleshooting

### Why does the app use arXiv server dates?

arXiv submission and update windows do not always align with the local timezone. Server-date processing makes daily runs more reproducible.

### Why was a paper filtered out?

Common reasons:

- PDF download failed or the file was smaller than the configured minimum.
- The first PDF page did not expose a recognizable author or affiliation block.
- No target institution matched the lead, corresponding, or main author area.
- The paper category was outside the configured Computer Science target categories.

### Why are some cached PDFs deleted?

When `PRUNE_UNMATCHED_CACHED_PDFS = True`, PDFs that do not pass the affiliation filter are removed at the end of the run. Change this setting in `config.py` if you want to keep all downloaded PDFs.

### How do I add a new institution?

Use the GUI institution editor for day-to-day changes. For project defaults, update `INSTITUTIONS_PATTERNS` and `ORG_SEARCH_TERMS` in `config.py`.

### How should another app call DailyPaper?

Run the executable with `--run-once`, pass the target date and output paths, wait for the process to finish, then read `result.json`.

## Version Notes

This version has moved from the older web UI and `output_org` workflow to a desktop GUI, headless CLI mode, PDF author-block affiliation filtering, and structured JSON reports.
