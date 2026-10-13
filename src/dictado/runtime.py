"""Process setup shared by the module entry and the frozen executable.

Windows keeps the per-monitor DPI v2 setup. macOS has no DPI step and skips
the frozen cwd change: a .app is not launched from a shell directory.
"""

from __future__ import annotations

import ctypes
import multiprocessing
import os
import sys
from ctypes import wintypes
from pathlib import Path


def prepare_runtime() -> None:
    multiprocessing.freeze_support()
    if sys.platform != "win32":
        return
    _enable_per_monitor_dpi()
    if not getattr(sys, "frozen", False):
        return
    exe_dir = Path(sys.executable).resolve().parent
    os.chdir(exe_dir)


def _enable_per_monitor_dpi() -> None:
    """Place the pill in real pixels on the monitor under the cursor."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_context = user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = wintypes.BOOL
        # -4 is DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
        if set_context(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness.restype = ctypes.c_long
        if shcore.SetProcessDpiAwareness(2) == 0:
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass
