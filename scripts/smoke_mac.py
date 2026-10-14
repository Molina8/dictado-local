"""Offline smoke check for the macOS build, run inside the CI job.

Steps:
1. `import dictado.app` resolves the platform layer.
2. `say` + `afconvert` render a Spanish wav.
3. Transcribe it with the selected backend (whisper-small-mlx for speed) and
   assert the word "prueba" is present.
4. The generated bundle binary answers `--selftest` (checked in build_mac.sh).

Run: python scripts/smoke_mac.py [--model mlx-community/whisper-small-mlx]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TEXT = "hola, esto es una prueba"


def make_wav(path: Path) -> Path:
    aiff = path.with_suffix(".aiff")
    subprocess.run(["say", "-o", str(aiff), TEXT], check=True, timeout=60)
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff), str(path)],
        check=True,
        timeout=60,
    )
    aiff.unlink(missing_ok=True)
    return path


def read_audio(path: Path):
    """16 kHz mono PCM as float32 in [-1, 1].

    mlx-whisper shells out to ffmpeg when given a path. The runner has no
    ffmpeg; afconvert already wrote the samples, so we hand them over directly.
    """
    import numpy as np

    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2 or handle.getframerate() != 16000:
            raise RuntimeError(
                f"wav inesperado: {handle.getnchannels()}ch "
                f"{handle.getsampwidth() * 8}bit {handle.getframerate()}Hz"
            )
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    return np.ascontiguousarray(samples)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default="mlx-community/whisper-small-mlx",
        help="Repositorio de Hugging Face para la transcripcion",
    )
    parser.add_argument(
        "--bundle",
        default=None,
        help="Ruta al binario dentro del .app para el --selftest",
    )
    args = parser.parse_args()

    from dictado.backends import select_backend
    from dictado.config import Config
    from dictado.platform import get_platform

    config = Config(device="mlx", model=args.model, model_fallback="small")
    get_platform()
    backend = select_backend(config)
    print(f"backend={backend}")

    wav = make_wav(Path("/tmp/dictado-smoke.wav"))

    import mlx_whisper  # the wheel only exists on darwin arm64

    if args.bundle:
        # Bundle first: a broken pack cannot be saved by a good transcription.
        subprocess.run([args.bundle, "--selftest"], check=True, timeout=120)
        print("bundle selftest ok")

    result = mlx_whisper.transcribe(read_audio(wav), path_or_hf_repo=args.model, language="es")
    text = str(result.get("text", "")).lower()
    print(f"text={text}")
    wav.unlink(missing_ok=True)
    if "prueba" not in text:
        print("El texto esperado no aparece en la transcripcion", file=sys.stderr)
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())