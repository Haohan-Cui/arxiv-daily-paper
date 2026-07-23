# DailyPaper 论文抓取器

[English README](README.md) | [发布说明](RELEASE.md)

DailyPaper Desktop 是一个面向 Windows 桌面使用的 arXiv 计算机论文抓取、PDF 缓存和机构筛选工具。它以 arXiv 服务器日期为单位抓取论文，优先处理 AI、大模型、视觉、机器人等计算机方向，下载论文 PDF，并通过论文首页作者块识别第一作者、通讯作者或主要作者的机构线索，最后输出可被人工筛选或其他本地工具读取的 JSON 报告和摘要文本。

仓库地址：

```text
https://github.com/Haohan-Cui/arxiv-daily-paper
```

## 适用场景

- 每天按固定日期窗口拉取 arXiv 计算机论文。
- 关注指定高校、实验室、公司或研究机构的论文。
- 在桌面 GUI 里调整机构名单、选择日期、查看进度和结果。
- 从其他本地项目或控制台程序中以命令行方式调用一次性抓取任务。
- 将 PDF 与结构化报告沉淀到本地目录，方便后续人工阅读、筛选或二次处理。

## 功能亮点

- 桌面 GUI：基于 Tkinter 和 tkcalendar，不需要浏览器或本地 Web 服务。
- 日期选择：通过日历选择 arXiv 服务器日期，便于稳定复现某一天的抓取结果。
- 完整 CS baseline：先抓取目标日期窗口内的计算机论文，再进入缓存和筛选流程。
- 重点类别排序：默认优先展示 `cs.CL`、`cs.LG`、`cs.AI`、`cs.CV`、`cs.RO`。
- PDF 缓存：按日期保存到 `cache_pdfs/YYYY-MM-DD/`，重复运行会复用已缓存文件。
- PDF 作者块机构识别：从 PDF 首页顶部和底部常见作者/通讯信息区域提取机构线索。
- 机构名单可编辑：GUI 内可保存自定义机构和别名，命令行也支持文件或文本传入。
- 运行控制：支持实时进度、暂停、继续和取消。
- 断点与缓存：baseline 抓取有 checkpoint，完整 baseline 会缓存到报告目录。
- 结构化输出：生成 `pipeline_report.json` 和 `cache_manifest.json`。
- Headless 模式：支持 `--run-once`，方便被其他本地系统集成。
- Windows 打包：提供 PyInstaller 打包脚本生成单文件 `.exe`。

## 项目结构

```text
DailyPaper/
|- desktop_app.py          # 桌面 GUI 和 headless CLI 入口
|- app.py                  # 主流程编排
|- fetch_arxiv.py          # arXiv API 请求、限速、代理和 PDF URL 解析
|- prefetch.py             # PDF 下载、缓存、文件大小校验
|- affil_classify.py       # 基于机构正则的论文筛选
|- pdf_affil.py            # PDF 作者块和机构文本提取
|- filters.py              # 日期窗口、CS 类别过滤
|- config.py               # 默认配置、类别、机构、代理、缓存路径
|- runtime_control.py      # 暂停、继续、取消控制
|- pipeline_report.py      # 阶段报告数据结构
|- classify.py             # 旧的元数据机构匹配辅助逻辑
|- live_smoke_test.py      # 网络链路冒烟测试
|- tests/                  # 单元测试
|- build_exe.ps1           # Windows PyInstaller 打包脚本
|- README.md               # 英文说明
|- README.zh-CN.md         # 中文说明
`- RELEASE.md              # 发布与打包说明
```

## 环境要求

- Windows 10/11。
- Python 3.11 或兼容版本。
- 网络可访问 `arxiv.org` 和 `export.arxiv.org`。
- 如需 PDF 机构识别，需要安装 PyMuPDF。
- 如需打包 exe，需要安装 PyInstaller。

依赖见 [requirements.txt](requirements.txt)。

## 安装

在 PowerShell 中执行：

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

如果系统策略阻止激活脚本，可以先执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 运行桌面版

```powershell
.\venv\Scripts\python desktop_app.py
```

桌面端主要操作流程：

1. 在左侧选择目标 arXiv 服务器日期。
2. 编辑机构列表。格式为 `机构名: 别名1, 别名2`，每行一条。
3. 点击“保存机构”可把当前机构列表保存到本机用户配置目录。
4. 点击“开始抓取”启动 pipeline。
5. 右侧查看实时日志、阶段进度、摘要和论文列表。
6. 运行结束后可以打开报告目录或缓存目录。

## Headless 一次性运行

`desktop_app.py` 支持命令行一次性运行，适合被另一个本地控制中心、定时任务或批处理脚本调用。

基本示例：

```powershell
.\venv\Scripts\python desktop_app.py --run-once --target-day 2026-04-01 --output-json .\out\result.json --output-summary .\out\summary.txt
```

如果使用已打包 exe：

```powershell
.\dist\DailyPaperDesktopLauncher.exe --run-once --target-day 2026-04-01 --output-json .\out\result.json --output-summary .\out\summary.txt
```

绝对路径示例：

```powershell
C:\Users\BW\Desktop\Haohan_Cui\DailyPaper\dist\DailyPaperDesktopLauncher.exe --run-once --target-day 2026-04-01 --output-json C:\Work\ControlCenter\temp\dailypaper_result.json --output-summary C:\Work\ControlCenter\temp\dailypaper_summary.txt --quiet
```

命令行参数：

- `--run-once`：不打开 GUI，只运行一次 pipeline。
- `--target-day YYYY-MM-DD`：指定 arXiv 服务器日期。
- `--institutions-file path.txt`：从 UTF-8 文本文件读取机构定义。
- `--institutions-text "Org: Alias1, Alias2"`：直接传入机构定义文本。
- `--output-json path.json`：写入机器可读的结果 JSON。
- `--output-summary path.txt`：写入人类可读的摘要文本。
- `--quiet`：不向 stdout 打印摘要。

不传 `--run-once` 时，程序会启动桌面 GUI。

## 机构配置

机构定义格式：

```text
OpenAI: OpenAI
Microsoft: Microsoft, Microsoft Research, MSR
Tsinghua: Tsinghua, Tsinghua University, 清华
RenminU: Renmin University of China, RUC, 中国人民大学, 人大
```

规则说明：

- 冒号左侧是机构名称，用于报告中的归类显示。
- 冒号右侧是匹配别名，可以包含英文、中文、缩写。
- 每行一个机构。
- 空行会被忽略。
- GUI 保存的机构列表会在下次启动时自动加载。
- `config.py` 中也提供了一组默认机构和正则匹配规则。

## 输出文件

运行结果默认写入：

```text
cache_pdfs/
|- YYYY-MM-DD/                         # 当天 PDF 缓存
|  `- <arxiv_id>.pdf
`- _reports/
   `- YYYY-MM-DD/
      |- pipeline_report.json          # 阶段状态、计数、警告和错误
      |- cache_manifest.json           # 筛选后论文、PDF 路径、机构匹配结果
      |- baseline_fetch_checkpoint.json
      `- baseline_entries_cache.json
```

`result.json` 的常见字段：

- `status`：`ok`、`error` 或 `cancelled`。
- `report_date`：本次处理的 arXiv 日期。
- `candidate_count`：baseline 候选论文数。
- `ordered_candidate_count`：排序后的候选论文数。
- `filtered_candidate_count`：机构筛选后保留论文数。
- `cached_count`：可用 PDF 缓存数量。
- `json_outputs`：报告文件路径。
- `report`：阶段报告。
- `filtered_candidates`：筛选后的论文条目。

`cache_manifest.json` 中每篇论文会包含：

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

## Pipeline 流程

1. 计算目标日期的 arXiv 服务器时间窗口。
2. 请求 arXiv API，抓取目标窗口内的计算机论文。
3. 过滤非目标 CS 类别和日期窗口外条目。
4. 将完整 baseline 作为候选集。
5. 按重点类别和发布时间排序。
6. 下载或复用 PDF 缓存。
7. 从 PDF 首页提取作者块、通讯信息和机构文本。
8. 按机构正则筛选论文。
9. 可选删除未通过筛选的 PDF 缓存。
10. 写入 JSON 报告和摘要。

## 网络、代理和限速

网络相关配置位于 [config.py](config.py)：

- `ARXIV_API_ENDPOINTS`：arXiv API 地址。
- `REQUEST_TIMEOUT`：请求超时。
- `REQUEST_CONCURRENCY_LIMIT`：请求并发限制。
- `SESSION_RATE_LIMIT_PER_MIN`：会话级限速。
- `RATE_LIMIT_MIN_INTERVAL_SEC`：请求间隔。
- `ARXIV_429_COOLDOWN_SEC`：遇到 HTTP 429 后的冷却时间。
- `PROXIES`：代理配置。
- `ARXIV_API_USE_PROXY`：是否强制 API 使用代理。
- `RESPECT_ENV_PROXIES`：是否读取环境变量代理。
- `NO_PROXY_HOSTS`：直连主机列表。

如果 arXiv 返回 HTTP 429，程序会写入请求状态并进入冷却期，避免短时间内重复触发限流。

## 打包 Windows EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

当前脚本输出：

```text
dist\DailyPaperDesktopLauncher.exe
```

打包产物、虚拟环境、PDF 缓存和报告目录默认被 `.gitignore` 忽略，不会提交到 Git。

## 测试

运行全部单元测试：

```powershell
.\venv\Scripts\python -m unittest discover -s tests -v
```

运行单个测试文件：

```powershell
.\venv\Scripts\python -m unittest tests.test_app_pipeline -v
```

网络链路冒烟测试：

```powershell
.\venv\Scripts\python live_smoke_test.py
```

## 常见问题

### 为什么选择的是 arXiv 服务器日期？

arXiv 的提交、更新时间窗口和本地时区不完全一致。按 arXiv 服务器日期处理，可以让同一天的结果更稳定，也方便之后复现。

### 为什么有些论文没有被保留？

常见原因：

- PDF 下载失败或文件过小。
- PDF 首页没有可识别的作者/机构块。
- 第一作者、通讯作者或主要作者区域没有匹配到目标机构。
- 论文类别不在当前 CS 目标类别范围内。

### 为什么有些 PDF 会被删除？

`PRUNE_UNMATCHED_CACHED_PDFS = True` 时，未通过机构筛选的 PDF 会在流程末尾删除，只保留最终命中的论文 PDF。可在 `config.py` 中调整。

### 如何增加新的机构？

推荐在 GUI 左侧机构列表中新增并保存。也可以修改 `config.py` 中的 `INSTITUTIONS_PATTERNS` 和 `ORG_SEARCH_TERMS`。

### 如何作为外部程序调用？

使用 `--run-once`，传入目标日期、输出 JSON 路径和摘要路径。外部程序等待进程退出后读取 `result.json` 即可。

## 版本说明

当前版本已经从旧网页界面和 `output_org` 分类流程迁移到桌面 GUI、headless CLI、PDF 作者块机构筛选和结构化 JSON 报告流程。
