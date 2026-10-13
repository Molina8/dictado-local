"""Platform implementations exposed through `get_platform()`.

Each module is imported lazily so the Windows code (ctypes.WinDLL at module
level) never runs on macOS and the macOS code (pyobjc) never runs on Windows.
"""

from __future__ import annotations

import sys
from types import ModuleType

_MACOS = "dictado.platform.macos"
_WINDOWS = "dictado.platform.windows"

_cache: dict[str, ModuleType] = {}


def get_platform() -> ModuleType:
    """Import the implementation for this platform, once per process."""
    name = _WINDOWS if sys.platform == "win32" else _MACOS if sys.platform == "darwin" else ""
    if not name:
        raise NotImplementedError(f"Plataforma no soportada: {sys.platform}")
    module = _cache.get(name)
    if module is None:
        import importlib

        module = importlib.import_module(name)
        _cache[name] = module
    return module
