"""Best-effort check for a newer GitHub release.

The request goes out without a token, times out quickly, and any failure is
logged. Nothing is downloaded or installed.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import urllib.request
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

from dictado import __version__

log = logging.getLogger("dictado.updates")

LATEST_RELEASE_URL = "https://api.github.com/repos/Molina8/dictado-local/releases/latest"
LATEST_RELEASE_PAGE = "https://github.com/Molina8/dictado-local/releases/latest"
REQUEST_TIMEOUT_S = 5
CHECK_INTERVAL_S = 24 * 60 * 60

_ASSET_SUFFIX = {
    "win32": ".exe",
    "darwin": ".dmg",
}


@dataclass(frozen=True)
class AvailableUpdate:
    """A release newer than the running build."""

    version: str
    url: str


@dataclass(frozen=True)
class UpdateCheckResult:
    """`ok` is false when the request or the payload could not be used."""

    update: AvailableUpdate | None
    ok: bool


def update_message(version: str) -> str:
    return f"Hay una versión nueva {version}"


def release_tag_matches(tag: str, current: str | None = None) -> bool:
    """True when a release tag is the same string as ``dictado.__version__``.

    The leading ``v`` is ignored. ``1.0`` and ``1.0.0`` do not match.
    """

    text = tag.strip()
    bare = text[1:] if text[:1] in {"v", "V"} else text
    return bare == (__version__ if current is None else current)


def check_for_update(
    *,
    current: str | None = None,
    platform: str | None = None,
    urlopen=urllib.request.urlopen,
    url: str = LATEST_RELEASE_URL,
    timeout: float = REQUEST_TIMEOUT_S,
) -> UpdateCheckResult:
    """Return a newer release, or an empty result when nothing should be shown."""

    running = __version__ if current is None else current
    system = sys.platform if platform is None else platform
    payload = _fetch_latest(urlopen, url, timeout)
    if payload is None:
        return UpdateCheckResult(update=None, ok=False)
    return _describe(payload, running, system)


class UpdateWatcher:
    """Calls `on_update` from a daemon thread while the app stays open.

    The first check runs as soon as `start` is called. Later checks wait
    `interval_s` (24 h in the app). `check_once` is the manual menu action
    and still works when automatic checks are off.
    """

    def __init__(
        self,
        on_update,
        *,
        enabled: bool = True,
        interval_s: float = CHECK_INTERVAL_S,
        check=check_for_update,
    ) -> None:
        self._on_update = on_update
        self.enabled = enabled
        self.interval_s = interval_s
        self._check = check
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="dictado-updates", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def check_once(self) -> UpdateCheckResult:
        with self._lock:
            try:
                result = self._check()
            except Exception:
                log.warning("No se pudo comprobar actualizaciones", exc_info=True)
                return UpdateCheckResult(update=None, ok=False)
        if result.update is not None:
            self._on_update(result.update)
        return result

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:
                log.warning("No se pudo comprobar actualizaciones", exc_info=True)
            if self._stop.wait(self.interval_s):
                return


def _fetch_latest(urlopen, url: str, timeout: float) -> dict | None:
    # GitHub rejects calls without a User-Agent. No Authorization header:
    # the check stays anonymous on purpose.
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "dictado-local",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except Exception as exc:
        log.warning("No se pudo comprobar actualizaciones: %s", exc)
        return None
    if isinstance(raw, str):
        text = raw
    else:
        text = bytes(raw).decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("La respuesta de actualizaciones no es JSON: %s", exc)
        return None
    if not isinstance(payload, dict):
        log.warning("La respuesta de actualizaciones no es un objeto")
        return None
    return payload


def _describe(payload: dict, current: str, platform: str) -> UpdateCheckResult:
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        log.warning("La release no trae tag_name")
        return UpdateCheckResult(update=None, ok=False)
    text = tag.strip()
    bare = text[1:] if text[:1] in {"v", "V"} else text
    try:
        remote = Version(bare)
        local = Version(current)
    except InvalidVersion as exc:
        log.warning("No se pudo comparar %s con %s: %s", bare, current, exc)
        return UpdateCheckResult(update=None, ok=False)
    if remote <= local:
        return UpdateCheckResult(update=None, ok=True)
    page = payload.get("html_url")
    page_url = page if isinstance(page, str) and page else LATEST_RELEASE_PAGE
    download = _asset_url(payload.get("assets"), platform) or page_url
    return UpdateCheckResult(update=AvailableUpdate(version=bare, url=download), ok=True)


def _asset_url(assets: object, platform: str) -> str | None:
    suffix = _ASSET_SUFFIX.get(platform)
    if suffix is None or not isinstance(assets, list):
        return None
    matches: list[tuple[str, str]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str) or not url:
            continue
        if name.lower().endswith(suffix):
            matches.append((name, url))
    if not matches:
        return None
    # Windows publishes the installer next to other .exe files. Prefer it.
    for name, url in matches:
        if "setup" in name.lower():
            return url
    return matches[0][1]
