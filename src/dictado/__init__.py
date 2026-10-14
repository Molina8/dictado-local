"""Local push-to-talk dictation for Windows and macOS (Apple Silicon)."""

from __future__ import annotations

import sys

# Keep this equal to the GitHub release tag, without the leading v.
__version__ = "0.2.1"

DEFAULT_HOTKEY = "ctrl_r" if sys.platform != "darwin" else "alt_r"
