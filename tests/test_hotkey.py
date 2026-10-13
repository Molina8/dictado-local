from pynput.keyboard import Key, KeyCode

from dictado.hotkey import HotkeyMatcher, parse_hotkey


def test_hold_and_release_right_control() -> None:
    events: list[str] = []
    matcher = HotkeyMatcher("ctrl_r", lambda: events.append("down"), lambda: events.append("up"))
    matcher.press(Key.ctrl_r)
    matcher.press(Key.ctrl_r)
    matcher.release(Key.ctrl_r)
    assert events == ["down", "up"]


def test_generic_ctrl_matches_either_side() -> None:
    events: list[str] = []
    matcher = HotkeyMatcher("ctrl", lambda: events.append("down"), lambda: events.append("up"))
    matcher.press(Key.ctrl_l)
    matcher.release(Key.ctrl_l)
    matcher.press(Key.ctrl_r)
    matcher.release(Key.ctrl_r)
    assert events == ["down", "up", "down", "up"]


def test_right_ctrl_ignores_the_left_key() -> None:
    events: list[str] = []
    matcher = HotkeyMatcher("ctrl_r", lambda: events.append("down"), lambda: events.append("up"))
    matcher.press(Key.ctrl_l)
    matcher.release(Key.ctrl_l)
    assert events == []


def test_chord_waits_for_every_key() -> None:
    events: list[str] = []
    matcher = HotkeyMatcher("ctrl+shift", lambda: events.append("down"), lambda: events.append("up"))
    matcher.press(Key.ctrl_l)
    assert events == []
    matcher.press(Key.shift_r)
    matcher.release(Key.ctrl_l)
    assert events == ["down", "up"]


def test_letter_uses_the_character() -> None:
    events: list[str] = []
    matcher = HotkeyMatcher("ctrl+a", lambda: events.append("down"), lambda: events.append("up"))
    matcher.press(Key.ctrl_l)
    matcher.press(KeyCode.from_char("A"))
    matcher.release(KeyCode.from_char("A"))
    assert events == ["down", "up"]
    assert parse_hotkey("control") == frozenset({"ctrl"})
    assert parse_hotkey("a") == frozenset({"a"})
