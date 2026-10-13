"""Save and restore the Windows clipboard, including non-text formats."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
user32.EnumClipboardFormats.restype = wintypes.UINT
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL

ClipboardSnapshot = dict[int, bytes]


def _open_clipboard() -> None:
    for _ in range(25):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.02)
    raise OSError("No se pudo abrir el portapapeles")


def _read_format(fmt: int) -> bytes | None:
    handle = user32.GetClipboardData(fmt)
    if not handle:
        return None
    size = kernel32.GlobalSize(handle)
    if not size:
        return None
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        return None
    try:
        return ctypes.string_at(pointer, size)
    finally:
        kernel32.GlobalUnlock(handle)


def snapshot() -> ClipboardSnapshot:
    saved: ClipboardSnapshot = {}
    _open_clipboard()
    try:
        fmt = 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            data = _read_format(fmt)
            if data is not None:
                saved[int(fmt)] = data
        return saved
    finally:
        user32.CloseClipboard()


def _write_formats(formats: ClipboardSnapshot) -> None:
    user32.EmptyClipboard()
    for fmt, data in formats.items():
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            continue
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            continue
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(fmt, handle):
            kernel32.GlobalFree(handle)


def set_text(text: str) -> None:
    encoded = text.encode("utf-16-le") + b"\x00\x00"
    _open_clipboard()
    try:
        _write_formats({CF_UNICODETEXT: encoded})
    finally:
        user32.CloseClipboard()


def restore(saved: ClipboardSnapshot) -> None:
    _open_clipboard()
    try:
        _write_formats(saved)
    finally:
        user32.CloseClipboard()


def get_text() -> str:
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return ""
    _open_clipboard()
    try:
        data = _read_format(CF_UNICODETEXT)
    finally:
        user32.CloseClipboard()
    if not data:
        return ""
    return data.decode("utf-16-le", errors="ignore").rstrip("\x00")
