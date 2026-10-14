#!/usr/bin/env bash
# Build the unsigned macOS .app + .dmg on an Apple Silicon Mac or CI.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
VERSION="$(python3 packaging/_version.py)"
if [ -z "$VERSION" ]; then
    echo "No pude leer la version de src/dictado/__init__.py" >&2
    exit 1
fi
DMG="dist/DictadoLocal-${VERSION}-macos-arm64.dmg"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "No hay $PYTHON_BIN. Instala Xcode CLT o Homebrew Python 3.11." >&2
    exit 1
fi

"$PYTHON_BIN" -m venv .venv-mac
./.venv-mac/bin/pip install --disable-pip-version-check --upgrade pip >/dev/null
./.venv-mac/bin/pip install --disable-pip-version-check -r requirements.txt "pyinstaller==6.16.0"

# .icns from the existing .ico (sips is part of macOS).
if [ ! -f assets/dictado.icns ]; then
    mkdir -p assets/icon.iconset
    for size in 16 32 64 128 256 512; do
        double=$((size * 2))
        sips -z "$size" "$size" assets/dictado.ico --out "assets/icon.iconset/icon_${size}x${size}.png" >/dev/null
        sips -z "$double" "$double" assets/dictado.ico --out "assets/icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
    done
    iconutil -c icns assets/icon.iconset -o assets/dictado.icns
    rm -rf assets/icon.iconset
fi

./.venv-mac/bin/pyinstaller --noconfirm --clean packaging/DictadoLocal-mac.spec

APP="dist/DictadoLocal.app"
if [ ! -d "$APP" ]; then
    echo "No se genero $APP" >&2
    exit 1
fi
cp config.example.yaml "$APP/Contents/Resources/config.example.yaml"

# Info.plist essentials
PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Print :NSMicrophoneUsageDescription" "$PLIST" >/dev/null 2>&1 || {
    echo "Falta NSMicrophoneUsageDescription en $PLIST" >&2
    exit 1
}
/usr/libexec/PlistBuddy -c "Print :LSUIElement" "$PLIST" >/dev/null 2>&1 || {
    echo "Falta LSUIElement en $PLIST" >&2
    exit 1
}

# Ad-hoc signature so the binary starts on arm64 without a Developer ID.
codesign --force --deep -s - "$APP"
echo "Bundle firmado ad-hoc:"; codesign -dv "$APP" 2>&1 | head -4

# Remove the quarantine attr that the CI runner may have stamped.
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

# Smoke: the bundle binary answers --selftest
"$APP/Contents/MacOS/DictadoLocal" --selftest

rm -f "$DMG"
hdiutil create -volname "Dictado local" -srcfolder "$APP" -ov -format UDZO "$DMG"
ls -la "$DMG"
echo "Listo: $DMG"