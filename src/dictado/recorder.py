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

# Nine bars. Quiet room noise stays at zero; a normal voice fills the pill.
LEVEL_BARS = 9
_NOISE_FLOOR = 0.008
_FULL_SCALE_RMS = 0.10


class Microphone:
    def __init__(
        self,
        sample_rate: int = 16000,
        device: int | None = None,
        keep_open: bool = True,
        pre_roll_ms: int = 250,
        level_bars: int = LEVEL_BARS,
    ) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.keep_open = keep_open
        self.level_bars = level_bars
        self._lock = threading.Lock()
        self._recording = False
        self._chunks: list[np.ndarray] = []
        self._levels = _silent_levels(level_bars)
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
            self._levels = _silent_levels(self.level_bars)
            needs_open = self._stream is None
        if needs_open:
            self._commands.put(("open", None, []))

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
            chunks = self._chunks
            self._chunks = []
            self._levels = _silent_levels(self.level_bars)
        if not self.keep_open:
            self._commands.put(("close", None, []))
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32, copy=False)

    def levels(self) -> tuple[float, ...]:
        """Latest per-bar loudness, from 0 to 1. Safe to call from the UI thread."""
        with self._lock:
            return self._levels

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
            recording = self._recording
            if recording:
                self._chunks.append(chunk)
            elif self.keep_open:
                self._preroll.append(chunk)
                self._preroll_count += int(chunk.shape[0])
                while self._preroll_count > self._preroll_limit and self._preroll:
                    removed = self._preroll.popleft()
                    self._preroll_count -= int(removed.shape[0])
        if not recording:
            return
        levels = chunk_levels(chunk, self.level_bars)
        with self._lock:
            if self._recording:
                self._levels = levels


def _silent_levels(count: int) -> tuple[float, ...]:
    return tuple(0.0 for _ in range(count))


def chunk_levels(samples: np.ndarray, bars: int = LEVEL_BARS) -> tuple[float, ...]:
    """Map one mic buffer to bar heights. Overall loudness sets the size; the buffer shape sets the contour."""
    if bars < 1:
        return ()
    data = np.asarray(samples, dtype=np.float32).reshape(-1)
    count = int(data.shape[0])
    if count == 0:
        return _silent_levels(bars)
    rms = float(np.dot(data, data) / count) ** 0.5
    if not np.isfinite(rms) or rms <= _NOISE_FLOOR:
        return _silent_levels(bars)
    loud = _loudness(rms)
    usable = (count // bars) * bars
    if usable >= bars:
        partial = np.sqrt(np.mean(data[:usable].reshape(bars, -1) ** 2, axis=1))
    else:
        partial = np.full(bars, rms, dtype=np.float32)
    peak = float(np.max(partial))
    if peak > 1e-8 and np.isfinite(peak):
        shape = partial / peak
    else:
        shape = np.ones(bars, dtype=np.float32)
    mixed = np.clip(loud * (0.42 + 0.58 * shape), 0.0, 1.0).astype(np.float32, copy=False)
    if bars == 1:
        return (float(mixed[0]),)
    padded = np.empty(bars + 2, dtype=np.float32)
    padded[0] = mixed[0]
    padded[-1] = mixed[-1]
    padded[1:-1] = mixed
    soft = np.clip(0.22 * padded[:-2] + 0.56 * padded[1:-1] + 0.22 * padded[2:], 0.0, 1.0)
    return tuple(float(value) for value in soft)


def _loudness(rms: float) -> float:
    span = _FULL_SCALE_RMS - _NOISE_FLOOR
    if span <= 0:
        return 1.0
    curved = ((rms - _NOISE_FLOOR) / span) ** 0.5
    if curved <= 0:
        return 0.0
    if curved >= 1:
        return 1.0
    return float(curved)
