#!/usr/bin/env python3
"""Render assets/dictado.ico into an assets/icon.iconset for iconutil.

macOS runners cannot feed .ico to sips; PIL (already in the venv) reads the
ico and writes every PNG the iconset needs.
"""

import sys
from pathlib import Path

from PIL import Image

root = Path(sys.argv[1]).resolve()
ico = root / "assets" / "dictado.ico"
iconset = root / "assets" / "icon.iconset"

source = Image.open(ico)
source.load()

sizes = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}
iconset.mkdir(parents=True, exist_ok=True)
for name, target in sizes.items():
    image = source.resize((target, target), Image.Resampling.LANCZOS)
    image.save(iconset / name, format="PNG")
print(f"iconset listo en {iconset}")
