<#
.SYNOPSIS
  Build the portable Windows package: dist\PDFMerger-<version>-win64.zip (+ .sha256)

.DESCRIPTION
  Needs Python 3.12 on Windows 10/11 (python.org or `winget install Python.Python.3.12`).
  Dependencies are installed from the hash-locked requirements\windows-py312.lock.
  Clone the repository to a local Windows folder first (building from a \\wsl$ path is
  slow and may fail).

  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-SkipTests]
#>
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Lock = "requirements\windows-py312.lock"

$Venv = Join-Path $Root ".venv-win"
if (-not (Test-Path "$Venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3.12 -m venv $Venv } else { python -m venv $Venv }
    if ($LASTEXITCODE -ne 0) { throw "could not create the virtual environment (is Python 3.12 installed?)" }
}
$Py = "$Venv\Scripts\python.exe"
$PyVer = & $Py -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($PyVer -ne "3.12") { throw "$Lock is for Python 3.12, but the venv uses Python $PyVer" }

# --require-hashes: every package must match the lock; --no-deps: the lock is complete.
& $Py -m pip install --no-deps --require-hashes -r $Lock
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "Compiling translations..."
Get-ChildItem "src\pdfmerger\i18n\*.ts" | ForEach-Object {
    & "$Venv\Scripts\pyside6-lrelease.exe" $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "lrelease failed for $($_.Name)" }
}

if (-not $SkipTests) {
    $env:QT_QPA_PLATFORM = "offscreen"
    & $Py -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "tests failed" }
    Remove-Item Env:\QT_QPA_PLATFORM
}

& $Py -m PyInstaller --noconfirm --clean packaging\pdfmerger.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$Version = (Select-String -Path "src\pdfmerger\__init__.py" -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
$Name = "PDFMerger-$Version-win64.zip"
$Zip = "dist\$Name"
if (Test-Path $Zip) { Remove-Item $Zip }
Compress-Archive -Path "dist\PDFMerger" -DestinationPath $Zip
$Hash = (Get-FileHash -Algorithm SHA256 $Zip).Hash.ToLower()
Set-Content -Path "$Zip.sha256" -Value "$Hash  $Name" -Encoding ascii
Write-Host "Done: $Zip"
Write-Host "SHA-256: $Hash"
