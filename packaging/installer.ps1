# Build dist\DictadoLocal and compile the Inno Setup installer.
param(
    [string]$Python = "",
    [string]$Destination = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "build.ps1") -Python $Python
}

$staged = Join-Path $Root "dist\DictadoLocal"
$exe = Join-Path $staged "DictadoLocal.exe"
if (-not (Test-Path $exe)) {
    throw "No esta $exe"
}

$banned = @(Get-ChildItem $staged -Recurse -Filter "model.bin" -File -ErrorAction SilentlyContinue)
if ($banned.Count -gt 0) {
    throw "El instalador no puede incluir model.bin ($($banned[0].FullName))"
}

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    throw "No esta Inno Setup 6 (ISCC.exe). Instala JRSoftware.InnoSetup."
}

$version = "0.2.1"
$init = Join-Path $Root "src\dictado\__init__.py"
if (Test-Path $init) {
    $text = Get-Content $init -Raw
    if ($text -match '__version__\s*=\s*"([^"]+)"') {
        $version = $Matches[1]
    }
}

# The workspace path is long enough that ISCC hits MAX_PATH inside dist.
# A junction gives the compiler a short path. rmdir removes only the link.
$link = $null
foreach ($candidate in @("C:\dlsetup", "C:\dls")) {
    if (-not (Test-Path $candidate)) {
        $link = $candidate
        break
    }
}
if (-not $link) {
    throw "No hay una ruta corta libre (C:\dlsetup o C:\dls) para compilar el setup"
}
cmd /c mklink /J $link $Root
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo crear el enlace $link"
}
try {
    & $iscc "/Qp" "/DMyAppVersion=$version" (Join-Path $link "packaging\DictadoLocal.iss")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    cmd /c rmdir $link
}

$setup = Join-Path $Root "dist\DictadoLocal-Setup.exe"
if (-not (Test-Path $setup)) {
    throw "No se genero $setup"
}
if ($Destination) {
    $parent = Split-Path -Parent $Destination
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Copy-Item $setup $Destination -Force
    Write-Host "Copiado a $Destination"
}

$bytes = (Get-Item $setup).Length
Write-Host ("Listo: {0} ({1:N1} MB)" -f $setup, ($bytes / 1MB))
