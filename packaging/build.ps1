# Build the windowed app into dist\DictadoLocal.
param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $Python) {
    $candidate = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path $candidate)) {
        throw "No hay .venv. Crea uno con: py -3.11 -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements.txt pyinstaller==6.16.0"
    }
    $Python = $candidate
}

& $Python -m pip install --disable-pip-version-check "pyinstaller==6.16.0"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Python -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\DictadoLocal.spec")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$dist = Join-Path $Root "dist\DictadoLocal"
$exe = Join-Path $dist "DictadoLocal.exe"
if (-not (Test-Path $exe)) {
    throw "No se genero $exe"
}

Copy-Item (Join-Path $Root "config.example.yaml") (Join-Path $dist "config.example.yaml") -Force
Copy-Item (Join-Path $Root "install.ps1") (Join-Path $dist "install.ps1") -Force
Copy-Item (Join-Path $Root "install.cmd") (Join-Path $dist "install.cmd") -Force

& $Python -c @"
import struct, sys
path = sys.argv[1]
data = open(path, 'rb').read(4096)
pe = struct.unpack_from('<I', data, 0x3C)[0]
subsystem = struct.unpack_from('<H', data, pe + 92)[0]
print('subsystem', subsystem)
sys.exit(0 if subsystem == 2 else 1)
"@ $exe
if ($LASTEXITCODE -ne 0) { throw "DictadoLocal.exe sigue siendo una app de consola" }

Write-Host "Listo: $exe"
