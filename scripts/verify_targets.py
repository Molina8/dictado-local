"""Paste the same marker into Notepad, Edge and VS Code when they are installed."""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from dictado.paste import INPUT, KEYBDINPUT, _send_inputs, focus_window, paste_text

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

MARKER = "dictado-local objetivo áéí"
ROOT = Path.home() / "AppData" / "Local" / "Temp" / "dictado-local-verify"


def window_text(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def window_class(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def windows_for(pid: int) -> list[int]:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and window_text(hwnd):
            found.append(int(hwnd))
        return True

    user32.EnumWindows(visit, 0)
    return found


def wait_title(fragment: str, timeout: float = 15) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd) and fragment.lower() in window_text(hwnd).lower():
                found.append(int(hwnd))
            return True

        user32.EnumWindows(visit, 0)
        if found:
            return found[-1]
        time.sleep(0.25)
    return 0


def close_window(hwnd: int) -> None:
    user32.PostMessageW(hwnd, 0x0010, 0, 0)


def chord(vk_mod: int, vk_key: int) -> None:
    events = (INPUT * 4)()
    sequence = ((vk_mod, 0), (vk_key, 0), (vk_key, 0x0002), (vk_mod, 0x0002))
    for index, (vk, flags) in enumerate(sequence):
        events[index].type = 1
        events[index].ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    _send_inputs(events)


def type_unicode(text: str) -> None:
    events = (INPUT * (len(text) * 2))()
    for index, char in enumerate(text):
        events[index * 2].type = 1
        events[index * 2].ki = KEYBDINPUT(0, ord(char), 0x0004, 0, 0)
        events[index * 2 + 1].type = 1
        events[index * 2 + 1].ki = KEYBDINPUT(0, ord(char), 0x0004 | 0x0002, 0, 0)
    _send_inputs(events)


def press_enter() -> None:
    events = (INPUT * 2)()
    events[0].type = 1
    events[0].ki = KEYBDINPUT(0x0D, 0, 0, 0, 0)
    events[1].type = 1
    events[1].ki = KEYBDINPUT(0x0D, 0, 0x0002, 0, 0)
    _send_inputs(events)


def read_edit(hwnd: int) -> str:
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
    length = int(user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, None))
    buffer = ctypes.create_unicode_buffer(max(length, 0) + 1)
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_wchar_p]
    user32.SendMessageW(hwnd, WM_GETTEXT, len(buffer), buffer)
    return buffer.value


def child_edit(hwnd: int) -> int:
    edit = user32.FindWindowExW(hwnd, None, "Edit", None)
    if edit:
        return int(edit)
    # One level deeper covers the classic Notepad frame.
    child = user32.FindWindowExW(hwnd, None, None, None)
    while child:
        nested = user32.FindWindowExW(child, None, "Edit", None)
        if nested:
            return int(nested)
        child = user32.FindWindowExW(hwnd, child, None, None)
    return 0


def launch(command: list[str]) -> subprocess.Popen:
    return subprocess.Popen(command)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]


def click_center(hwnd: int) -> None:
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    x = (rect.left + rect.right) // 2
    y = (rect.top + rect.bottom) // 2
    user32.SetCursorPos(x, y)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def copied_text() -> str:
    from dictado.clipboard_win import get_text

    chord(0x11, 0x41)
    time.sleep(0.2)
    chord(0x11, 0x43)
    time.sleep(0.3)
    return get_text()


def check_notepad() -> str:
    target = ROOT / "notepad.txt"
    target.write_text("", encoding="utf-8")
    launch([r"C:\Windows\System32\notepad.exe", str(target)])
    hwnd = wait_title("notepad.txt")
    if not hwnd:
        return "notepad: no aparecio la ventana"
    before = window_text(hwnd)
    focus_window(hwnd)
    click_center(hwnd)
    time.sleep(0.2)
    paste_text(MARKER, 500, hwnd)
    time.sleep(0.3)
    copied = copied_text()
    chord(0x11, 0x53)
    time.sleep(0.8)
    saved = target.read_text(encoding="utf-8")
    close_window(hwnd)
    if MARKER in saved or MARKER in copied:
        return f"notepad: ok class={window_class(hwnd)} saved={MARKER in saved} copied={MARKER in copied}"
    return (
        f"notepad: no class={window_class(hwnd)} before={before!r} "
        f"after={window_text(hwnd)!r} file={saved!r} clipboard={copied!r}"
    )


def check_edge() -> str:
    html = ROOT / "caja.html"
    html.write_text(
        "<!doctype html><meta charset='utf-8'><title>dictado-caja</title>"
        "<textarea id='t' autofocus style='width:95%;height:70%'></textarea>",
        encoding="utf-8",
    )
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.is_file():
        return "edge: no instalado"
    launch([str(edge), "--new-window", html.as_uri()])
    hwnd = wait_title("dictado-caja", 15)
    if not hwnd:
        return "edge: no aparecio la ventana"
    time.sleep(1.5)
    paste_text(MARKER, 600, hwnd)
    time.sleep(0.4)
    chord(0x11, 0x41)  # Ctrl+A
    time.sleep(0.15)
    chord(0x11, 0x43)  # Ctrl+C
    time.sleep(0.3)
    from dictado.clipboard_win import get_text

    copied = get_text()
    close_window(hwnd)
    if MARKER in copied:
        return "edge: ok"
    return f"edge: texto no copiado title={window_text(hwnd)!r} clipboard={copied!r}"


def check_vscode() -> str:
    code = Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "Code.exe"
    if not code.is_file():
        return "vscode: no instalado"
    target = ROOT / "vscode.txt"
    target.write_text("", encoding="utf-8")
    launch([str(code), "--new-window", "--disable-workspace-trust", str(target)])
    hwnd = wait_title("vscode.txt", 20)
    if not hwnd:
        return "vscode: no aparecio la ventana"
    time.sleep(1.2)
    focus_window(hwnd)
    time.sleep(0.2)
    chord(0x11, 0x50)  # Ctrl+P, abre el fichero aunque haya otra pestaña
    time.sleep(0.4)
    type_unicode("vscode.txt")
    time.sleep(0.3)
    press_enter()
    time.sleep(0.5)
    paste_text(MARKER, 700, hwnd)
    time.sleep(0.4)
    copied = copied_text()
    chord(0x11, 0x53)
    time.sleep(1.2)
    saved = target.read_text(encoding="utf-8")
    close_window(hwnd)
    if MARKER in saved or MARKER in copied:
        return f"vscode: ok saved={MARKER in saved} copied={MARKER in copied}"
    return f"vscode: no title={window_text(hwnd)!r} file={saved!r} clipboard={copied!r}"


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    checks = (check_notepad, check_edge, check_vscode)
    failed = 0
    for check in checks:
        try:
            line = check()
        except Exception as exc:
            line = f"{check.__name__}: excepcion {exc}"
            failed += 1
        else:
            if ": ok" not in line:
                failed += 1
        print(line, flush=True)
    print("WORD: no esta instalado en las rutas de Office", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
