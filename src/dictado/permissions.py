"""Permission heuristics shared by the platform layer."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class PermissionPrompt:
    """Set a tray status and point the user at the right settings panel."""

    ACCESSIBILITY_TITLE = "Falta permiso de Accesibilidad"
    MICROPHONE_TITLE = "Permiso del microfono denegado"

    def __init__(self, set_status, open_settings) -> None:
        self._set_status = set_status
        self._open_settings = open_settings

    def accessibility_missing(self) -> None:
        self._set_status(self.ACCESSIBILITY_TITLE, "#c92a2a")
        try:
            self._open_settings("accessibility")
        except Exception:
            log.exception("No se pudo abrir Ajustes del Sistema")

    def microphone_missing(self) -> None:
        self._set_status(self.MICROPHONE_TITLE, "#c92a2a")
        try:
            self._open_settings("microphone")
        except Exception:
            log.exception("No se pudo abrir Ajustes del Sistema")


def microphone_permission_denied(exc: BaseException) -> bool:
    """Heuristic: a mic open failure that looks like a system permission.

    sounddevice/PortAudio surfaces denied access as -9996 (no free device)
    only for missing devices; denial usually arrives as -9985/-9988 or a
    message mentioning permission. Anything else returns False so the
    generic error path handles it.
    """
    message = str(exc).lower()
    if "permission" in message or "denied" in message or "not allowed" in message:
        return True
    code = getattr(exc, "errcode", None) or getattr(exc, "errno", None)
    return code in {-9985, -9988}