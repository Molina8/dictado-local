"""System tray push-to-talk for local dictation."""

from __future__ import annotations

import argparse
import logging
import queue
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from dictado.config import Config, default_log_path, load_config
from dictado.hotkey import HotkeyMatcher, listen
from dictado.overlay import Indicator
from dictado.paste import foreground_window, paste_text
from dictado.recorder import Microphone
from dictado.transcriber import Transcriber

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
        )
        self.indicator = Indicator(config.indicator)
        self._jobs: queue.Queue = queue.Queue()
        self._state = threading.Lock()
        self._generation = 0
        self._recording = False
        self._target = 0
        self._ready = False
        self._status = "Cargando el modelo..."
        self._limit: threading.Timer | None = None
        self._listener = None
        self._icon: pystray.Icon | None = None
        self._worker = threading.Thread(target=self._work, name="dictado-worker", daemon=True)

    def run(self) -> None:
        self._configure_logging()
        log.info("Arranque. Atajo %s.", self.config.hotkey)
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
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.handlers.clear()
        root.addHandler(file_handler)
        root.addHandler(stream)

    def _load_model(self) -> None:
        try:
            self.transcriber.load()
            self.transcriber.warmup()
        except FileNotFoundError as exc:
            self._status = "Falta el modelo"
            log.error("%s", exc)
            return
        except Exception:
            self._status = "El modelo no cargo"
            log.exception("No se pudo cargar el modelo")
            return
        self._ready = True
        self._status = f"Listo ({self.transcriber.model_name}, {self.transcriber.device})"
        log.info(
            "Modelo listo: %s en %s/%s",
            self.transcriber.model_name,
            self.transcriber.device,
            self.transcriber.compute_type,
        )
        self._paint("#2f9e44")

    def _paint(self, color: str) -> None:
        if self._icon is not None:
            self._icon.icon = icon_image(color)

    def _on_press(self) -> None:
        if not self._ready:
            log.info("Atajo ignorado: %s. Si falta el modelo: python -m dictado.download_model", self._status)
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
            self.indicator.hide()
            return
        self.indicator.show_recording()
        self._paint("#c92a2a")
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
            self.indicator.hide()
            self._paint("#2f9e44")
            return
        self.indicator.show_transcribing()
        self._paint("#e67700")
        self._jobs.put((generation, hwnd, audio))

    def _work(self) -> None:
        while True:
            item = self._jobs.get()
            if item is None:
                return
            generation, hwnd, audio = item
            try:
                transcript = self.transcriber.transcribe(audio)
                log.info(
                    "Texto %s caracteres, idioma %s, audio %.2fs",
                    len(transcript.text),
                    transcript.language,
                    transcript.duration_s,
                )
                if transcript.text:
                    paste_text(transcript.text, self.config.paste_restore_delay_ms, hwnd or None)
            except Exception:
                log.exception("Fallo al transcribir o pegar")
            finally:
                with self._state:
                    current = self._generation
                    recording = self._recording
                if generation == current and not recording:
                    self.indicator.hide()
                    self._paint("#2f9e44")

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
