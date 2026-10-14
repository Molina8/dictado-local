"""Transcription backend selection. Pure logic, no heavy imports.

`select_backend` decides between mlx-whisper (Apple silicon), faster-whisper
on CUDA (Windows with an NVIDIA GPU) and faster-whisper on CPU. It only
inspects config values, `sys.platform`, `platform.machine()` and the
importability of `mlx_whisper`, so tests can drive every branch with
monkeypatched inputs.
"""

from __future__ import annotations

import importlib.util
import platform
import sys
from pathlib import Path
from typing import Callable

from dictado.config import Config

MLX_MODEL_ID = "mlx-community/whisper-large-v3-turbo"
MLX_FALLBACK_ID = "mlx-community/whisper-small-mlx"

BACKEND_MLX = "mlx"
BACKEND_CUDA = "faster-whisper-cuda"
BACKEND_CPU = "faster-whisper-cpu"


def mlx_repo_for(name: str) -> str:
    """Map a faster-whisper model name onto its mlx-community repo.

    Local folders and explicit Hugging Face ids pass through untouched.
    """
    if name.startswith(("mlx-community/", "local/")) or Path(name).is_dir() or Path(name).is_absolute():
        return name
    mapping = {
        "large-v3-turbo": MLX_MODEL_ID,
        "turbo": MLX_MODEL_ID,
        "small": MLX_FALLBACK_ID,
    }
    return mapping.get(name, name)


def mlx_importable(
    platform_name: str | None = None,
    find_spec_fn: Callable[[str], object] | None = None,
) -> bool:
    """True when the MLX wheel could be imported. Never imports it."""
    if (platform_name or sys.platform) != "darwin":
        return False
    finder = find_spec_fn or importlib.util.find_spec
    try:
        return finder("mlx_whisper") is not None
    except (ImportError, ValueError):
        return False


def select_backend(
    config: Config,
    platform_name: str | None = None,
    machine: str | None = None,
    find_spec_fn: Callable[[str], object] | None = None,
    cuda_ok: bool | None = None,
) -> str:
    """Pick the transcription backend for this machine.

    - darwin + arm64 + device in {auto, mlx} + mlx_whisper importable -> mlx.
    - any other darwin case -> faster-whisper CPU with int8.
    - elsewhere the current CUDA logic decides.
    """
    name = platform_name if platform_name is not None else sys.platform
    if name == "darwin":
        arch = (machine if machine is not None else platform.machine()).lower()
        if arch in {"arm64", "aarch64"} and config.device in {"auto", "mlx"}:
            if mlx_importable(name, find_spec_fn):
                return BACKEND_MLX
        return BACKEND_CPU
    if cuda_ok is None:
        from dictado.transcriber import cuda_available  # deferred: import cycle

        cuda_ok = cuda_available()
    if config.device in {"auto", "cuda"} and cuda_ok:
        return BACKEND_CUDA
    return BACKEND_CPU