"""Paste into an EDIT control that runs its own message loop."""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes

from dictado.paste import INPUT, paste_text

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CLOSE = 0x0010
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
ES_AUTOHSCROLL = 0x0080

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SendMessageW.restype = ctypes.c_ssize_t
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE


def read_text(hwnd: int) -> str:
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
    length = int(user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, None))
    buffer = ctypes.create_unicode_buffer(max(length, 0) + 1)
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_wchar_p]
    user32.SendMessageW(hwnd, WM_GETTEXT, len(buffer), buffer)
    return buffer.value


def _ui(ready: threading.Event, holder: dict) -> None:
    instance = kernel32.GetModuleHandleW(None)
    edit = user32.CreateWindowExW(
        0,
        "Edit",
        "",
        WS_OVERLAPPEDWINDOW | WS_VISIBLE | ES_AUTOHSCROLL,
        220,
        220,
        720,
        140,
        None,
        None,
        instance,
        None,
    )
    holder["hwnd"] = int(edit or 0)
    ready.set()
    if not edit:
        return
    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))


def main() -> int:
    print(f"sizeof_INPUT={ctypes.sizeof(INPUT)}")
    marker = "dictado-local pegado áéí"
    ready = threading.Event()
    holder: dict = {}
    thread = threading.Thread(target=_ui, args=(ready, holder), daemon=True)
    thread.start()
    if not ready.wait(3) or not holder.get("hwnd"):
        print("NO_WINDOW")
        return 1
    hwnd = holder["hwnd"]
    try:
        time.sleep(0.3)
        paste_text(marker, restore_delay_ms=400, target_hwnd=hwnd)
        time.sleep(0.3)
        print(f"foreground={int(user32.GetForegroundWindow() or 0)} edit={hwnd}")
        found = read_text(hwnd)
        print(f"edit_text={found!r}")
        if marker not in found:
            print("PASTE_MISMATCH")
            return 2
        print("PASTE_OK")
        return 0
    finally:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


if __name__ == "__main__":
    sys.exit(main())
