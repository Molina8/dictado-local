"""Paste text into the foreground window and restore the previous clipboard."""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

from dictado.clipboard_win import restore, set_text, snapshot

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56
VK_MENU = 0x12
SW_RESTORE = 9
KEYEVENTF_SCANCODE = 0x0008

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetFocus.argtypes = [wintypes.HWND]
user32.SetFocus.restype = wintypes.HWND
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


def _send_inputs(events: ctypes.Array) -> None:
    sent = user32.SendInput(len(events), events, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise OSError(f"SendInput envio {sent} de {len(events)} eventos")


def _nudge_foreground_lock() -> None:
    """A quick Alt tap is what lets a background process take the foreground."""
    events = (INPUT * 2)()
    events[0].type = INPUT_KEYBOARD
    events[0].ki = KEYBDINPUT(VK_MENU, 0x38, KEYEVENTF_SCANCODE, 0, 0)
    events[1].type = INPUT_KEYBOARD
    events[1].ki = KEYBDINPUT(VK_MENU, 0x38, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0, 0)
    _send_inputs(events)


def focus_window(hwnd: int) -> bool:
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.GetForegroundWindow() == hwnd:
        return True
    _activate(hwnd)
    if user32.GetForegroundWindow() == hwnd:
        return True
    _nudge_foreground_lock()
    _activate(hwnd)
    time.sleep(0.05)
    return user32.GetForegroundWindow() == hwnd


def _activate(hwnd: int) -> None:
    this_thread = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    attached: list[int] = []
    for other in (fg_thread, target_thread):
        if other and other != this_thread and other not in attached:
            if user32.AttachThreadInput(this_thread, other, True):
                attached.append(other)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        for other in attached:
            user32.AttachThreadInput(this_thread, other, False)


def send_ctrl_v() -> None:
    events = (INPUT * 4)()
    sequence = (
        (VK_CONTROL, 0),
        (VK_V, 0),
        (VK_V, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    )
    for index, (vk, flags) in enumerate(sequence):
        events[index].type = INPUT_KEYBOARD
        events[index].ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    _send_inputs(events)


def paste_text(text: str, restore_delay_ms: int, target_hwnd: int | None = None) -> None:
    if not text:
        return
    saved = snapshot()
    try:
        if target_hwnd:
            focus_window(target_hwnd)
        set_text(text)
        time.sleep(0.03)
        send_ctrl_v()
        time.sleep(max(restore_delay_ms, 0) / 1000)
    finally:
        try:
            restore(saved)
        except OSError:
            log.exception("No se pudo restaurar el portapapeles")
