"""System tray push-to-talk for local dictation."""

from __future__ import annotations

import argparse
import logging
import os
import queue
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from dictado.autostart import apply_autostart
from dictado.config import Config, default_log_path, ensure_user_config, load_config
from dictado.cues import play_async
from dictado.download_model import download_best_effort, model_ready
from dictado.history import append_history, history_path, transcript_record
from dictado.hotkey import HotkeyMatcher, listen
from dictado.overlay import BAR_COUNT, Indicator
from dictado.paste import foreground_window, paste_text
from dictado.recorder import Microphone
from dictado.transcriber import Transcriber, cuda_available, models_for_device

log = logging.getLogger("dictado")


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
        self.transcriber = Transcriber(config)
        self.mic = Microphone(
            sample_rate=config.sample_rate,
            device=config.input_device,
            keep_open=config.keep_mic_open,
            pre_roll_ms=config.pre_roll_ms,
            level_bars=BAR_COUNT,
        )
        self.indicator = Indicator(
            config.indicator,
            position=config.indicator_position,
            monitor=config.indicator_monitor,
            scale=config.indicator_scale,
            level_source=self.mic.levels,
        )
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
        self._worker = threading.Thread(target=self._work, name="dictado-worker", daemon=True)

    def run(self) -> None:
        self._configure_logging()
        log.info("Arranque. Atajo %s. Ejecutable %s.", self.config.hotkey, sys.executable)
        self._sync_autostart()
        if self.config.keep_mic_open:
            try:
                self.mic.open()
            except Exception:
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
                pystray.MenuItem("Salir", self._quit),
            ),
        )
        self._icon.run()

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

    def _sync_autostart(self) -> None:
        if not getattr(sys, "frozen", False):
            return
        try:
            apply_autostart(bool(self.config.start_with_windows))
        except Exception:
            log.exception("No se pudo actualizar el arranque con Windows")
            return
        log.info("Arranque con Windows: %s", bool(self.config.start_with_windows))

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
        wanted = models_for_device(self.config, cuda_available())
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
        os.startfile(path)  # type: ignore[attr-defined]

    def _open_config(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        os.startfile(ensure_user_config())  # type: ignore[attr-defined]

    def _on_press(self) -> None:
        if not self._ready:
            log.info("Atajo ignorado: %s. Si falta el modelo, se intenta descargar al arrancar.", self._status)
            return
        hwnd = foreground_window()
        with self._state:
            if self._recording:
                return
            self._generation += 1
            generation = self._generation
            self._recording = True
            self._target = hwnd
        try:
            self.mic.start()
        except Exception:
            log.exception("No se pudo grabar")
            with self._state:
                self._recording = False
            self.indicator.show_error(generation)
            return
        self.indicator.show_listening(generation)
        self._paint("#c92a2a")
        if self.config.sound:
            play_async("record")
        self._arm_limit(generation)
        log.info("Grabando (gen %s, hwnd %s)", generation, hwnd)

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
            hwnd = self._target
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
            play_async("done")
        self._jobs.put((generation, hwnd, audio))

    def _work(self) -> None:
        while True:
            item = self._jobs.get()
            if item is None:
                return
            generation, hwnd, audio = item
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
                    paste_text(transcript.text, self.config.paste_restore_delay_ms, hwnd or None)
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dictado", description="Dictado local push-to-talk")
    parser.add_argument("--config", default=None, help="Ruta a un config.yaml")
    args = parser.parse_args(argv)
    config = load_config(Path(args.config) if args.config else None)
    DictadoApp(config).run()


if __name__ == "__main__":
    main()
