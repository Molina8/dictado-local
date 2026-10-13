import ctypes

import numpy as np

from dictado.clipboard_win import get_text, restore, set_text, snapshot
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
