$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "??????? Python: $python"
}

& $python -m PyInstaller --noconfirm --clean --onefile --noconsole --name DailyPaperDesktopLauncher desktop_app.py
Write-Host "?????????: dist\DailyPaperDesktopLauncher.exe"
