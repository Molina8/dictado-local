# Instala Dictado local en %LOCALAPPDATA%\Programs\dictado-local y lo arranca.
$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$candidates = @(
    (Join-Path $here "dist\DictadoLocal"),
    $here
)
$src = $null
foreach ($candidate in $candidates) {
    if (Test-Path (Join-Path $candidate "DictadoLocal.exe")) {
        $src = (Resolve-Path $candidate).Path
        break
    }
}
if (-not $src) {
    throw "No encuentro DictadoLocal.exe. Genera el ejecutable con packaging\build.ps1."
}

$dest = Join-Path $env:LOCALAPPDATA "Programs\dictado-local"
$exe = Join-Path $dest "DictadoLocal.exe"

Get-Process -Name "DictadoLocal" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

$destFull = $null
if (Test-Path $dest) {
    $destFull = (Resolve-Path $dest).Path
}
if ($destFull -ne $src) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    & robocopy $src $dest /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /nc /ns /np | Out-Host
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy fallo con el codigo $LASTEXITCODE"
    }
}

$shell = New-Object -ComObject WScript.Shell

function New-DictadoShortcut([string]$Path) {
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $exe
    $link.WorkingDirectory = $dest
    $link.Description = "Dictado local"
    $link.IconLocation = "$exe,0"
    $link.Save()
}

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
New-DictadoShortcut (Join-Path $startMenu "Dictado local.lnk")

$desktop = [Environment]::GetFolderPath("Desktop")
if ($desktop) {
    New-DictadoShortcut (Join-Path $desktop "Dictado local.lnk")
}

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
New-Item -Path $runKey -Force | Out-Null
Set-ItemProperty -Path $runKey -Name "DictadoLocal" -Value "`"$exe`""

$cfgDir = Join-Path $env:APPDATA "dictado-local"
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
$cfg = Join-Path $cfgDir "config.yaml"
$example = Join-Path $dest "config.example.yaml"
if (-not (Test-Path $example)) {
    $example = Join-Path $dest "_internal\config.example.yaml"
}
if (-not (Test-Path $cfg) -and (Test-Path $example)) {
    Copy-Item $example $cfg
}

$model = Join-Path $env:LOCALAPPDATA "dictado-local\models\large-v3-turbo\model.bin"
if (Test-Path $model) {
    Write-Host "El modelo grande ya esta en el equipo."
} else {
    Write-Host "El modelo se descargara la primera vez que se abra la app."
}

Start-Process -FilePath $exe -WorkingDirectory $dest
Write-Host "Instalado en $dest"
Write-Host "Para abrirlo: menu Inicio, escribe Dictado local, y pulsa Enter."
Write-Host "Tambien esta en el escritorio y en $exe"
exit 0
