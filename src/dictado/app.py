"""System tray push-to-talk for local dictation."""

from __future__ import annotations

import argparse
import logging
import pathlib
import queue
import sys
import threading
from logging.handlers import RotatingFileHandler

import pystray
from PIL import Image, ImageDraw

from dictado.backends import BACKEND_MLX, select_backend
from dictado.config import Config, default_log_path, ensure_user_config, load_config
from dictado.download_model import download_best_effort, model_ready
from dictado.history import append_history, history_path, transcript_record
from dictado.hotkey import HotkeyMatcher, listen
from dictado.permissions import PermissionPrompt, microphone_permission_denied
from dictado.recorder import Microphone
from dictado.transcriber import Transcriber, cuda_available, models_for_device
from dictado.updates import AvailableUpdate, UpdateWatcher, update_message

log = logging.getLogger("dictado")

#: Same bar count the Windows pill and the recorder agree on.
BAR_COUNT = 9


def icon_image(color: str) -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((6, 6, 58, 58), fill=color)
    draw.rounded_rectangle((28, 16, 36, 36), radius=3, fill=(255, 255, 255, 255))
    draw.arc((22, 30, 42, 50), 20, 160, fill=(255, 255, 255, 255), width=3)
    return image


class DictadoApp:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.platform = _platform()
        self.transcriber = Transcriber(config)
        self.mic = Microphone(
            sample_rate=config.sample_rate,
            device=config.input_device,
            keep_open=config.keep_mic_open,
            pre_roll_ms=config.pre_roll_ms,
            level_bars=BAR_COUNT,
        )
        self.indicator = self.platform.Indicator(
            config.indicator,
            position=config.indicator_position,
            monitor=config.indicator_monitor,
            scale=config.indicator_scale,
            level_source=self.mic.levels,
        )
        self._permission = PermissionPrompt(self._set_status, self.platform.open_settings)
        self._jobs: queue.Queue = queue.Queue()
        self._state = threading.Lock()
        self._generation = 0
        self._recording = False
        self._target = 0
        self._ready = False
        self._status = "Cargando el modelo..."
        self._last_text = ""
        self._limit: threading.Timer | None = None
        self._listener = None
        self._icon: pystray.Icon | None = None
        self._available: AvailableUpdate | None = None
        self._updates = UpdateWatcher(self._on_available_update, enabled=self.config.check_updates)
        self._worker = threading.Thread(target=self._work, name="dictado-worker", daemon=True)

    def run(self) -> None:
        self._configure_logging()
        log.info("Arranque. Atajo %s. Ejecutable %s.", self.config.hotkey, sys.executable)
        self._check_accessibility()
        self._sync_autostart()
        if self.config.keep_mic_open:
            try:
                self.mic.open()
            except Exception as exc:
                if getattr(self.platform, "is_macos", False) and microphone_permission_denied(exc):
                    self._permission.microphone_missing()
                else:
                    log.exception("No se pudo abrir el microfono")
                self._status = "Sin microfono"
        self._worker.start()
        threading.Thread(target=self._load_model, name="dictado-model", daemon=True).start()
        matcher = HotkeyMatcher(self.config.hotkey, self._on_press, self._on_release)
        self._listener = listen(matcher)
        self._listener.start()
        self._icon = pystray.Icon(
            "dictado-local",
            icon_image("#5b616b"),
            "Dictado local",
            menu=pystray.Menu(
                pystray.MenuItem(lambda _: self._status, lambda: None, enabled=False),
                pystray.MenuItem(lambda _: f"Atajo: {self.config.hotkey}", lambda: None, enabled=False),
                pystray.MenuItem(lambda _: self._last_line(), lambda: None, enabled=False),
                pystray.MenuItem("Abrir historial", self._open_history),
                pystray.MenuItem("Abrir configuracion", self._open_config),
                pystray.MenuItem(
                    lambda _: self._update_menu_label(),
                    self._open_update,
                    visible=lambda _: self._available is not None,
                ),
                pystray.MenuItem("Buscar actualizaciones", self._search_updates),
                pystray.MenuItem("Salir", self._quit),
            ),
        )
        self.platform.start_icon(self._icon, self._on_icon_ready)

    def _configure_logging(self) -> None:
        path = default_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        file_handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.handlers.clear()
        root.addHandler(file_handler)
        if sys.stderr is not None:
            stream = logging.StreamHandler()
            stream.setFormatter(formatter)
            root.addHandler(stream)

    def _check_accessibility(self) -> None:
        checker = getattr(self.platform, "accessibility_trusted", None)
        if checker is None or checker(prompt=True):
            return
        self._permission.accessibility_missing()

    def _sync_autostart(self) -> None:
        if not getattr(sys, "frozen", False):
            return
        try:
            self.platform.apply_autostart(bool(self.config.start_with_windows))
        except Exception:
            log.exception("No se pudo actualizar el arranque automatico")
            return
        log.info("Arranque automatico: %s", bool(self.config.start_with_windows))

    def _load_model(self) -> None:
        try:
            self._ensure_models()
            self.transcriber.load()
            self.transcriber.warmup()
        except FileNotFoundError as exc:
            self._set_status("Falta el modelo", "#5b616b")
            log.error("%s", exc)
            return
        except Exception:
            self._set_status("El modelo no cargo", "#5b616b")
            log.exception("No se pudo cargar el modelo")
            return
        self._ready = True
        self._set_status(
            f"Listo ({self.transcriber.model_name}, {self.transcriber.device})",
            "#2f9e44",
        )
        log.info(
            "Modelo listo: %s en %s/%s",
            self.transcriber.model_name,
            self.transcriber.device,
            self.transcriber.compute_type,
        )

    def _ensure_models(self) -> None:
        wanted = models_for_device(self.config, self._cuda_ok())
        missing = [name for name in wanted if name and not model_ready(self.config.model_path(name))]
        if not missing:
            return
        self._set_status("Descargando el modelo...", "#1971c2")
        log.info("Faltan modelos %s. Se descargan una vez.", ", ".join(missing))
        download_best_effort(missing, self.config.resolved_model_dir())
        ready = [name for name in wanted if model_ready(self.config.model_path(name))]
        if not ready:
            raise RuntimeError("No se pudo descargar ningun modelo (" + ", ".join(missing) + ")")
        if len(ready) < len(wanted):
            log.warning("Solo quedaron listos: %s", ", ".join(ready))

    def _cuda_ok(self) -> bool:
        # Only the CUDA path probes ctranslate2; darwin is mlx or CPU int8.
        if select_backend(self.config) == BACKEND_MLX:
            return False
        return cuda_available()

    def _set_status(self, text: str, color: str | None = None) -> None:
        self._status = text
        if self._icon is None:
            return
        self._icon.title = text
        if color:
            self._icon.icon = icon_image(color)

    def _paint(self, color: str) -> None:
        if self._icon is not None:
            self._icon.icon = icon_image(color)

    def _last_line(self) -> str:
        if not self._last_text:
            return "Sin transcripciones"
        text = self._last_text.replace("\n", " ")
        if len(text) > 80:
            text = text[:77] + "..."
        return f"Ultima: {text}"

    def _open_history(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        path = history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")
        self.platform.open_path(path)

    def _open_config(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self.platform.open_path(ensure_user_config())

    def _on_icon_ready(self, icon: pystray.Icon) -> None:
        # A custom setup replaces the one pystray uses to show the icon.
        icon.visible = True
        self._updates.start()

    def _update_menu_label(self) -> str:
        update = self._available
        if update is None:
            return "Hay una versión nueva"
        return update_message(update.version)

    def _on_available_update(self, update: AvailableUpdate) -> None:
        self._available = update
        log.info("Version nueva %s: %s", update.version, update.url)
        self._notify(update_message(update.version))
        # Windows and macOS snapshot the menu. Rebuild it so the new item shows.
        icon = self._icon
        if icon is None:
            return
        try:
            self.platform.refresh_menu(icon)
        except Exception:
            log.info("No se pudo refrescar el menu de actualizaciones")

    def _search_updates(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        threading.Thread(
            target=self._manual_update_check,
            name="dictado-update-now",
            daemon=True,
        ).start()

    def _manual_update_check(self) -> None:
        result = self._updates.check_once()
        if result.update is None and result.ok:
            self._notify("No hay una versión nueva")

    def _open_update(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        update = self._available
        if update is None:
            return
        try:
            self.platform.open_url(update.url)
        except Exception:
            log.exception("No se pudo abrir la descarga %s", update.url)

    def _notify(self, message: str) -> None:
        icon = self._icon
        if icon is None:
            log.info("%s", message)
            return
        try:
            icon.notify(message, "Dictado local")
        except Exception:
            log.info("Aviso de bandeja no disponible: %s", message)

    def _on_press(self) -> None:
        if not self._ready:
            log.info("Atajo ignorado: %s. Si falta el modelo, se intenta descargar al arrancar.", self._status)
            return
        target = self.platform.foreground_window()
        with self._state:
            if self._recording:
                return
            self._generation += 1
            generation = self._generation
            self._recording = True
            self._target = target
        try:
            self.mic.start()
        except Exception as exc:
            log.exception("No se pudo grabar")
            with self._state:
                self._recording = False
            self.indicator.show_error(generation)
            if getattr(self.platform, "is_macos", False) and microphone_permission_denied(exc):
                self._permission.microphone_missing()
            return
        self.indicator.show_listening(generation)
        self._paint("#c92a2a")
        if self.config.sound:
            self.platform.play_async("record")
        self._arm_limit(generation)
        log.info("Grabando (gen %s, destino %s)", generation, target)

    def _arm_limit(self, generation: int) -> None:
        if self._limit is not None:
            self._limit.cancel()
        timer = threading.Timer(self.config.max_record_s, self._hit_limit, args=(generation,))
        timer.daemon = True
        self._limit = timer
        timer.start()

    def _hit_limit(self, generation: int) -> None:
        with self._state:
            if not self._recording or generation != self._generation:
                return
        log.info("Tope de grabacion (%ss)", self.config.max_record_s)
        self._on_release()

    def _on_release(self) -> None:
        with self._state:
            if not self._recording:
                return
            self._recording = False
            generation = self._generation
            target = self._target
        if self._limit is not None:
            self._limit.cancel()
            self._limit = None
        audio = self.mic.stop()
        duration_ms = (len(audio) * 1000 / self.config.sample_rate) if self.config.sample_rate else 0
        if duration_ms < self.config.min_record_ms:
            log.info("Grabacion corta (%.0f ms), se ignora", duration_ms)
            self.indicator.hide(generation)
            self._paint("#2f9e44")
            return
        self.indicator.show_transcribing(generation)
        self._paint("#e67700")
        if self.config.sound:
            self.platform.play_async("done")
        self._jobs.put((generation, target, audio))

    def _work(self) -> None:
        while True:
            item = self._jobs.get()
            if item is None:
                return
            generation, target, audio = item
            failed = False
            has_text = False
            try:
                transcript = self.transcriber.transcribe(audio)
                log.info(
                    "Texto %s caracteres, idioma %s, audio %.2fs",
                    len(transcript.text),
                    transcript.language,
                    transcript.duration_s,
                )
                if transcript.text:
                    has_text = True
                    self._last_text = transcript.text
                    if self.config.history:
                        self._remember(transcript)
                    self.platform.paste_text(
                        transcript.text,
                        self.config.paste_restore_delay_ms,
                        target or None,
                    )
            except Exception:
                failed = True
                log.exception("Fallo al transcribir o pegar")
            finally:
                with self._state:
                    current = self._generation
                    recording = self._recording
                if generation == current and not recording:
                    if failed:
                        self.indicator.show_error(generation)
                    elif has_text:
                        self.indicator.show_ready(generation)
                    else:
                        self.indicator.hide(generation)
                    self._paint("#2f9e44")

    def _remember(self, transcript) -> None:
        try:
            append_history(
                transcript_record(
                    text=transcript.text,
                    language=transcript.language,
                    duration_s=transcript.duration_s,
                    model=transcript.model,
                    device=transcript.device,
                )
            )
        except Exception:
            log.exception("No se pudo guardar el historial")

    def _quit(self, icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        log.info("Saliendo")
        self._updates.stop()
        if self._limit is not None:
            self._limit.cancel()
        if self._listener is not None:
            self._listener.stop()
        self._jobs.put(None)
        try:
            self.mic.close()
        except Exception:
            log.exception("Al cerrar el microfono")
        self.indicator.close()
        icon.stop()


def _platform():
    from dictado.platform import get_platform

    return get_platform()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dictado", description="Dictado local push-to-talk")
    parser.add_argument("--config", default=None, help="Ruta a un config.yaml")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Comprueba import de plataforma y backend; sale con 0",
    )
    args = parser.parse_args(argv)
    config = load_config(pathlib.Path(args.config) if args.config else None)
    if args.selftest:
        _platform()
        print("selftest ok:", select_backend(config), flush=True)
        return
    DictadoApp(config).run()


if __name__ == "__main__":
    main()
