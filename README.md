# DailyPaper Desktop

[Chinese README](README.zh-CN.md) | [Release Guide](RELEASE.md)

DailyPaper Desktop is a desktop-first arXiv paper collector for selected Computer Science categories and target institutions. It focuses on date-based collection, institution-aware filtering, PDF caching, and a Windows desktop workflow.

## Highlights

- Desktop GUI workflow, no browser or local web server required
- Calendar-based arXiv server date selection
- Editable institution list with aliases
- Priority ranking for AI, LLM, vision, and robotics related categories
- PDF caching by date folder with JSON reports
- Lead/corresponding author affiliation filtering from PDF author blocks
- Runtime progress, pause, resume, and cancel support
- Windows `.exe` packaging with PyInstaller

## Project Layout

```text
DailyPaper/
|- desktop_app.py          # Desktop GUI entry
|- app.py                  # Main pipeline
|- fetch_arxiv.py          # arXiv API fetcher
|- prefetch.py             # PDF caching
|- affil_classify.py       # Affiliation matching
|- pdf_affil.py            # PDF author block extraction
|- runtime_control.py      # Pause/cancel control
|- pipeline_report.py      # Structured stage report
|- config.py               # Runtime config
|- tests/                  # Regression tests
`- build_exe.ps1           # PyInstaller build script
```

## Install

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

## Run From Python

```powershell
.\venv\Scripts\python desktop_app.py
```

## Build EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Output executable:

```text
dist/DailyPaperDesktop.exe
```

## Current Pipeline

1. Select an arXiv server date and institution list.
2. Fetch baseline papers within the selected server-day window.
3. Run per-organization fallback search when needed.
4. Rank priority categories.
5. Cache PDFs into `cache_pdfs/YYYY-MM-DD/`.
6. Filter by author affiliation from PDF author blocks.
7. Write reports to `cache_pdfs/_reports/YYYY-MM-DD/`.

## Documentation

- Chinese README: [README.zh-CN.md](README.zh-CN.md)
- Release and packaging guide: [RELEASE.md](RELEASE.md)

## Test

```powershell
.\venv\Scripts\python -m unittest discover -s tests -v
```

## Notes

- Runtime cache, downloaded PDFs, build output, and virtual environments are ignored by Git.
- The desktop app replaces the previous web UI and old `output_org` workflow.
