# Build on Windows 10/11 x64 with Python 3.12 and Inno Setup 6 installed.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

$python = '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python build environment.' }
}
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip update failed.' }
& $python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Could not install Windows build dependencies.' }

& $python -m PyInstaller --noconfirm --clean --onedir --windowed --name RTEHosting `
  --icon build\rte-hosting.ico `
  --add-data 'rte_hosting\static;rte_hosting\static' `
  --collect-all webview --collect-all paramiko --hidden-import webview.platforms.edgechromium `
  run.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

$iscc = @('C:\Program Files (x86)\Inno Setup 6\ISCC.exe', 'C:\Program Files\Inno Setup 6\ISCC.exe') `
    | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Install Inno Setup 6 first: https://jrsoftware.org/isinfo.php' }
& $iscc build\RTEHosting.iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }

$installer = 'release\RTEHosting-Setup-v0.2.0.exe'
if (-not (Test-Path $installer)) { throw "Expected installer not found: $installer" }
Write-Host "Build complete: $installer"
