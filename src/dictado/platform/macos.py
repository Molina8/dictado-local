"""macOS (Apple Silicon) implementation of the platform layer.

Clipboard snapshot/restore through NSPasteboard (pyobjc), paste with a Cmd+V
Quartz event and menu-bar feedback through pystray. Audio cues reuse `afplay`.
Everything degrades with a log line when a framework call fails; nothing
crashes the tray app.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import pystray

from dictado.permissions import PermissionPrompt  # noqa: F401  (re-export for app.py)

log = logging.getLogger(__name__)

AFPLAY = "/usr/bin/afplay"
TINK = "/System/Library/Sounds/Tink.aiff"

TEXT_TYPE = "public.utf8-plain-text"

#: `app.py` checks this to decide whether a mic failure can be a permission.
is_macos = True


class MacClipboardError(OSError):
    """A clipboard operation did not complete."""


# ---------------------------------------------------------------------------
# Portapapeles
# ---------------------------------------------------------------------------


def _pasteboard():
    import Cocoa

    return Cocoa.NSPasteboard.generalPasteboard()


class MacClipboardSnapshot:
    """All types of every pasteboard item, captured as raw bytes.

    The public API mirrors `dictado.clipboard_win`: `snapshot()` returns the
    saved state, `set_text(text)` swaps the clipboard, `restore(saved)` puts
    the previous contents back.
    """

    def __init__(self, items: list[list[tuple[str, bytes]]]) -> None:
        self.items = items

    def __bool__(self) -> bool:
        return bool(self.items)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MacClipboardSnapshot) and other.items == self.items


def clipboard_mac_snapshot() -> MacClipboardSnapshot:
    board = _pasteboard()
    saved: list[list[tuple[str, bytes]]] = []
    items = board.pasteboardItems()
    if items is None:
        return MacClipboardSnapshot(saved)
    for item in items:
        captured: list[tuple[str, bytes]] = []
        for uti in item.types():
            try:
                data = item.dataForType_(uti)
            except Exception as exc:  # noqa: BLE001 - foreign clipboard data
                log.debug("Tipo %s no se pudo leer: %s", uti, exc)
                continue
            if data is None:
                continue
            captured.append((str(uti), bytes(data)))
        if captured:
            saved.append(captured)
    return MacClipboardSnapshot(saved)


def clipboard_mac_restore(saved: MacClipboardSnapshot | None, delay_ms: int = 0) -> None:
    """Wait `delay_ms` for the target app to read Cmd+V, then put it all back."""
    if saved is None:
        return
    if delay_ms and delay_ms > 0:
        time.sleep(delay_ms / 1000.0)
    if not saved.items:
        return
    try:
        _restore_items(saved)
    except Exception:
        log.exception("No se pudo restaurar el portapapeles")


def _restore_items(saved: MacClipboardSnapshot) -> None:
    import Cocoa

    board = _pasteboard()
    for _attempt in range(10):
        if board.clearContents() >= 0:
            break
        time.sleep(0.02)
    written = 0
    for item in saved.items:
        payload = Cocoa.NSMutableDictionary.dictionary()
        for uti, data in item:
            nsdata = Cocoa.NSData.dataWithBytes_length_(data, len(data))
            payload[uti] = nsdata
        if not board.writeObjects_([payload]):
            log.warning("No se pudo reponer un elemento del portapapeles")
            continue
        written += 1
    if not written:
        raise MacClipboardError("El portapapeles quedo vacio tras restaurar")


def clipboard_mac_set_text(text: str) -> None:
    import Cocoa

    nsdata = Cocoa.NSData.dataWithBytes_length_(text.encode("utf-8"), len(text.encode("utf-8")))
    board = _pasteboard()
    board.clearContents()
    if not board.writeObjects_([{TEXT_TYPE: nsdata}]):
        raise MacClipboardError("writeObjects_ rechazo el texto")


def get_clipboard_text() -> str:
    return str(_pasteboard().stringForType_(TEXT_TYPE) or "")


def snapshot() -> MacClipboardSnapshot:
    return clipboard_mac_snapshot()


def set_text(text: str) -> None:
    clipboard_mac_set_text(text)


def restore(saved: MacClipboardSnapshot | None) -> None:
    clipboard_mac_restore(saved, 0)


# ---------------------------------------------------------------------------
# Pegado
# ---------------------------------------------------------------------------

V_KEYCODE = 9  # kVK_ANSI_V
CG_EVENT_TAP_HID = 0  # kCGHIDEventTap


def send_cmd_v() -> None:
    """Post a Command+V pair into the system event stream."""
    import Quartz

    down = Quartz.CGEventCreateKeyboardEvent(None, V_KEYCODE, True)
    Quartz.CGEventSetFlags(down, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(CG_EVENT_TAP_HID, down)
    time.sleep(0.02)
    up = Quartz.CGEventCreateKeyboardEvent(None, V_KEYCODE, False)
    Quartz.CGEventSetFlags(up, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(CG_EVENT_TAP_HID, up)


def foreground_window() -> int:
    """PID of the frontmost application, 0 when it cannot be read."""
    try:
        import AppKit

        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app else 0
    except Exception:
        log.exception("No se pudo leer la app en primer plano")
        return 0


def activate_pid(pid: int) -> bool:
    """Bring the app back to the front so Cmd+V lands in it."""
    if not pid:
        return False
    try:
        import AppKit

        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return False
        app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
        return True
    except Exception:
        log.exception("No se pudo activar el pid %s", pid)
        return False


def focus_window(pid: int) -> bool:
    return activate_pid(pid)


def paste_text(text: str, restore_delay_ms: int, target_pid: int | None = None) -> None:
    """Same contract as `dictado.paste.paste_text`."""
    if not text:
        return
    saved = snapshot()
    try:
        if target_pid:
            activate_pid(target_pid)
        set_text(text)
        time.sleep(0.03)
        send_cmd_v()
        time.sleep(max(restore_delay_ms, 0) / 1000)
    finally:
        try:
            restore(saved)
        except MacClipboardError:
            log.exception("No se pudo restaurar el portapapeles")


# ---------------------------------------------------------------------------
# Ajustes y permisos
# ---------------------------------------------------------------------------

SYSTEM_SETTINGS_ACCESSIBILITY = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)
SYSTEM_SETTINGS_MICROPHONE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
)


def accessibility_trusted(prompt: bool = True) -> bool:
    """True once the app is a trusted accessibility (input monitoring) client."""
    try:
        import ApplicationServices

        options = {ApplicationServices.kAXTrustedCheckOptionPrompt: prompt}
        return bool(
            ApplicationServices.AXIsProcessTrustedWithOptions(
                ApplicationServices.NSDictionary.dictionaryWithDictionary_(options)
            )
        )
    except Exception:
        log.exception("No se pudo comprobar el permiso de Accesibilidad")
        return True  # fail open: do not block dictation on a probe failure


def open_accessibility_settings() -> bool:
    return _open_url(SYSTEM_SETTINGS_ACCESSIBILITY)


def open_microphone_settings() -> bool:
    return _open_url(SYSTEM_SETTINGS_MICROPHONE)


def open_settings(which: str) -> None:
    """`which` is "accessibility" or "microphone"; used by PermissionPrompt."""
    opener = {
        "accessibility": open_accessibility_settings,
        "microphone": open_microphone_settings,
    }.get(which)
    if opener is not None:
        opener()


def _open_url(url: str) -> bool:
    try:
        subprocess.Popen(["open", url])
        return True
    except Exception:
        log.exception("No se pudo abrir %s", url)
        return False


# ---------------------------------------------------------------------------
# Autostart (LaunchAgent, best effort)
# ---------------------------------------------------------------------------


def apply_autostart(enabled: bool) -> None:
    """Write or remove ~/Library/LaunchAgents/com.molina8.dictadolocal.plist."""
    try:
        if enabled:
            _write_launch_agent()
        else:
            _delete_launch_agent()
    except Exception:
        log.exception("No se pudo actualizar el arranque con sesion")


def _launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.molina8.dictadolocal.plist"


def _launch_agent_program() -> str | None:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())
    return None


def _write_launch_agent() -> None:
    program = _launch_agent_program()
    if program is None:
        log.info("Arranque con sesion no disponible en modo desarrollo")
        return
    if _launch_agent_path().exists():
        return
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.molina8.dictadolocal</string>
    <key>ProgramArguments</key>
    <array>
        <string>{program}</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><false/>
</dict>
</plist>
"""
    path = _launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    log.info("LaunchAgent creado en %s", path)


def _delete_launch_agent() -> None:
    path = _launch_agent_path()
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# Avisos sonoros
# ---------------------------------------------------------------------------


def play(kind: str) -> None:
    sound = TINK if kind == "done" else "/System/Library/Sounds/Pop.aiff"
    try:
        subprocess.run([AFPLAY, sound], check=False, timeout=2)
    except Exception:
        return


def play_async(kind: str) -> None:
    threading.Thread(target=play, args=(kind,), name="dictado-cue", daemon=True).start()


# ---------------------------------------------------------------------------
# Abrir ficheros (historial/configuracion)
# ---------------------------------------------------------------------------


def open_path(path) -> None:
    subprocess.Popen(["open", str(path)])


# ---------------------------------------------------------------------------
# Indicador
# ---------------------------------------------------------------------------


class NullIndicator:
    """Same interface as `dictado.overlay.Indicator`, zero window.

    All feedback happens through the menu-bar icon the app owns.
    """

    def __init__(self, *args, **kwargs) -> None:
        self.enabled = True

    def show_listening(self, generation: int) -> None:
        pass

    def show_transcribing(self, generation: int) -> None:
        pass

    def show_ready(self, generation: int) -> None:
        pass

    def show_error(self, generation: int) -> None:
        pass

    def hide(self, generation: int) -> None:
        pass

    def close(self) -> None:
        pass


Indicator = NullIndicator


def start_icon(icon: pystray.Icon, setup=None) -> None:
    """Run the menu-bar icon. On darwin pystray needs the main thread."""
    icon.run(setup)


__all__ = [
    "AFPLAY",
    "MacClipboardError",
    "MacClipboardSnapshot",
    "NullIndicator",
    "SYSTEM_SETTINGS_ACCESSIBILITY",
    "SYSTEM_SETTINGS_MICROPHONE",
    "TEXT_TYPE",
    "apply_autostart",
    "accessibility_trusted",
    "activate_pid",
    "clipboard_mac_restore",
    "clipboard_mac_set_text",
    "clipboard_mac_snapshot",
    "focus_window",
    "foreground_window",
    "get_clipboard_text",
    "open_accessibility_settings",
    "open_microphone_settings",
    "open_path",
    "open_settings",
    "paste_text",
    "play",
    "play_async",
    "restore",
    "send_cmd_v",
    "set_text",
    "snapshot",
    "start_icon",
]