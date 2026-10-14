"""Load/warmup/fallback behaviour of the mlx backend, all with fakes."""

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from dictado.backends import BACKEND_MLX, MLX_FALLBACK_ID, MLX_MODEL_ID
from dictado.config import Config
from dictado.transcriber import Transcript, Transcriber

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="mlx decisions only run on darwin; the Windows branch has its own tests",
)


class _FakeMlxWhisper:
    """Stands in for the mlx_whisper module."""

    result = {"text": " hola prueba ", "segments": [{"text": " hola prueba "}], "language": "es"}

    calls: list[dict] = []

    @classmethod
    def transcribe(cls, audio, **kwargs):
        cls.calls.append({"audio_len": len(audio), **kwargs})
        return dict(cls.result)


@pytest.fixture
def mlx_env(monkeypatch, tmp_path):
    """darwin+arm64 with an importable mlx_whisper and local weights."""
    _FakeMlxWhisper.calls = []
    import platform

    fake = types.ModuleType("mlx_whisper")
    fake.__spec__ = importlib.util.spec_from_file_location("mlx_whisper", __file__)
    fake.transcribe = lambda audio, **kwargs: _FakeMlxWhisper.transcribe(audio, **kwargs)
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)
    _FakeMlxWhisper.calls = []

    for name in ("large-v3-turbo", "small"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "config.json").write_text("{}", encoding="utf-8")
        (folder / "weights.safetensors").write_bytes(b"w")
        (folder / "model.bin").write_bytes(b"w")
    config = Config(model_dir=str(tmp_path), device="mlx", model="large-v3-turbo")
    return config


def _engine(config: Config) -> Transcriber:
    return Transcriber(config)


def test_mlx_backend_selected_and_transcribed(mlx_env) -> None:
    from dictado.backends import select_backend

    engine = _engine(mlx_env)
    assert select_backend(mlx_env) == BACKEND_MLX
    engine.load()
    assert engine.device == "mlx"
    # The friendly faster-whisper name is mapped to the mlx-community repo.
    assert engine.model_name == MLX_MODEL_ID
    transcript = engine.transcribe(np.zeros(1600, dtype=np.float32))
    assert isinstance(transcript, Transcript)
    assert "prueba" in transcript.text
    assert transcript.device == "mlx"
    # mlx_whisper.transcribe got the mlx-community repo, not "large-v3-turbo"
    assert _FakeMlxWhisper.calls[-1]["path_or_hf_repo"] == MLX_MODEL_ID
    _FakeMlxWhisper.calls.pop()


def test_mlx_repo_reaches_mlx_whisper_transcribe(mlx_env) -> None:
    """point 1 of the review: the repo id, not the faster-whisper name."""
    engine = _engine(mlx_env)
    engine.load()
    _FakeMlxWhisper.calls = []
    # real speech (non-empty audio + language auto) -> language None
    engine.transcribe(np.zeros(1600, dtype=np.float32))
    call = _FakeMlxWhisper.calls[-1]
    assert call["path_or_hf_repo"] == MLX_MODEL_ID
    assert call["language"] is None  # mlx-whisper itself detects it
    _FakeMlxWhisper.calls.pop()


def test_mlx_fallback_repo_used_when_small_requested(tmp_path, monkeypatch) -> None:
    """device: mlx con small -> mlx-community/whisper-small-mlx."""
    import platform

    _FakeMlxWhisper.calls = []
    fake = types.ModuleType("mlx_whisper")
    fake.__spec__ = importlib.util.spec_from_file_location("mlx_whisper", __file__)
    fake.transcribe = lambda audio, **kwargs: _FakeMlxWhisper.transcribe(audio, **kwargs)
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)

    config = Config(model_dir=str(tmp_path), device="mlx", model="small")
    engine = _engine(config)
    engine.load()
    assert engine.model_name == MLX_FALLBACK_ID
    _FakeMlxWhisper.calls = []
    engine.transcribe(np.zeros(1600, dtype=np.float32))
    assert _FakeMlxWhisper.calls[-1]["path_or_hf_repo"] == MLX_FALLBACK_ID
    _FakeMlxWhisper.calls.pop()


def test_models_for_device_on_darwin_uses_mlx_repo_ids(monkeypatch) -> None:
    import platform

    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    from dictado.transcriber import models_for_device

    config = Config()
    assert models_for_device(config, cuda_ok=False) == [MLX_MODEL_ID, MLX_FALLBACK_ID]
    assert models_for_device(Config(device="cpu"), cuda_ok=False) == ["small"]
    assert models_for_device(Config(device="mlx"), cuda_ok=False) == [MLX_MODEL_ID, MLX_FALLBACK_ID]


def test_mlx_load_failure_falls_back_to_cpu_int8(mlx_env, monkeypatch, tmp_path, caplog) -> None:
    import faster_whisper

    class _Boom:
        def __init__(self, path, device, compute_type, local_files_only=True):
            self.calls_made = (device, compute_type)

        def transcribe(self, *_a, **_k):
            return iter(()), type("_I", (), {"language": "es", "duration": 0.1})()

    # Break the mlx path at load: no mlx_whisper module importable anymore.
    monkeypatch.delitem(sys.modules, "mlx_whisper", raising=False)

    def import_raises(name, *args, **kwargs):
        if name == "mlx_whisper":
            raise ImportError("no mlx")
        return __import__(name, *args, **kwargs)

    import builtins

    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "mlx_whisper":
            raise ImportError("no mlx")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    # The backend selection now answers CPU, so load() takes the faster path
    # directly; assert it opens the small model on CPU int8.
    monkeypatch.setattr(faster_whisper, "WhisperModel", _Boom)
    engine = _engine(mlx_env)
    with caplog.at_level("WARNING"):
        engine.load()
    assert engine.device == "cpu"
    assert engine.compute_type == "int8"
    assert engine.model_name == "small"


def test_mlx_warmup_failure_falls_back_to_cpu(mlx_env, monkeypatch) -> None:
    import faster_whisper

    # warmup() calls transcribe(silence) -> the fake mlx transcribe raises
    # -> _load_mlx falls back. Record what the faster-whisper loader got.
    opened: list[tuple] = []

    class _Recorder:
        def __init__(self, path, device, compute_type, local_files_only=True):
            opened.append((Path(path).name, device, compute_type))

        def transcribe(self, *_a, **_k):
            return iter(()), type("_I", (), {"language": "es", "duration": 0.1})()

    opened.clear()

    def mlx_boom(audio, **_kwargs):
        raise RuntimeError("MLX kernel mismatch")

    monkeypatch.setattr(_FakeMlxWhisper, "transcribe", staticmethod(mlx_boom))
    monkeypatch.setattr(faster_whisper, "WhisperModel", _Recorder)
    engine = _engine(mlx_env)
    engine.load()
    assert engine.device == "cpu"
    assert ("small", "cpu", "int8") in opened


def test_mlx_language_pin_and_es_default(mlx_env) -> None:
    engine = _engine(mlx_env)
    engine.load()
    # empty audio -> "es" default keeps autodetection deterministic
    _FakeMlxWhisper.calls = []
    engine.transcribe(np.zeros(0, dtype=np.float32))
    assert _FakeMlxWhisper.calls[-1]["language"] == "es"
    _FakeMlxWhisper.calls.pop()


def test_mlx_respects_offline_after_first_download(mlx_env, monkeypatch) -> None:
    engine = _engine(mlx_env)
    engine.load()
    import os

    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    _FakeMlxWhisper.calls.pop()