# DailyPaper 论文抓取器

[English README](README.md) | [发布说明](RELEASE.md)

DailyPaper Desktop 是一个面向 Windows 桌面使用的 arXiv 论文抓取与缓存工具，聚焦于按日期抓取、机构过滤、PDF 缓存，以及桌面端人工筛选工作流。

## 功能亮点

- 桌面图形界面，不需要浏览器或本地 Web 服务
- 通过日历选择 arXiv 服务器日期
- 机构列表可编辑，并支持别名
- 优先处理 AI、大模型、视觉、机器人相关类别
- PDF 按日期分目录缓存，并生成 JSON 报告
- 基于 PDF 作者块识别第一作者、通讯作者、主要作者的机构线索
- 支持实时进度、暂停、继续和取消
- 支持使用 PyInstaller 打包 Windows `.exe`

## 项目结构

```text
DailyPaper/
|- desktop_app.py          # 桌面界面入口
|- app.py                  # 主流程
|- fetch_arxiv.py          # arXiv API 抓取
|- prefetch.py             # PDF 缓存
|- affil_classify.py       # 机构匹配
|- pdf_affil.py            # PDF 作者块提取
|- runtime_control.py      # 暂停/取消控制
|- pipeline_report.py      # 结构化阶段报告
|- config.py               # 运行配置
|- tests/                  # 回归测试
`- build_exe.ps1           # PyInstaller 打包脚本
```

## 安装

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

## 直接运行

```powershell
.\venv\Scripts\python desktop_app.py
```

## 打包 EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

生成文件：

```text
dist/DailyPaperDesktop.exe
```

## 当前流程

1. 选择 arXiv 服务器日期和机构列表。
2. 在选定日期窗口内抓取 baseline 论文。
3. 按需执行机构补搜。
4. 对重点类别排序。
5. 将 PDF 缓存到 `cache_pdfs/YYYY-MM-DD/`。
6. 基于 PDF 作者块进行机构过滤。
7. 将 JSON 报告写入 `cache_pdfs/_reports/YYYY-MM-DD/`。

## 文档导航

- 英文 README：[README.md](README.md)
- 发布与打包说明：[RELEASE.md](RELEASE.md)

## 测试

```powershell
.\venv\Scripts\python -m unittest discover -s tests -v
```

## 说明

- Git 不会跟踪运行缓存、已下载 PDF、构建产物和虚拟环境。
- 当前桌面版已经替代旧网页界面和 `output_org` 分类流程。
