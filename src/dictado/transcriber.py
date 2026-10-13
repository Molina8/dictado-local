"""Offline faster-whisper transcription."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dictado.config import Config


def force_offline() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"


def enable_cuda_dlls() -> None:
    """Make the pip CUDA libraries visible to ctranslate2 on Windows."""
    import importlib.util

    packages = ("nvidia.cublas", "nvidia.cuda_runtime", "nvidia.cudnn", "nvidia.cuda_nvrtc")
    for name in packages:
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.submodule_search_locations:
            continue
        for root in spec.submodule_search_locations:
            bin_dir = Path(root) / "bin"
            if not bin_dir.is_dir():
                continue
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


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

        cuda = ctranslate2.get_cuda_device_count() > 0
        requested = self.config.device
        use_cuda = cuda and requested in {"auto", "cuda"}
        if requested == "cuda" and not cuda:
            use_cuda = False
        if use_cuda:
            self.model_name = self.config.model
            self.device = "cuda"
            self.compute_type = "float16" if self.config.compute_type == "auto" else self.config.compute_type
        else:
            self.model_name = self.config.model_fallback if requested == "auto" or not cuda else self.config.model
            if requested == "cpu":
                self.model_name = self.config.model_fallback
            self.device = "cpu"
            self.compute_type = "int8" if self.config.compute_type == "auto" else self.config.compute_type
        path = self._require_model(self.model_name)
        self.model = WhisperModel(
            str(path),
            device=self.device,
            compute_type=self.compute_type,
            local_files_only=True,
        )

    def warmup(self) -> None:
        silence = np.zeros(self.config.sample_rate // 2, dtype=np.float32)
        self.transcribe(silence)

    def transcribe(self, audio: np.ndarray) -> Transcript:
        if self.model is None:
            raise RuntimeError("El modelo no esta cargado")
        language = None if self.config.language == "auto" else self.config.language
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
        detected = getattr(info, "language", None) or ""
        duration = float(getattr(info, "duration", 0.0) or (len(audio) / self.config.sample_rate))
        return Transcript(
            text=text,
            language=str(detected),
            duration_s=duration,
            model=self.model_name,
            device=self.device,
            compute_type=self.compute_type,
        )

    def _require_model(self, name: str) -> Path:
        path = self.config.model_path(name)
        if (path / "model.bin").is_file():
            return path
        raise FileNotFoundError(
            f"No esta el modelo '{name}' en {path}. "
            "Descargalo una vez con: python -m dictado.download_model"
        )
