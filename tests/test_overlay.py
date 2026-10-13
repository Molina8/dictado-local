import inspect
import time

import numpy as np
from PIL import Image

from dictado.overlay import (
    BAR_COUNT,
    BASE_HEIGHT,
    BASE_WIDTH,
    EXSTYLE,
    POSITIONS,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
    accepts_generation,
    pill_origin,
    pill_pixel_size,
    render_frame,
    smooth_levels,
    to_premultiplied_bgra,
)
from dictado.recorder import LEVEL_BARS, Microphone, chunk_levels


def test_bar_count_matches_the_microphone() -> None:
    assert BAR_COUNT == LEVEL_BARS
    assert len(POSITIONS) == 4
    default = inspect.signature(Microphone.__init__).parameters["level_bars"].default
    assert default == BAR_COUNT


def test_older_gesture_is_ignored() -> None:
    assert accepts_generation(4, 4)
    assert accepts_generation(4, 5)
    assert not accepts_generation(4, 3)


def test_overlay_style_stays_click_through() -> None:
    assert EXSTYLE & WS_EX_TRANSPARENT
    assert EXSTYLE & WS_EX_NOACTIVATE
    assert EXSTYLE & WS_EX_TOOLWINDOW
    assert EXSTYLE & WS_EX_TOPMOST
    assert EXSTYLE & WS_EX_LAYERED


def test_pill_size_follows_dpi_and_scale() -> None:
    base = pill_pixel_size(96, 1)
    assert base == (BASE_WIDTH, BASE_HEIGHT)
    assert pill_pixel_size(192, 1) == (BASE_WIDTH * 2, BASE_HEIGHT * 2)
    assert pill_pixel_size(96, 2) == (BASE_WIDTH * 2, BASE_HEIGHT * 2)


def test_pill_sits_on_the_requested_edge() -> None:
    work = (0, 0, 1920, 1080)
    size = (160, 40)
    assert pill_origin(work, size, "bottom-center", 32) == ((1920 - 160) // 2, 1080 - 40 - 32)
    assert pill_origin(work, size, "bottom-left", 32) == (32, 1080 - 40 - 32)
    assert pill_origin(work, size, "bottom-right", 32) == (1920 - 160 - 32, 1080 - 40 - 32)
    assert pill_origin(work, size, "top-center", 32) == ((1920 - 160) // 2, 32)


def test_pill_uses_the_monitor_origin_even_when_it_is_negative() -> None:
    work = (-1920, 0, 0, 1080)
    size = (100, 40)
    x, y = pill_origin(work, size, "bottom-center", 32)
    assert x == -1920 + (1920 - 100) // 2
    assert y == 1080 - 40 - 32


def test_pill_stays_inside_a_small_work_area() -> None:
    work = (10, 20, 400, 300)
    size = (500, 400)
    for position in POSITIONS:
        x, y = pill_origin(work, size, position, 16)
        assert x == 10
        assert y == 20


def test_levels_rise_quickly_and_fall_slowly() -> None:
    rising = smooth_levels([0.0], [1.0])
    falling = smooth_levels([1.0], [0.0])
    assert rising[0] > 1.0 - falling[0]
    stepped = [0.2]
    stepped = smooth_levels(stepped, [0.5])
    assert 0.2 < stepped[0] < 0.5
    value = [0.0]
    for _ in range(8):
        value = smooth_levels(value, [1.0])
    assert value[0] > 0.9
    value = [1.0]
    for _ in range(90):
        value = smooth_levels(value, [0.0])
    assert 0 <= value[0] < 0.05


def test_chunk_levels_follow_loudness_and_shape() -> None:
    assert chunk_levels(np.zeros(1600, dtype=np.float32)) == tuple(0.0 for _ in range(BAR_COUNT))
    quiet = chunk_levels(np.full(1600, 0.001, dtype=np.float32))
    loud = chunk_levels(np.full(1800, 0.2, dtype=np.float32))
    assert sum(quiet) == 0
    assert sum(loud) > 1
    assert all(0 <= item <= 1 for item in loud)
    shaped = np.zeros(900, dtype=np.float32)
    shaped[:100] = 0.4
    levels = chunk_levels(shaped)
    assert levels[0] > levels[-1]


def test_premultiply_scales_color_by_alpha() -> None:
    image = Image.new("RGBA", (1, 1), (255, 0, 0, 128))
    assert list(to_premultiplied_bgra(image)) == [0, 0, 128, 128]


def test_frames_show_distinct_states() -> None:
    common = {"width": 172, "height": 50, "phase": 0.2, "opacity": 1.0, "scale": 1.0}
    quiet = render_frame(state="listening", levels=[0.0] * BAR_COUNT, **common)
    loud = render_frame(state="listening", levels=[1.0] * BAR_COUNT, **common)
    dots = render_frame(state="transcribing", levels=[0.0] * BAR_COUNT, **common)
    ready = render_frame(state="ready", levels=[0.0] * BAR_COUNT, **common)
    error = render_frame(state="error", levels=[0.0] * BAR_COUNT, **common)
    blank = render_frame(state="listening", levels=[1.0] * BAR_COUNT, opacity=0, width=172, height=50, phase=0)
    assert quiet.getpixel((0, 0))[3] == 0
    assert quiet.getpixel((22, 22))[3] > 180
    assert _bright_pixels(loud) > _bright_pixels(quiet)
    pictures = {frame.tobytes() for frame in (quiet, dots, ready, error)}
    assert len(pictures) == 4
    assert int(np.asarray(blank)[:, :, 3].max()) == 0
    shrunk = render_frame(state="listening", levels=[1.0] * BAR_COUNT, width=172, height=50, phase=0, opacity=1, scale=0.8)
    assert shrunk.tobytes() != loud.tobytes()


def test_render_stays_cheap_enough_for_60fps() -> None:
    levels = [0.2, 0.8, 0.4, 1.0, 0.6, 0.3, 0.9, 0.5, 0.15]
    started = time.perf_counter()
    for index in range(60):
        render_frame(
            state="listening" if index % 2 == 0 else "transcribing",
            levels=levels,
            width=344,
            height=100,
            phase=index / 60,
            opacity=1,
            scale=1,
        )
    elapsed = time.perf_counter() - started
    assert elapsed < 0.6


def _bright_pixels(image: Image.Image) -> int:
    data = np.asarray(image)
    mask = (data[:, :, 0] > 200) & (data[:, :, 1] > 200) & (data[:, :, 2] > 190) & (data[:, :, 3] > 80)
    return int(mask.sum())
