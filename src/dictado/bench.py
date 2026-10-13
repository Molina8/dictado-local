"""Time a warm transcription of a wav file with the app settings."""

from __future__ import annotations

import argparse
import time
import wave
from pathlib import Path

import numpy as np

from dictado.config import load_config
from dictado.transcriber import Transcriber


def load_wav(path: Path, sample_rate: int) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"WAV de {width} bytes por muestra no soportado")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != sample_rate and len(audio):
        target = int(len(audio) * sample_rate / rate)
        source_x = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        target_x = np.linspace(0.0, 1.0, num=max(target, 1), endpoint=False)
        audio = np.interp(target_x, source_x, audio).astype(np.float32)
    return np.ascontiguousarray(audio, dtype=np.float32)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dictado.bench", description="Mide una transcripcion en caliente")
    parser.add_argument("wav", help="Archivo WAV")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    config = load_config(Path(args.config) if args.config else None)
    audio = load_wav(Path(args.wav), config.sample_rate)
    seconds = len(audio) / config.sample_rate
    engine = Transcriber(config)
    engine.load()
    engine.warmup()
    started = time.perf_counter()
    transcript = engine.transcribe(audio)
    elapsed = time.perf_counter() - started
    print(f"audio_s={seconds:.2f}")
    print(f"elapsed_s={elapsed:.3f}")
    print(f"model={transcript.model}")
    print(f"device={transcript.device}")
    print(f"compute_type={transcript.compute_type}")
    print(f"language={transcript.language}")
    print(f"text={transcript.text}")


if __name__ == "__main__":
    main()
