"""get_platform() picks the right implementation without importing the other.

The Windows module binds ctypes.WinDLL at module level and the macOS module
imports pyobjc lazily inside functions; a wrong pick would raise at import.
These tests monkeypatch sys.platform so both paths execute off-platform.
"""

import importlib
import sys

import pytest

from dictado.platform import get_platform

MODULES = {
    "win32": "dictado.platform.windows",
    "darwin": "dictado.platform.macos",
}


def _fresh(monkeypatch, name: str):
    # Outside the module's real platform, pystray's own backend would try to
    # open a GUI stack; the dummy backend keeps the import observable.
    monkeypatch.setenv("PYSTRAY_BACKEND", "dummy")
    sys.modules.pop(MODULES[name], None)
    monkeypatch.setattr(sys, "platform", name, raising=False)
    return importlib.import_module(MODULES[name])


def test_windows_module_exposes_the_same_names(monkeypatch) -> None:
    if sys.platform != "win32":
        pytest.skip("the real user32 bindings only exist on Windows")
    module = _fresh(monkeypatch, "win32")
    assert module.paste_text and module.foreground_window and module.focus_window
    assert module.Indicator and module.apply_autostart and module.play_async
    assert module.open_path and module.start_icon and module.open_settings
    assert module.is_macos is False


def test_macos_module_exposes_the_same_names(monkeypatch) -> None:
    if sys.platform == "win32":
        pytest.skip("this machine is Windows; the darwin path is covered by the unit stubs")
    module = _fresh(monkeypatch, "darwin")
    assert module.paste_text and module.foreground_window and module.focus_window
    assert module.Indicator and module.apply_autostart and module.play_async
    assert module.open_path and module.start_icon and module.open_settings
    assert module.is_macos is True


def test_selecting_the_wrong_platform_module_raises_cleanly(monkeypatch) -> None:
    """get_platform() with a stubbed platform still resolves a module."""
    from dictado.platform import _cache

    for name in MODULES.values():
        monkeypatch.delitem(_cache, name, raising=False)
        sys.modules.pop(name, None)

    # A module that is never importable (neither win32 nor darwin) must fail
    # with NotImplementedError, not with a half-initialised import of the
    # wrong native bindings.
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    with pytest.raises(NotImplementedError):
        get_platform()


def test_platform_cache_returns_one_module(monkeypatch) -> None:
    if sys.platform not in MODULES:
        pytest.skip("sin implementacion nativa en esta maquina")

    from dictado.platform import _cache

    name = MODULES[sys.platform]
    monkeypatch.delitem(_cache, name, raising=False)
    sys.modules.pop(name, None)
    first = get_platform()
    second = get_platform()
    assert first is second