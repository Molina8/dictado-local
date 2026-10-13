from pathlib import Path

import numpy as np

from dictado.config import Config
from dictado.transcriber import Transcriber, choose_language


class _Info:
    language = "es"
    duration = 0.5


class _Boom:
    def __init__(self, path, device, compute_type, local_files_only=True):
        self.calls.append((device, compute_type, Path(path).name))
        if device == "cuda":
            raise RuntimeError("cublas64_12.dll is not found")

    def transcribe(self, *_args, **_kwargs):
        return iter(()), _Info()

    calls: list[tuple[str, str, str]] = []


def _models(root: Path) -> Config:
    for name in ("large-v3-turbo", "small"):
        folder = root / name
        folder.mkdir()
        (folder / "model.bin").write_bytes(b"x")
    return Config(model_dir=str(root), device="auto")


def test_cuda_load_failure_falls_back_to_small_cpu_int8(tmp_path, monkeypatch, caplog) -> None:
    _Boom.calls = []
    import ctranslate2
    import faster_whisper

    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)
    monkeypatch.setattr(faster_whisper, "WhisperModel", _Boom)
    engine = Transcriber(_models(tmp_path))
    with caplog.at_level("ERROR"):
        engine.load()
    assert _Boom.calls == [("cuda", "float16", "large-v3-turbo"), ("cpu", "int8", "small")]
    assert engine.device == "cpu"
    assert engine.compute_type == "int8"
    assert engine.model_name == "small"
    assert "CPU int8" in caplog.text


def test_cuda_encode_failure_also_falls_back(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    class _EncodeBoom:
        def __init__(self, path, device, compute_type, local_files_only=True):
            calls.append(device)
            self.device = device

        def transcribe(self, *_args, **_kwargs):
            if self.device == "cuda":
                raise RuntimeError("no VRAM")
            return iter(()), _Info()

    import ctranslate2
    import faster_whisper

    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)
    monkeypatch.setattr(faster_whisper, "WhisperModel", _EncodeBoom)
    engine = Transcriber(_models(tmp_path))
    engine.load()
    assert calls == ["cuda", "cpu"]
    assert engine.device == "cpu"
    assert engine.model_name == "small"


def test_autodetect_stays_inside_spanish_and_english() -> None:
    assert choose_language("en", [("en", 0.8), ("es", 0.1)]) == "en"
    assert choose_language("fr", [("fr", 0.7), ("es", 0.2), ("en", 0.1)]) == "es"
    assert choose_language("de", [("de", 0.9)]) == "es"

    class _Detector:
        def detect_language(self, _audio):
            return "ja", 0.6, [("ja", 0.6), ("en", 0.3), ("es", 0.05)]

    engine = Transcriber(Config())
    engine.model = _Detector()
    audio = np.zeros(1600, dtype=np.float32)
    assert engine._language_for(audio) == "en"
