"""Test collection and import rules per platform.

`test_clipboard`, `test_overlay` and `test_autostart` import Win32 bindings
at module level (ctypes.WinDLL, winreg), so on macOS and Linux CI those files
are removed from collection instead of failing the whole run. `test_hotkey`
pulls pynput, whose Key/KeyCode objects come from a backend that needs a
window system: on darwin it is fine ( Cocoa), on headless Linux CI it is
skipped the same way.
"""

from __future__ import annotations

import sys
from pathlib import Path

WINDOWS_ONLY_FILES = {
    "test_clipboard.py",
    "test_overlay.py",
    "test_autostart.py",
}

NO_WINDOW_SYSTEM_FILES = set() if sys.platform == "darwin" else {"test_hotkey.py"}


def pytest_ignore_collect(collection_path: Path, config) -> bool | None:
    name = collection_path.name
    if sys.platform != "win32" and name in WINDOWS_ONLY_FILES:
        return True
    if name in NO_WINDOW_SYSTEM_FILES:
        return True
    return None
