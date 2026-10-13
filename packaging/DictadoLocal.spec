# -*- mode: python ; coding: utf-8 -*-
"""Windowed onedir build. CUDA DLLs stay inside the nvidia packages."""

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
    "nvidia.cublas",
    "nvidia.cuda_runtime",
    "nvidia.cudnn",
    "nvidia.cuda_nvrtc",
]

datas = [(str(ROOT / "config.example.yaml"), ".")]
binaries = []
hiddenimports = [
    "yaml",
    "pystray._win32",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "_sounddevice_data",
]

for name in ("hf_xet", "tqdm", "filelock", "fsspec"):
    if importlib.util.find_spec(name):
        PACKAGES.append(name)

for name in PACKAGES:
    package_datas, package_binaries, package_hidden = collect_all(name)
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
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
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
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "dictado.ico"),
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
