"""Microphone capture for push-to-talk.

Opening and closing the PortAudio stream happens on a private thread.
The keyboard hook only flips the recording flag and, at most, queues a command.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections import deque

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


class Microphone:
    def __init__(
        self,
        sample_rate: int = 16000,
        device: int | None = None,
        keep_open: bool = True,
        pre_roll_ms: int = 250,
    ) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.keep_open = keep_open
        self._lock = threading.Lock()
        self._recording = False
        self._chunks: list[np.ndarray] = []
        preroll_frames = max(1, int(sample_rate * pre_roll_ms / 1000))
        self._preroll: deque[np.ndarray] = deque()
        self._preroll_limit = preroll_frames
        self._preroll_count = 0
        self._stream: sd.InputStream | None = None
        self._commands: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="dictado-mic", daemon=True)
        self._thread.start()

    def open(self) -> None:
        self._call("open")

    def close(self) -> None:
        self._call("close")

    def start(self) -> None:
        with self._lock:
            self._chunks = list(self._preroll)
            self._recording = True
            needs_open = self._stream is None
        if needs_open:
            self._commands.put(("open", None, []))

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
            chunks = self._chunks
            self._chunks = []
        if not self.keep_open:
            self._commands.put(("close", None, []))
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32, copy=False)

    def _call(self, name: str) -> None:
        done = threading.Event()
        error: list[BaseException] = []
        self._commands.put((name, done, error))
        if not done.wait(5):
            raise TimeoutError(f"El microfono no respondio a {name}")
        if error:
            raise error[0]

    def _run(self) -> None:
        while True:
            item = self._commands.get()
            if item is None:
                self._close_stream()
                return
            name, done, error = item
            try:
                if name == "open":
                    self._open_stream()
                elif name == "close":
                    self._close_stream()
            except Exception as exc:
                log.exception("Fallo de microfono en %s", name)
                if error is not None:
                    error.append(exc)
            finally:
                if done is not None:
                    done.set()

    def _open_stream(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=self._on_audio,
        )
        stream.start()
        with self._lock:
            self._stream = stream

    def _close_stream(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is None:
            return
        stream.stop()
        stream.close()

    def _on_audio(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        chunk = np.array(indata[:, 0], dtype=np.float32, copy=True)
        with self._lock:
            if self._recording:
                self._chunks.append(chunk)
                return
            if not self.keep_open:
                return
            self._preroll.append(chunk)
            self._preroll_count += int(chunk.shape[0])
            while self._preroll_count > self._preroll_limit and self._preroll:
                removed = self._preroll.popleft()
                self._preroll_count -= int(removed.shape[0])
