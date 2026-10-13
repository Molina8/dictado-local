"""Floating dictation pill. Always on top, click-through, never activated.

The window is a per-pixel-alpha layered popup:
WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE.
It is not in the taskbar and it does not take keyboard focus, so the dictated
text still lands in the window that was active when the hotkey went down.
"""

from __future__ import annotations

import ctypes
import logging
import math
import threading
import time
from collections.abc import Callable, Sequence
from ctypes import wintypes

import numpy as np
from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shcore = ctypes.WinDLL("shcore", use_last_error=True)
winmm = ctypes.WinDLL("winmm", use_last_error=True)

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
LRESULT = ctypes.c_ssize_t
HMONITOR = getattr(wintypes, "HMONITOR", wintypes.HANDLE)

WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
WM_TIMER = 0x0113
WM_MOUSEACTIVATE = 0x0021
WM_NCHITTEST = 0x0084
WM_APP = 0x8000
WM_SET_MODE = WM_APP + 1
MA_NOACTIVATE = 3
HTTRANSPARENT = -1
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
EXSTYLE = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
SW_HIDE = 0
SW_SHOWNA = 8
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
ULW_ALPHA = 2
SPI_GETWORKAREA = 0x0030
MONITOR_DEFAULTTOPRIMARY = 1
MONITORINFOF_PRIMARY = 1
BI_RGB = 0
DIB_RGB_COLORS = 0
TIMER_ID = 1

BAR_COUNT = 9
BASE_WIDTH = 172
BASE_HEIGHT = 50
APPEAR_S = 0.18
LEAVE_S = 0.15
HOLD_READY_S = 0.70
HOLD_ERROR_S = 1.00
MARGIN_PX_AT_96 = 32
MODE_HIDE = 0
MODE_LISTENING = 1
MODE_TRANSCRIBING = 2
MODE_READY = 3
MODE_ERROR = 4
STATE_BY_MODE = {
    MODE_LISTENING: "listening",
    MODE_TRANSCRIBING: "transcribing",
    MODE_READY: "ready",
    MODE_ERROR: "error",
}
POSITIONS = {
    "bottom-center": (0.5, "bottom"),
    "bottom-left": (0.0, "bottom"),
    "bottom-right": (1.0, "bottom"),
    "top-center": (0.5, "top"),
}
PALETTE = {
    "listening": {"fill": (18, 18, 22, 210), "border": (255, 255, 255, 42), "mark": (247, 244, 238, 255)},
    "transcribing": {"fill": (18, 20, 32, 216), "border": (188, 200, 255, 78), "mark": (214, 220, 245, 255)},
    "ready": {"fill": (14, 32, 24, 216), "border": (150, 220, 170, 90), "mark": (156, 230, 176, 255)},
    "error": {"fill": (42, 16, 18, 220), "border": (255, 160, 150, 96), "mark": (255, 186, 178, 255)},
}


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", wintypes.BYTE * 32),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
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
user32.DestroyWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = HMONITOR
user32.GetMonitorInfoW.argtypes = [HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, MONITORENUMPROC, wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE),
    wintypes.HDC,
    ctypes.POINTER(POINT),
    wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION),
    wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wintypes.BOOL
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.c_void_p,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
shcore.GetDpiForMonitor.argtypes = [HMONITOR, ctypes.c_int, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
shcore.GetDpiForMonitor.restype = ctypes.c_long
winmm.timeBeginPeriod.argtypes = [wintypes.UINT]
winmm.timeBeginPeriod.restype = wintypes.UINT
winmm.timeEndPeriod.argtypes = [wintypes.UINT]
winmm.timeEndPeriod.restype = wintypes.UINT

try:
    user32.GetDpiForSystem.argtypes = []
    user32.GetDpiForSystem.restype = wintypes.UINT
except AttributeError:
    pass


def accepts_generation(current: int, incoming: int) -> bool:
    """Ignore a late message from an older push-to-talk gesture."""
    return incoming >= current


def pill_pixel_size(dpi: int, scale: float) -> tuple[int, int]:
    dpi_value = 96 if dpi <= 0 else dpi
    factor = (dpi_value / 96.0) * scale
    width = min(1600, max(1, round(BASE_WIDTH * factor)))
    height = min(800, max(1, round(BASE_HEIGHT * factor)))
    return width, height


def pill_origin(
    work: tuple[int, int, int, int],
    size: tuple[int, int],
    position: str,
    margin: int,
) -> tuple[int, int]:
    left, top, right, bottom = work
    width, height = size
    anchor, edge = POSITIONS.get(position, POSITIONS["bottom-center"])
    if anchor <= 0:
        x = left + margin
    elif anchor >= 1:
        x = right - width - margin
    else:
        x = left + max(0, (right - left - width) // 2)
    y = top + margin if edge == "top" else bottom - height - margin
    max_x = right - width
    if x < left or max_x < left:
        x = left
    elif x > max_x:
        x = max_x
    max_y = bottom - height
    if y < top or max_y < top:
        y = top
    elif y > max_y:
        y = max_y
    return int(x), int(y)


def smooth_levels(
    current: Sequence[float],
    target: Sequence[float],
    *,
    rising: float = 0.48,
    falling: float = 0.16,
) -> list[float]:
    """Attack faster than release so the bars follow the voice without shaking."""
    fitted = _fit_levels(target, len(current))
    eased: list[float] = []
    for previous, nxt in zip(current, fitted):
        rate = rising if nxt >= previous else falling
        eased.append(previous + (nxt - previous) * rate)
    return eased


def render_frame(
    *,
    state: str,
    levels: Sequence[float],
    width: int,
    height: int,
    phase: float,
    opacity: float = 1.0,
    scale: float = 1.0,
) -> Image.Image:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if opacity <= 0 or width < 2 or height < 2:
        return image
    draw = ImageDraw.Draw(image)
    box = _content_box(width, height)
    _draw_shadow(draw, box)
    _draw_body(draw, box, state)
    if state == "transcribing":
        _draw_dots(draw, box, phase)
    elif state == "ready":
        _draw_check(draw, box, PALETTE["ready"]["mark"])
    elif state == "error":
        _draw_bang(draw, box, PALETTE["error"]["mark"])
    else:
        _draw_bars(draw, box, _fit_levels(levels, BAR_COUNT))
    if scale < 0.999:
        image = _scale_about_center(image, scale)
    if opacity < 0.999:
        image = _fade(image, opacity)
    return image


def to_premultiplied_bgra(image: Image.Image) -> bytes:
    rgba = np.asarray(image, dtype=np.uint8)
    alpha = rgba[:, :, 3:4].astype(np.uint16)
    rgb = (rgba[:, :, :3].astype(np.uint16) * alpha + 127) // 255
    bgra = np.empty_like(rgba)
    bgra[:, :, 0] = rgb[:, :, 2]
    bgra[:, :, 1] = rgb[:, :, 1]
    bgra[:, :, 2] = rgb[:, :, 0]
    bgra[:, :, 3] = rgba[:, :, 3]
    return bgra.tobytes()


def _clamp01(value: float) -> float:
    if value != value or value <= 0:
        return 0.0
    if value >= 1:
        return 1.0
    return float(value)


def _fit_levels(levels: Sequence[float], count: int) -> list[float]:
    if count <= 0:
        return []
    values = [_clamp01(float(item)) for item in levels]
    if len(values) == count:
        return values
    if not values:
        return [0.0] * count
    if len(values) == 1 or count == 1:
        return [values[0]] * count
    last = len(values) - 1
    fitted: list[float] = []
    for index in range(count):
        pos = last * index / (count - 1)
        low = int(pos)
        high = min(last, low + 1)
        frac = pos - low
        fitted.append(values[low] * (1.0 - frac) + values[high] * frac)
    return fitted


def _content_box(width: int, height: int) -> tuple[int, int, int, int]:
    pad_x = max(8, round(width * 0.055))
    pad_top = max(4, round(height * 0.10))
    pad_bottom = max(8, round(height * 0.20))
    return (pad_x, pad_top, max(pad_x + 2, width - pad_x), max(pad_top + 2, height - pad_bottom))


def _draw_shadow(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    radius = max(1, (y1 - y0) // 2)
    for spread, alpha, drop in ((6, 24, 3), (3, 36, 2)):
        draw.rounded_rectangle(
            (x0 - spread, y0 - spread + drop, x1 + spread - 1, y1 + spread + drop - 1),
            radius=radius + spread,
            fill=(0, 0, 0, alpha),
        )


def _draw_body(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], state: str) -> None:
    colors = PALETTE.get(state, PALETTE["listening"])
    x0, y0, x1, y1 = box
    radius = max(1, (y1 - y0) // 2)
    draw.rounded_rectangle(
        (x0, y0, x1 - 1, y1 - 1),
        radius=radius,
        fill=colors["fill"],
        outline=colors["border"],
        width=max(1, round((y1 - y0) * 0.035)),
    )


def _draw_bars(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], levels: Sequence[float]) -> None:
    x0, y0, x1, y1 = box
    height = max(1, y1 - y0)
    inset = max(4, round(height * 0.20))
    area_top = y0 + inset
    area_bottom = y1 - inset
    area_h = max(4, area_bottom - area_top)
    count = len(levels)
    bar_w = max(3, round(height * 0.15))
    gap = max(2, round(bar_w * 0.55))
    total = count * bar_w + max(0, count - 1) * gap
    limit = int((x1 - x0) * 0.78)
    if total > limit and count > 1:
        gap = max(1, (limit - count * bar_w) // (count - 1))
        total = count * bar_w + (count - 1) * gap
    left = x0 + max(0, (x1 - x0 - total) // 2)
    center = (area_top + area_bottom) / 2
    min_h = max(4.0, bar_w * 1.45)
    max_h = float(area_h)
    for index, level in enumerate(levels):
        amount = _clamp01(level)
        bar_h = min_h + (max_h - min_h) * amount
        bx = left + index * (bar_w + gap)
        top = center - bar_h / 2
        alpha = int(150 + 105 * amount)
        draw.rounded_rectangle(
            (bx, top, bx + bar_w - 1, top + bar_h),
            radius=bar_w / 2,
            fill=(247, 244, 238, alpha),
        )


def _draw_dots(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], phase: float) -> None:
    x0, y0, x1, y1 = box
    height = max(1, y1 - y0)
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    radius = max(2.2, height * 0.09)
    spacing = max(radius * 3.2, height * 0.38)
    for index in range(3):
        wave = math.sin(phase * 7.5 + index * 0.75)
        alpha = int(150 + 105 * (0.5 + 0.5 * wave))
        ox = (index - 1) * spacing
        oy = wave * height * 0.07
        draw.ellipse(
            (cx + ox - radius, cy + oy - radius, cx + ox + radius, cy + oy + radius),
            fill=(214, 220, 245, alpha),
        )


def _draw_check(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], color: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    height = max(1, y1 - y0)
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    size = height * 0.20
    width = max(2, round(height * 0.075))
    start = (cx - size * 1.15, cy + size * 0.05)
    mid = (cx - size * 0.25, cy + size * 0.85)
    end = (cx + size * 1.35, cy - size * 0.95)
    draw.line([start, mid, end], fill=color, width=width, joint="curve")


def _draw_bang(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], color: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    height = max(1, y1 - y0)
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    stem_w = max(3, round(height * 0.08))
    stem_h = height * 0.28
    top = cy - height * 0.24
    draw.rounded_rectangle(
        (cx - stem_w / 2, top, cx + stem_w / 2, top + stem_h),
        radius=stem_w / 2,
        fill=color,
    )
    dot_r = stem_w * 0.72
    dot_y = top + stem_h + dot_r * 1.8
    draw.ellipse((cx - dot_r, dot_y - dot_r, cx + dot_r, dot_y + dot_r), fill=color)


def _scale_about_center(image: Image.Image, scale: float) -> Image.Image:
    width, height = image.size
    scaled_w = max(1, round(width * scale))
    scaled_h = max(1, round(height * scale))
    scaled = image.resize((scaled_w, scaled_h), Image.Resampling.BILINEAR)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(scaled, ((width - scaled_w) // 2, (height - scaled_h) // 2), scaled)
    return canvas


def _fade(image: Image.Image, opacity: float) -> Image.Image:
    amount = 0.0 if opacity < 0 else 1.0 if opacity > 1 else opacity
    arr = np.array(image)
    arr[:, :, 3] = (arr[:, :, 3].astype(np.uint16) * amount).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def _monitor_work(which: str) -> tuple[tuple[int, int, int, int], int]:
    handle = _primary_monitor() if which == "primary" else _cursor_monitor()
    if not handle:
        return _fallback_work()
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        return _fallback_work()
    work = (
        int(info.rcWork.left),
        int(info.rcWork.top),
        int(info.rcWork.right),
        int(info.rcWork.bottom),
    )
    return work, _monitor_dpi(handle)


def _cursor_monitor() -> int:
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return _primary_monitor()
    return int(user32.MonitorFromPoint(point, MONITOR_DEFAULTTOPRIMARY) or 0)


def _primary_monitor() -> int:
    found: list[int] = []

    @MONITORENUMPROC
    def _visit(handle, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)) and info.dwFlags & MONITORINFOF_PRIMARY:
            found.append(int(handle))
        return True

    user32.EnumDisplayMonitors(None, None, _visit, 0)
    if found:
        return found[0]
    return int(user32.MonitorFromPoint(POINT(0, 0), MONITOR_DEFAULTTOPRIMARY) or 0)


def _monitor_dpi(handle: int) -> int:
    dpi_x = wintypes.UINT()
    dpi_y = wintypes.UINT()
    try:
        result = shcore.GetDpiForMonitor(handle, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
    except OSError:
        result = 1
    if result == 0 and dpi_x.value:
        return int(dpi_x.value)
    getter = getattr(user32, "GetDpiForSystem", None)
    if getter is not None:
        try:
            value = int(getter())
        except OSError:
            value = 0
        if value:
            return value
    return 96


def _fallback_work() -> tuple[tuple[int, int, int, int], int]:
    area = RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(area), 0)
    return (int(area.left), int(area.top), int(area.right), int(area.bottom)), 96


class _Surface:
    """A reused top-down 32-bit DIB the pill is painted into."""

    def __init__(self) -> None:
        self.hdc_screen = user32.GetDC(None)
        self.hdc_mem = gdi32.CreateCompatibleDC(self.hdc_screen) if self.hdc_screen else None
        self.hbmp = None
        self.previous = None
        self.bits = 0
        self.size = (0, 0)

    def ensure(self, width: int, height: int) -> bool:
        if self.size == (width, height) and self.bits and self.hdc_mem:
            return True
        if not self.hdc_mem:
            return False
        self._drop_bitmap()
        info = BITMAPINFOHEADER()
        info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.biWidth = width
        info.biHeight = -height
        info.biPlanes = 1
        info.biBitCount = 32
        info.biCompression = BI_RGB
        info.biSizeImage = width * height * 4
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(self.hdc_screen, ctypes.byref(info), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        if not bitmap or not bits.value:
            if bitmap:
                gdi32.DeleteObject(bitmap)
            return False
        self.hbmp = bitmap
        self.previous = gdi32.SelectObject(self.hdc_mem, bitmap)
        self.bits = int(bits.value)
        self.size = (width, height)
        return True

    def close(self) -> None:
        self._drop_bitmap()
        if self.hdc_mem:
            gdi32.DeleteDC(self.hdc_mem)
            self.hdc_mem = None
        if self.hdc_screen:
            user32.ReleaseDC(None, self.hdc_screen)
            self.hdc_screen = None

    def _drop_bitmap(self) -> None:
        if self.hbmp and self.hdc_mem and self.previous:
            gdi32.SelectObject(self.hdc_mem, self.previous)
        if self.hbmp:
            gdi32.DeleteObject(self.hbmp)
        self.hbmp = None
        self.previous = None
        self.bits = 0
        self.size = (0, 0)


class Indicator:
    def __init__(
        self,
        enabled: bool = True,
        *,
        position: str = "bottom-center",
        monitor: str = "cursor",
        scale: float = 1.0,
        level_source: Callable[[], Sequence[float]] | None = None,
    ) -> None:
        self.enabled = enabled
        self._position = position if position in POSITIONS else "bottom-center"
        self._monitor = monitor if monitor in {"cursor", "primary"} else "cursor"
        self._scale = _valid_scale(scale)
        self._level_source = level_source
        self._hwnd = 0
        self._ready = threading.Event()
        self._wndproc = WNDPROC(self._proc)
        self._thread: threading.Thread | None = None
        self._mode = MODE_LISTENING
        self._generation = 0
        self._phase = "hidden"
        self._anim = 0.0
        self._motion = 0.0
        self._last_tick = 0.0
        self._hold_until = 0.0
        self._levels = [0.0] * BAR_COUNT
        self._targets = [0.0] * BAR_COUNT
        self._origin: tuple[int, int] | None = None
        self._size = pill_pixel_size(96, self._scale)
        self._place_dirty = True
        self._visible = False
        self._timer_on = False
        self._top_tick = 0
        self._level_error = False
        self._present_error = False
        self._surface: _Surface | None = None
        if not enabled:
            self._ready.set()
            return
        self._thread = threading.Thread(target=self._run, name="dictado-indicator", daemon=True)
        self._thread.start()
        self._ready.wait(3)

    def show_listening(self, generation: int) -> None:
        self._post(MODE_LISTENING, generation)

    def show_transcribing(self, generation: int) -> None:
        self._post(MODE_TRANSCRIBING, generation)

    def show_ready(self, generation: int) -> None:
        self._post(MODE_READY, generation)

    def show_error(self, generation: int) -> None:
        self._post(MODE_ERROR, generation)

    def hide(self, generation: int) -> None:
        self._post(MODE_HIDE, generation)

    def close(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)

    def _post(self, mode: int, generation: int) -> None:
        if not self.enabled or not self._hwnd:
            return
        user32.PostMessageW(self._hwnd, WM_SET_MODE, mode, int(generation))

    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_SET_MODE:
            try:
                self._apply_mode(int(wparam), int(lparam), hwnd)
            except Exception:
                log.exception("No se pudo cambiar el indicador")
            return 0
        if msg == WM_TIMER:
            try:
                self._tick(hwnd)
            except Exception:
                log.exception("No se pudo dibujar el indicador")
            return 0
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if msg == WM_NCHITTEST:
            return HTTRANSPARENT
        if msg == WM_PAINT:
            paint = PAINTSTRUCT()
            user32.BeginPaint(hwnd, ctypes.byref(paint))
            user32.EndPaint(hwnd, ctypes.byref(paint))
            return 0
        if msg == WM_CLOSE:
            self._stop_timer(hwnd)
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            self._stop_timer(hwnd)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _apply_mode(self, mode: int, generation: int, hwnd) -> None:
        if not accepts_generation(self._generation, generation):
            return
        new_gesture = generation != self._generation or self._phase == "hidden"
        self._generation = generation
        if mode == MODE_HIDE:
            self._hold_until = 0.0
            if self._phase != "hidden":
                self._phase = "leaving"
                self._ensure_timer(hwnd)
                self._tick(hwnd)
            return
        if new_gesture:
            self._levels = [0.0] * BAR_COUNT
            self._targets = [0.0] * BAR_COUNT
            self._place_dirty = True
            self._top_tick = 0
            if self._phase == "hidden":
                self._anim = 0.0
                self._motion = 0.0
            self._phase = "appearing"
        elif self._phase == "leaving":
            self._phase = "appearing"
        self._hold_until = 0.0
        self._mode = mode
        self._ensure_timer(hwnd)
        self._tick(hwnd)

    def _tick(self, hwnd) -> None:
        now = time.perf_counter()
        dt = now - self._last_tick if self._last_tick else 0.0
        if dt < 0:
            dt = 0.0
        elif dt > 0.05:
            dt = 0.05
        self._last_tick = now
        self._motion += dt
        if self._phase == "appearing":
            self._anim = min(1.0, self._anim + (dt / APPEAR_S if APPEAR_S else 1.0))
            if self._anim >= 1.0:
                self._phase = "shown"
        if self._phase == "shown":
            self._arm_hold(now)
            if self._hold_until and now >= self._hold_until:
                self._phase = "leaving"
                self._hold_until = 0.0
        if self._phase == "leaving":
            self._anim = max(0.0, self._anim - (dt / LEAVE_S if LEAVE_S else 1.0))
            if self._anim <= 0.0:
                self._hide_now(hwnd)
                return
        if self._phase == "hidden":
            return
        if self._mode == MODE_LISTENING and self._level_source is not None:
            self._read_levels()
        self._present(hwnd)

    def _arm_hold(self, now: float) -> None:
        if self._hold_until or self._mode not in (MODE_READY, MODE_ERROR):
            return
        delay = HOLD_ERROR_S if self._mode == MODE_ERROR else HOLD_READY_S
        self._hold_until = now + delay

    def _read_levels(self) -> None:
        try:
            target = self._level_source() if self._level_source is not None else ()
        except Exception:
            if not self._level_error:
                self._level_error = True
                log.exception("No se pudieron leer los niveles")
            return
        self._targets = _fit_levels(target, BAR_COUNT)
        self._levels = smooth_levels(self._levels, self._targets)

    def _present(self, hwnd) -> None:
        if self._place_dirty or self._origin is None:
            self._origin, self._size = self._placement()
            self._place_dirty = False
        origin = self._origin
        width, height = self._size
        surface = self._surface
        if surface is None or origin is None or not surface.ensure(width, height):
            self._log_present_once("sin mapa de bits")
            return
        opacity, scale = _eased(self._anim)
        frame = render_frame(
            state=STATE_BY_MODE.get(self._mode, "listening"),
            levels=self._levels,
            width=width,
            height=height,
            phase=self._motion,
            opacity=opacity,
            scale=scale,
        )
        raw = to_premultiplied_bgra(frame)
        ctypes.memmove(surface.bits, raw, width * height * 4)
        dst = POINT(origin[0], origin[1])
        src = POINT(0, 0)
        size = SIZE(width, height)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(
            hwnd,
            surface.hdc_screen,
            ctypes.byref(dst),
            ctypes.byref(size),
            surface.hdc_mem,
            ctypes.byref(src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )
        if not ok:
            self._log_present_once(str(ctypes.get_last_error()))
            return
        self._top_tick += 1
        if self._top_tick == 1 or self._top_tick % 20 == 0:
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        if not self._visible:
            user32.ShowWindow(hwnd, SW_SHOWNA)
            self._visible = True

    def _placement(self) -> tuple[tuple[int, int], tuple[int, int]]:
        try:
            work, dpi = _monitor_work(self._monitor)
        except Exception:
            log.exception("No se pudo leer el monitor")
            work, dpi = _fallback_work()
        size = pill_pixel_size(dpi, self._scale)
        margin = max(8, round(MARGIN_PX_AT_96 * dpi / 96.0))
        return pill_origin(work, size, self._position, margin), size

    def _hide_now(self, hwnd) -> None:
        self._phase = "hidden"
        self._anim = 0.0
        self._hold_until = 0.0
        self._visible = False
        self._top_tick = 0
        user32.ShowWindow(hwnd, SW_HIDE)
        self._stop_timer(hwnd)

    def _ensure_timer(self, hwnd) -> None:
        if self._timer_on:
            return
        winmm.timeBeginPeriod(1)
        if not user32.SetTimer(hwnd, TIMER_ID, 16, None):
            winmm.timeEndPeriod(1)
            return
        self._timer_on = True
        self._last_tick = time.perf_counter()

    def _stop_timer(self, hwnd) -> None:
        if not self._timer_on:
            return
        user32.KillTimer(hwnd, TIMER_ID)
        winmm.timeEndPeriod(1)
        self._timer_on = False

    def _log_present_once(self, detail: str) -> None:
        if self._present_error:
            return
        self._present_error = True
        log.warning("No se pudo pintar la pastilla (%s)", detail)

    def _run(self) -> None:
        surface = _Surface()
        self._surface = surface
        try:
            if not surface.hdc_mem:
                log.error("No se pudo crear el indicador")
                return
            instance = kernel32.GetModuleHandleW(None)
            class_name = "DictadoLocalPill"
            window_class = WNDCLASSW()
            window_class.lpfnWndProc = self._wndproc
            window_class.hInstance = instance
            window_class.lpszClassName = class_name
            window_class.hbrBackground = None
            atom = user32.RegisterClassW(ctypes.byref(window_class))
            if not atom and ctypes.get_last_error() not in (0, 1410):
                log.error("No se pudo registrar la pastilla: %s", ctypes.get_last_error())
            hwnd = user32.CreateWindowExW(
                EXSTYLE,
                class_name,
                "Dictado",
                WS_POPUP,
                0,
                0,
                BASE_WIDTH,
                BASE_HEIGHT,
                None,
                None,
                instance,
                None,
            )
            self._hwnd = int(hwnd or 0)
            self._ready.set()
            if not hwnd:
                log.error("No se pudo crear la ventana del indicador: %s", ctypes.get_last_error())
                return
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            self._stop_timer(self._hwnd)
            surface.close()
            self._surface = None
            self._ready.set()


def _eased(anim: float) -> tuple[float, float]:
    t = 0.0 if anim < 0 else 1.0 if anim > 1 else anim
    eased = t * t * (3.0 - 2.0 * t)
    return eased, 0.90 + 0.10 * eased


def _valid_scale(scale: float) -> float:
    try:
        value = float(scale)
    except (TypeError, ValueError):
        return 1.0
    if value < 0.6 or value > 2.0:
        return 1.0
    return value
