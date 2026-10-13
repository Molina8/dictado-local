"""Register the installed app in HKCU Run so it starts with Windows."""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "DictadoLocal"


def quote_command(executable: str) -> str:
    return f'"{executable}"'


def current_command() -> str:
    if getattr(sys, "frozen", False):
        return quote_command(str(Path(sys.executable).resolve()))
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.is_file() else Path(sys.executable)
    return f'"{executable}" -m dictado'


def read_run_command() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, RUN_VALUE)
    except FileNotFoundError:
        return None
    text = str(value).strip()
    return text or None


def apply_autostart(enabled: bool, command: str | None = None) -> None:
    """Write or remove the HKCU Run value. `command` is the registry string."""
    if enabled:
        _write(command if command is not None else current_command())
        return
    _delete()


def _write(command: str) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command)


def _delete() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE)
    except FileNotFoundError:
        return
