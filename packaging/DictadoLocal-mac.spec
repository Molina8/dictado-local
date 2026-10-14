# -*- mode: python ; coding: utf-8 -*-
"""macOS .app bundle (arm64, onedir). Unsigned; ad-hoc signing happens in CI."""

import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent
PACKAGES = [
    "faster_whisper",
    "ctranslate2",
    "tokenizers",
    "huggingface_hub",
    "onnxruntime",
    "numpy",
    "av",
    "pystray",
    "PIL",
    "sounddevice",
    "_sounddevice_data",
    "pynput",
    "mlx_whisper",
    "mlx",
    # pystray's darwin backend imports these at import time. collect_all
    # pulls the PyObjC binaries; a bare hiddenimport leaves them out.
    "objc",
    "CoreFoundation",
    "Foundation",
    "AppKit",
    "Cocoa",
    "Quartz",
    "ApplicationServices",
]

datas = [(str(ROOT / "config.example.yaml"), ".")]
binaries = []
hiddenimports = [
    "yaml",
    # get_platform() loads this with importlib, so PyInstaller never sees it.
    "dictado.platform.macos",
    "dictado.permissions",
    "pystray._darwin",
    "pystray._dummy",
    "pynput.keyboard._darwin",
    "pynput.mouse._darwin",
    "_sounddevice_data",
    "Cocoa",
    "Quartz",
    "ApplicationServices",
    "AppKit",
    "Foundation",
]

for name in ("hf_xet", "tqdm", "filelock", "fsspec"):
    if importlib.util.find_spec(name):
        PACKAGES.append(name)

for name in PACKAGES:
    try:
        package_datas, package_binaries, package_hidden = collect_all(name)
    except Exception:
        # mlx extras may be absent on the build box; keep collecting the rest.
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

block_cipher = None

a = Analysis(
    [str(ROOT / "src" / "dictado" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DictadoLocal",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DictadoLocal",
)

app = BUNDLE(
    coll,
    name="DictadoLocal.app",
    icon=str(ROOT / "assets" / "dictado.icns"),
    bundle_identifier="com.molina8.dictadolocal",
    version="0.2.1",
    info_plist={
        "NSMicrophoneUsageDescription": "Dictado local necesita el microfono para transcribir tu voz en el equipo.",
        "NSAppleEventsUsageDescription": "Dictado local envia Cmd+V a la app activa para pegar la transcripcion.",
        "LSUIElement": True,
    },
)