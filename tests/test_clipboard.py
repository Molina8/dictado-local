import ctypes

import numpy as np

from dictado.clipboard_win import (
    CF_BITMAP,
    CF_DIB,
    CF_DIBV5,
    CF_ENHMETAFILE,
    CF_HDROP,
    CF_METAFILEPICT,
    CF_PALETTE,
    CF_UNICODETEXT,
    MAX_CLIPBOARD_FORMAT_BYTES,
    accept_clipboard_format,
    allowed_hglobal_formats,
    get_text,
    restore,
    set_text,
    snapshot,
)
from dictado.paste import INPUT
from dictado.recorder import Microphone


def test_text_roundtrip_restores_the_previous_clipboard() -> None:
    original = snapshot()
    try:
        set_text("dictado-prueba-áéí")
        assert get_text() == "dictado-prueba-áéí"
        set_text("otro")
        assert get_text() == "otro"
    finally:
        restore(original)


def test_only_hglobal_whitelist_is_captured() -> None:
    allowed = allowed_hglobal_formats()
    for fmt in (CF_BITMAP, CF_METAFILEPICT, CF_PALETTE, CF_ENHMETAFILE):
        assert fmt not in allowed
        assert accept_clipboard_format(fmt, 64, allowed) is False
    for fmt in (CF_UNICODETEXT, CF_DIB, CF_DIBV5, CF_HDROP):
        assert fmt in allowed
        assert accept_clipboard_format(fmt, 64, allowed) is True
    assert accept_clipboard_format(CF_DIB, MAX_CLIPBOARD_FORMAT_BYTES, allowed) is True
    assert accept_clipboard_format(CF_DIB, MAX_CLIPBOARD_FORMAT_BYTES + 1, allowed) is False
    html = int(ctypes.windll.user32.RegisterClipboardFormatW("HTML Format"))
    rtf = int(ctypes.windll.user32.RegisterClipboardFormatW("Rich Text Format"))
    assert html in allowed
    assert rtf in allowed


def test_restore_skips_bitmap_handles() -> None:
    original = snapshot()
    try:
        saved = {CF_UNICODETEXT: "sigue".encode("utf-16-le") + b"\x00\x00", CF_BITMAP: b"no-es-hglobal"}
        restore(saved)
        assert get_text() == "sigue"
        assert ctypes.windll.user32.IsClipboardFormatAvailable(CF_BITMAP) == 0
        found = snapshot()
        assert CF_BITMAP not in found
        assert set(found) <= allowed_hglobal_formats()
    finally:
        restore(original)


def test_sendinput_struct_matches_the_64_bit_layout() -> None:
    assert ctypes.sizeof(ctypes.c_void_p) == 8
    assert ctypes.sizeof(INPUT) == 40


def test_stop_keeps_the_preroll() -> None:
    mic = Microphone(sample_rate=16000, keep_open=True, pre_roll_ms=100)
    mic._stream = object()
    chunk = np.full((1600, 1), 0.25, dtype=np.float32)
    mic._on_audio(chunk, 1600, None, None)
    mic.start()
    mic._on_audio(np.full((800, 1), 0.5, dtype=np.float32), 800, None, None)
    audio = mic.stop()
    assert audio.shape == (2400,)
    assert audio[0] == np.float32(0.25)
    assert audio[-1] == np.float32(0.5)
