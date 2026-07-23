# Release Guide / 发布说明

[README (English)](README.md) | [README 中文版](README.zh-CN.md)

## For Users: Download The EXE / 给使用者：直接下载 EXE

### English

1. Open the repository Releases page on GitHub.
2. Download `DailyPaperDesktop.exe` from the latest release assets.
3. Double-click the executable on Windows.
4. If SmartScreen appears, choose "More info" and then "Run anyway" if you trust the build.

### 中文

1. 打开 GitHub 仓库的 Releases 页面。
2. 在最新发布版本的附件中下载 `DailyPaperDesktop.exe`。
3. 在 Windows 中双击运行该文件。
4. 如果弹出 SmartScreen，请在确认来源可信后点击“更多信息”再选择“仍要运行”。

## For Maintainers: Build Locally / 给维护者：本地自行打包

### English

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Generated file:

```text
dist/DailyPaperDesktop.exe
```

### 中文

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

生成文件：

```text
dist/DailyPaperDesktop.exe
```

## Release Checklist / 发布检查清单

### English

- Run tests before packaging.
- Rebuild the executable from a clean working tree when possible.
- Verify that `dist/DailyPaperDesktop.exe` starts correctly.
- Create a GitHub Release and upload the EXE asset.

### 中文

- 打包前先运行测试。
- 尽量在干净工作区中重新构建 EXE。
- 确认 `dist/DailyPaperDesktop.exe` 可以正常启动。
- 在 GitHub 创建 Release，并上传 EXE 附件。
