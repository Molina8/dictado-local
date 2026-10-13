"""Save and restore Windows clipboard formats that live in an HGLOBAL."""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_TEXT = 1
CF_BITMAP = 2
CF_METAFILEPICT = 3
CF_OEMTEXT = 7
CF_DIB = 8
CF_PALETTE = 9
CF_UNICODETEXT = 13
CF_ENHMETAFILE = 14
CF_HDROP = 15
CF_DIBV5 = 17
GMEM_MOVEABLE = 0x0002

# These handles are not HGLOBAL memory. Locking them corrupts bitmaps and metafiles.
HANDLE_FORMATS = frozenset({CF_BITMAP, CF_METAFILEPICT, CF_PALETTE, CF_ENHMETAFILE})

# One format, not the whole clipboard. A 4K DIB still fits; a runaway allocation does not.
MAX_CLIPBOARD_FORMAT_BYTES = 32 * 1024 * 1024

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
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT

ClipboardSnapshot = dict[int, bytes]


def allowed_hglobal_formats() -> frozenset[int]:
    """Text, DIB, HTML, RTF and file drops. Ids for HTML and RTF are registered."""
    registered = (
        user32.RegisterClipboardFormatW("HTML Format"),
        user32.RegisterClipboardFormatW("Rich Text Format"),
    )
    return frozenset(
        {
            CF_TEXT,
            CF_OEMTEXT,
            CF_UNICODETEXT,
            CF_DIB,
            CF_DIBV5,
            CF_HDROP,
            *(int(fmt) for fmt in registered if fmt),
        }
    )


def accept_clipboard_format(fmt: int, size: int, allowed: frozenset[int] | None = None) -> bool:
    if fmt in HANDLE_FORMATS:
        return False
    allowed = allowed_hglobal_formats() if allowed is None else allowed
    if fmt not in allowed:
        return False
    return 0 < size <= MAX_CLIPBOARD_FORMAT_BYTES


def _open_clipboard() -> None:
    for _ in range(25):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.02)
    raise OSError("No se pudo abrir el portapapeles")


def _read_format(fmt: int, allowed: frozenset[int]) -> bytes | None:
    if not accept_clipboard_format(fmt, 1, allowed):
        return None
    handle = user32.GetClipboardData(fmt)
    if not handle:
        return None
    size = int(kernel32.GlobalSize(handle))
    if not accept_clipboard_format(fmt, size, allowed):
        log.warning("Formato %s descartado (%s bytes)", fmt, size)
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
    allowed = allowed_hglobal_formats()
    _open_clipboard()
    try:
        fmt = 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            data = _read_format(int(fmt), allowed)
            if data is not None:
                saved[int(fmt)] = data
        return saved
    finally:
        user32.CloseClipboard()


def _write_formats(formats: ClipboardSnapshot) -> None:
    allowed = allowed_hglobal_formats()
    user32.EmptyClipboard()
    for fmt, data in formats.items():
        if not accept_clipboard_format(int(fmt), len(data), allowed):
            continue
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
    allowed = allowed_hglobal_formats()
    _open_clipboard()
    try:
        data = _read_format(CF_UNICODETEXT, allowed)
    finally:
        user32.CloseClipboard()
    if not data:
        return ""
    return data.decode("utf-16-le", errors="ignore").rstrip("\x00")
