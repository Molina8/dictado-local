"""Offline faster-whisper transcription."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dictado.config import Config

log = logging.getLogger(__name__)

ALLOWED_LANGUAGES = frozenset({"es", "en"})


def force_offline() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"


def enable_cuda_dlls() -> None:
    """Make the pip CUDA libraries visible to ctranslate2 on Windows."""
    import importlib.util
    import sys

    seen: set[str] = set()

    def add_dir(path: Path) -> None:
        if not path.is_dir() or not any(path.glob("*.dll")):
            return
        resolved = str(path.resolve())
        if resolved in seen:
            return
        seen.add(resolved)
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(resolved)
        os.environ["PATH"] = resolved + os.pathsep + os.environ.get("PATH", "")

    packages = ("nvidia.cublas", "nvidia.cuda_runtime", "nvidia.cudnn", "nvidia.cuda_nvrtc")
    roots: list[Path] = []
    for name in packages:
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.submodule_search_locations:
            continue
        for root in spec.submodule_search_locations:
            roots.append(Path(root) / "bin")

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        search = [exe_dir]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            search.append(Path(meipass))
        internal = exe_dir / "_internal"
        if internal.is_dir():
            search.append(internal)
        for folder in search:
            nvidia = folder / "nvidia"
            if nvidia.is_dir():
                roots.extend(nvidia.glob("*/bin"))
            elif any(folder.glob("cublas64_12.dll")) or any(folder.glob("cudnn64_9.dll")):
                roots.append(folder)

    for directory in roots:
        add_dir(directory)
    if seen:
        log.info("Bibliotecas CUDA en %s", os.pathsep.join(seen))
    else:
        log.warning("No encontre las bibliotecas CUDA de NVIDIA")


@dataclass
class Transcript:
    text: str
    language: str
    duration_s: float
    model: str
    device: str
    compute_type: str


class Transcriber:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.model = None
        self.model_name = ""
        self.device = ""
        self.compute_type = ""

    def load(self) -> None:
        force_offline()
        enable_cuda_dlls()
        import ctranslate2
        from faster_whisper import WhisperModel

        cuda_ok = ctranslate2.get_cuda_device_count() > 0
        requested = self.config.device
        if requested in {"auto", "cuda"} and cuda_ok:
            compute = "float16" if self.config.compute_type == "auto" else self.config.compute_type
            try:
                self._open_model(WhisperModel, self.config.model, "cuda", compute)
                self._touch()
                return
            except Exception:
                log.exception(
                    "No se pudo cargar %s en CUDA. Sigo con %s en CPU int8.",
                    self.config.model,
                    self.config.model_fallback,
                )
                self.model = None
        elif requested == "cuda":
            log.warning("No hay dispositivo CUDA. Sigo con %s en CPU int8.", self.config.model_fallback)

        if requested == "cpu" and self.config.compute_type != "auto":
            compute = self.config.compute_type
        else:
            compute = "int8"
        self._open_model(WhisperModel, self.config.model_fallback, "cpu", compute)

    def warmup(self) -> None:
        silence = np.zeros(self.config.sample_rate // 2, dtype=np.float32)
        self.transcribe(silence)

    def transcribe(self, audio: np.ndarray) -> Transcript:
        if self.model is None:
            raise RuntimeError("El modelo no esta cargado")
        language = self._language_for(audio)
        segments, info = self.model.transcribe(
            audio,
            language=language,
            beam_size=self.config.beam_size,
            vad_filter=self.config.vad_filter,
            condition_on_previous_text=False,
            without_timestamps=True,
            temperature=0.0,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text).strip()
        if self.config.append_space and text:
            text += " "
        detected = getattr(info, "language", None) or language or ""
        duration = float(getattr(info, "duration", 0.0) or (len(audio) / self.config.sample_rate))
        return Transcript(
            text=text,
            language=str(detected),
            duration_s=duration,
            model=self.model_name,
            device=self.device,
            compute_type=self.compute_type,
        )

    def _language_for(self, audio: np.ndarray) -> str | None:
        if self.config.language != "auto":
            return self.config.language
        if audio.size == 0:
            return "es"
        detected, _probability, ranked = self.model.detect_language(audio)
        return choose_language(detected, ranked)

    def _open_model(self, factory, name: str, device: str, compute_type: str) -> None:
        path = self._require_model(name)
        self.model_name = name
        self.device = device
        self.compute_type = compute_type
        self.model = factory(
            str(path),
            device=device,
            compute_type=compute_type,
            local_files_only=True,
        )

    def _touch(self) -> None:
        """Run one short encode so a missing CUDA DLL fails inside load()."""
        silence = np.zeros(max(1, self.config.sample_rate // 2), dtype=np.float32)
        segments, _info = self.model.transcribe(
            silence,
            language="es",
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
            temperature=0.0,
        )
        for _segment in segments:
            pass

    def _require_model(self, name: str) -> Path:
        path = self.config.model_path(name)
        if (path / "model.bin").is_file():
            return path
        raise FileNotFoundError(
            f"No esta el modelo '{name}' en {path}. "
            "Descargalo una vez con: python -m dictado.download_model"
        )


def choose_language(detected: str, ranked: list[tuple[str, float]]) -> str:
    """Keep autodetection inside Spanish and English."""
    if detected in ALLOWED_LANGUAGES:
        return detected
    scores = {code: score for code, score in ranked if code in ALLOWED_LANGUAGES}
    if not scores:
        return "es"
    return max(scores, key=scores.get)
