"""Short tones while dictating. Failures are ignored."""

from __future__ import annotations

import threading


def play(kind: str) -> None:
    try:
        import winsound
    except Exception:
        return
    try:
        if kind == "record":
            winsound.Beep(880, 45)
        elif kind == "done":
            winsound.Beep(620, 35)
    except Exception:
        return


def play_async(kind: str) -> None:
    threading.Thread(target=play, args=(kind,), name="dictado-cue", daemon=True).start()
