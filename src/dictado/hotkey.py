"""Hold-to-talk matching for a global key listener."""

from __future__ import annotations

from collections.abc import Callable

from pynput import keyboard

_ALIASES = {
    "control": "ctrl",
    "ctrl": "ctrl",
    "ctl": "ctrl",
    "win": "cmd",
    "windows": "cmd",
    "super": "cmd",
    "meta": "cmd",
    "escape": "esc",
    "return": "enter",
}


class HotkeyMatcher:
    """Track pressed keys and fire when a configured chord is held."""

    def __init__(self, spec: str, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self.required = parse_hotkey(spec)
        self._on_press = on_press
        self._on_release = on_release
        self._held: set[str] = set()
        self._active = False

    def press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        self._held.update(key_tokens(key))
        if not self._active and self.required <= self._held:
            self._active = True
            self._on_press()

    def release(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        self._held.difference_update(key_tokens(key))
        if self._active and not self.required <= self._held:
            self._active = False
            self._on_release()


def parse_hotkey(spec: str) -> frozenset[str]:
    parts = [normalize_token(part) for part in spec.replace("-", "+").split("+")]
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError("El atajo esta vacio")
    return frozenset(parts)


def normalize_token(token: str) -> str:
    cleaned = token.strip().lower().replace(" ", "")
    return _ALIASES.get(cleaned, cleaned)


def key_tokens(key: keyboard.Key | keyboard.KeyCode | None) -> set[str]:
    if key is None:
        return set()
    if isinstance(key, keyboard.KeyCode):
        tokens: set[str] = set()
        if key.char:
            tokens.add(key.char.lower())
        if key.vk is not None:
            tokens.add(f"vk{key.vk}")
        return tokens
    name = getattr(key, "name", None)
    if not name:
        return set()
    token = normalize_token(str(name))
    tokens = {token}
    if token in {"ctrl_l", "ctrl_r"}:
        tokens.add("ctrl")
    elif token in {"alt_l", "alt_r", "alt_gr"}:
        tokens.add("alt")
    elif token in {"shift_l", "shift_r"}:
        tokens.add("shift")
    elif token in {"cmd_l", "cmd_r"}:
        tokens.add("cmd")
    return tokens


def listen(matcher: HotkeyMatcher) -> keyboard.Listener:
    return keyboard.Listener(on_press=matcher.press, on_release=matcher.release)
