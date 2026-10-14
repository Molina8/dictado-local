"""HTTP mocks for the GitHub release check. Nothing here touches the network."""

from __future__ import annotations

import json
import logging
import threading
from urllib.error import URLError

import pytest

from dictado import __version__
from dictado.updates import (
    LATEST_RELEASE_URL,
    REQUEST_TIMEOUT_S,
    AvailableUpdate,
    UpdateCheckResult,
    UpdateWatcher,
    check_for_update,
    release_tag_matches,
    update_message,
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args) -> bool:
        return False


def _release(tag: str, assets: list[dict], page: str = "https://github.com/Molina8/dictado-local/releases/tag/x") -> dict:
    return {"tag_name": tag, "html_url": page, "assets": assets}


def _asset(name: str, url: str) -> dict:
    return {"name": name, "browser_download_url": url}


def _urlopen_for(payload: dict):
    seen: dict = {}

    def urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["authorization"] = request.get_header("Authorization")
        seen["user_agent"] = request.get_header("User-agent")
        return _Response(payload)

    return urlopen, seen


def test_newer_version_points_at_the_platform_asset() -> None:
    payload = _release(
        "v1.4.0",
        [
            _asset("DictadoLocal.exe", "https://example.test/DictadoLocal.exe"),
            _asset("DictadoLocal-Setup.exe", "https://example.test/DictadoLocal-Setup.exe"),
            _asset("DictadoLocal-1.4.0-macos-arm64.dmg", "https://example.test/Dictado.dmg"),
        ],
    )
    windows, seen = _urlopen_for(payload)
    result = check_for_update(current="0.2.1", platform="win32", urlopen=windows)
    assert result.ok is True
    assert result.update == AvailableUpdate("1.4.0", "https://example.test/DictadoLocal-Setup.exe")
    assert update_message(result.update.version) == "Hay una versión nueva 1.4.0"
    assert seen["url"] == LATEST_RELEASE_URL
    assert seen["timeout"] == REQUEST_TIMEOUT_S
    assert seen["authorization"] is None
    assert seen["user_agent"] == "dictado-local"

    macos, _seen = _urlopen_for(payload)
    mac = check_for_update(current="0.2.1", platform="darwin", urlopen=macos)
    assert mac.update == AvailableUpdate("1.4.0", "https://example.test/Dictado.dmg")


def test_a_single_exe_is_enough_on_windows() -> None:
    payload = _release("v2.0.0", [_asset("DictadoLocal.exe", "https://example.test/DictadoLocal.exe")])
    urlopen, _seen = _urlopen_for(payload)
    result = check_for_update(current="0.2.1", platform="win32", urlopen=urlopen)
    assert result.update == AvailableUpdate("2.0.0", "https://example.test/DictadoLocal.exe")


def test_same_version_is_not_an_update() -> None:
    urlopen, _seen = _urlopen_for(_release(f"v{__version__}", [_asset("DictadoLocal-Setup.exe", "https://example.test/s.exe")]))
    result = check_for_update(current=__version__, platform="win32", urlopen=urlopen)
    assert result == UpdateCheckResult(update=None, ok=True)


def test_older_release_is_not_an_update() -> None:
    urlopen, _seen = _urlopen_for(_release("v0.0.1", [_asset("DictadoLocal-Setup.exe", "https://example.test/s.exe")]))
    result = check_for_update(current="0.2.1", platform="win32", urlopen=urlopen)
    assert result == UpdateCheckResult(update=None, ok=True)


def test_network_error_is_logged_and_silent(caplog: pytest.LogCaptureFixture) -> None:
    def urlopen(request, timeout):
        raise URLError("timed out")

    with caplog.at_level(logging.WARNING):
        result = check_for_update(current="0.2.1", platform="win32", urlopen=urlopen)

    assert result == UpdateCheckResult(update=None, ok=False)
    assert any("actualizaciones" in record.message for record in caplog.records)


def test_missing_platform_asset_opens_the_release_page() -> None:
    page = "https://github.com/Molina8/dictado-local/releases/tag/v9.0.0"
    payload = _release("v9.0.0", [_asset("notas.zip", "https://example.test/notas.zip")], page=page)
    windows, _seen = _urlopen_for(payload)
    result = check_for_update(current="0.2.1", platform="win32", urlopen=windows)
    assert result.update == AvailableUpdate("9.0.0", page)

    macos, _seen = _urlopen_for(payload)
    mac = check_for_update(current="0.2.1", platform="darwin", urlopen=macos)
    assert mac.update == AvailableUpdate("9.0.0", page)


def test_broken_json_is_a_failed_check() -> None:
    class Broken:
        def read(self) -> bytes:
            return b"no-es-json"

        def __enter__(self) -> Broken:
            return self

        def __exit__(self, *args) -> bool:
            return False

    result = check_for_update(current="0.2.1", platform="win32", urlopen=lambda request, timeout: Broken())
    assert result == UpdateCheckResult(update=None, ok=False)


def test_release_tag_must_match_the_package_version() -> None:
    assert release_tag_matches(f"v{__version__}") is True
    assert release_tag_matches(__version__) is True
    assert release_tag_matches("v9.9.9") is False
    assert release_tag_matches("v1.0", current="1.0.0") is False


def test_watcher_reports_a_newer_release_and_repeats() -> None:
    update = AvailableUpdate("3.0.0", "https://example.test/DictadoLocal-Setup.exe")
    seen: list[AvailableUpdate] = []
    calls = []
    second = threading.Event()

    def check():
        calls.append(1)
        if len(calls) >= 2:
            second.set()
        return UpdateCheckResult(update=update, ok=True)

    watcher = UpdateWatcher(seen.append, interval_s=0.05, check=check)
    watcher.start()
    assert second.wait(2)
    watcher.stop()
    assert len(calls) >= 2
    assert seen
    assert all(item == update for item in seen)


def test_disabled_watcher_does_not_poll() -> None:
    calls: list[int] = []
    watcher = UpdateWatcher(lambda _update: None, enabled=False, interval_s=0.01, check=lambda: calls.append(1))
    watcher.start()
    threading.Event().wait(0.05)
    watcher.stop()
    assert calls == []


def test_manual_check_still_runs_when_automatic_checks_are_off() -> None:
    update = AvailableUpdate("3.0.0", "https://example.test/a.exe")
    seen: list[AvailableUpdate] = []
    watcher = UpdateWatcher(
        seen.append,
        enabled=False,
        check=lambda: UpdateCheckResult(update=update, ok=True),
    )
    result = watcher.check_once()
    assert result.update == update
    assert seen == [update]
