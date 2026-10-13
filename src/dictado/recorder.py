"""Microphone capture for push-to-talk."""

from __future__ import annotations

import threading
from collections import deque

import numpy as np
import sounddevice as sd


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

    def open(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=self._on_audio,
        )
        self._stream.start()

    def close(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            stream.stop()
            stream.close()

    def start(self) -> None:
        if self._stream is None:
            self.open()
        with self._lock:
            self._chunks = list(self._preroll)
            self._recording = True

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
            chunks = self._chunks
            self._chunks = []
        if not self.keep_open:
            self.close()
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32, copy=False)

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
