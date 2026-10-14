"""Offline faster-whisper transcription."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dictado.backends import (
    BACKEND_MLX,
    MLX_FALLBACK_ID,
    mlx_repo_for,
    select_backend,
)
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

    if sys.platform == "darwin":
        return

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
        try:
            spec = importlib.util.find_spec(name)
        except ModuleNotFoundError:
            # find_spec raises when the parent package ("nvidia") is absent,
            # a normal situation off-Windows. Missing DLLs, not an error.
            continue
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


def cuda_available() -> bool:
    """True when ctranslate2 can see a CUDA device. Any failure means CPU."""
    if sys.platform == "darwin":
        return False
    try:
        enable_cuda_dlls()
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:
        log.warning("No se pudo comprobar CUDA. Sigo en CPU.", exc_info=True)
        return False


def models_for_device(config: Config, cuda_ok: bool) -> list[str]:
    """Weights to fetch before load(). Without CUDA, only the CPU model."""
    if sys.platform == "darwin":
        wanted: list[str] = []
        if config.device in {"auto", "mlx"} and config.model:
            wanted.append(mlx_repo_for(config.model))
        if config.model_fallback:
            fallback = mlx_repo_for(config.model_fallback)
            if fallback not in wanted:
                wanted.append(fallback)
        if config.device == "cpu" and MLX_FALLBACK_ID in wanted:
            # CPU on darwin never runs mlx; fetch only the faster-whisper
            # fallback (its folder name stays the friendly name).
            wanted = [config.model_fallback]
        if not wanted and config.model:
            wanted.append(config.model)
        return wanted
    use_cuda = bool(cuda_ok) and config.device in {"auto", "cuda"}
    chosen: list[str] = []
    if use_cuda and config.model:
        chosen.append(config.model)
    fallback = config.model_fallback
    if fallback and fallback not in chosen:
        chosen.append(fallback)
    if not chosen and config.model:
        chosen.append(config.model)
    return chosen


@dataclass
class Transcript:
    text: str
    language: str
    duration_s: float
    model: str
    device: str
    compute_type: str


class _MlxModel:
    """Adapter that answers the same calls the faster-whisper model gets.

    `_language_for` needs `detect_language`; mlx-whisper decides language in
    its own transcribe() when `language` is not passed, so this adapter keeps
    the es/en filter by reading the result dictionary instead. `None` markers
    tell `Transcriber._language_for` to let mlx run with `language=None`.
    """

    def __init__(self, engine: "Transcriber") -> None:
        self._engine = engine
        self.repo = ""

    def transcribe(self, audio, **_kwargs):
        import mlx_whisper

        language = self._engine._decide_mlx_language(audio)
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.repo,
            language=language,
            condition_on_previous_text=False,
            temperature=0.0,
        )
        return self._iter_segments(result), _MlxInfo(result.get("language"))

    @staticmethod
    def _iter_segments(result):
        for segment in result.get("segments", []):
            text = str(segment.get("text", "")).strip()
            if text:
                yield _MlxSegment(text)

    def detect_language(self, _audio):
        raise RuntimeError("mlx detect_language no se usa: el idioma va en decode options")


class _MlxSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _MlxInfo:
    def __init__(self, language: str) -> None:
        self.language = language
        self.duration = 0.0


class Transcriber:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.model = None
        self.model_name = ""
        self.device = ""
        self.compute_type = ""

    def load(self) -> None:
        force_offline()
        if select_backend(self.config) == BACKEND_MLX:
            self._load_mlx()
            return
        from faster_whisper import WhisperModel  # deferred: heavy at import time

        cuda_ok = cuda_available()
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

    def _load_mlx(self) -> None:
        """Load mlx-community weights; fall back to faster-whisper on CPU.

        The config model names are faster-whisper ones; on the mlx backend
        they map to their mlx-community repos via `mlx_repo_for`. A local
        folder or an explicit "user/name" id passes through untouched.
        """
        requested = mlx_repo_for(self.config.model)
        try:
            self._open_mlx(requested)
        except Exception:
            log.exception(
                "No se pudo cargar %s con mlx-whisper. Sigo con %s en CPU int8.",
                requested,
                self.config.model_fallback,
            )
            self._load_faster_cpu()
            return
        try:
            self.warmup()
        except Exception:
            log.exception(
                "mlx-whisper no paso el warmup. Sigo con %s en CPU int8.",
                self.config.model_fallback,
            )
            self._load_faster_cpu()

    def _open_mlx(self, name: str) -> None:
        path = self.config.model_path(name)
        # model_path() points at the models folder for repo ids too; only a
        # real folder on disk may be handed to mlx-whisper directly.
        source = str(path) if path.is_dir() else name
        self.model = _MlxModel(self)
        self.model.repo = source
        self.model_name = name
        self.device = "mlx"
        self.compute_type = "mlx_fp16"

    def _load_faster_cpu(self) -> None:
        from faster_whisper import WhisperModel  # deferred: heavy at import time

        self.model = None
        compute = self.config.compute_type if self.config.compute_type != "auto" else "int8"
        self._open_model(WhisperModel, self.config.model_fallback, "cpu", compute)

    def _decide_mlx_language(self, audio: np.ndarray) -> str | None:
        """The one language mlx-whisper decodes with, None to autodetect."""
        if self.config.language != "auto":
            return self.config.language
        if audio.size == 0:
            return "es"
        return None

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
        if isinstance(self.model, _MlxModel) and detected not in ALLOWED_LANGUAGES:
            # The mlx result reports the raw detected language; the es/en
            # filter still applies to what ends up in the history record.
            detected = detected if detected in ALLOWED_LANGUAGES else ""
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
        if isinstance(self.model, _MlxModel):
            return None
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
