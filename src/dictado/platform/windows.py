"""Windows implementation of the platform layer.

This module only re-exports the existing Windows code so `app.py` can stay
platform-agnostic. The modules behind these names do not change behaviour.
"""

from __future__ import annotations

import os

import pystray

from dictado.autostart import apply_autostart
from dictado.cues import play_async
from dictado.overlay import Indicator
from dictado.paste import focus_window, foreground_window, paste_text

#: `app.py` checks this to decide whether a mic failure can be a permission.
is_macos = False

permission_prompt_available = False


def open_path(path) -> None:
    os.startfile(path)  # type: ignore[attr-defined]


def open_settings(which: str) -> None:
    """Windows shows no permission panel; a no-op keeps the interface shared."""


def start_icon(icon: pystray.Icon, setup=None) -> None:
    # On Windows pystray runs its own message loop from any thread.
    icon.run(setup)


__all__ = [
    "Indicator",
    "apply_autostart",
    "focus_window",
    "foreground_window",
    "is_macos",
    "open_path",
    "open_settings",
    "paste_text",
    "play_async",
    "start_icon",
]