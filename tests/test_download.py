from pathlib import Path

from dictado.download_model import download_best_effort, download_models, model_ready


def test_download_skips_a_model_that_is_already_present(tmp_path: Path) -> None:
    dest = tmp_path / "small"
    dest.mkdir()
    (dest / "model.bin").write_bytes(b"x")
    calls: list[str] = []

    def fetch(name, output_dir, local_files_only=False):
        calls.append(name)
        return output_dir

    saved = download_models(["small"], tmp_path, fetch=fetch)
    assert calls == []
    assert saved == [dest]
    assert model_ready(dest)


def test_download_fetches_only_the_missing_model(tmp_path: Path) -> None:
    present = tmp_path / "small"
    present.mkdir()
    (present / "model.bin").write_bytes(b"x")
    calls: list[str] = []

    def fetch(name, output_dir, local_files_only=False):
        calls.append(name)
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "model.bin").write_bytes(b"y")
        return output_dir

    download_models(["small", "large-v3-turbo"], tmp_path, fetch=fetch)
    assert calls == ["large-v3-turbo"]
    assert model_ready(tmp_path / "large-v3-turbo")


def test_download_best_effort_keeps_going_when_one_model_fails(tmp_path: Path) -> None:
    def fetch(name, output_dir, local_files_only=False):
        if name == "large-v3-turbo":
            raise RuntimeError("network")
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "model.bin").write_bytes(b"y")
        return output_dir

    failed = download_best_effort(["large-v3-turbo", "small"], tmp_path, fetch=fetch)
    assert failed == ["large-v3-turbo"]
    assert model_ready(tmp_path / "small")
    assert not model_ready(tmp_path / "large-v3-turbo")


def test_mlx_download_lands_where_config_looks(tmp_path: Path) -> None:
    from dictado.config import Config

    config = Config(model_dir=str(tmp_path))
    name = "mlx-community/whisper-large-v3-turbo"

    def fetch(repo, output_dir, local_files_only=False):
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.json").write_text("{}")
        (folder / "weights.safetensors").write_bytes(b"w")
        return folder

    download_models([name], config.resolved_model_dir(), fetch=fetch)
    assert model_ready(config.model_path(name))
    assert config.model_path(name) == tmp_path / "mlx-community" / "whisper-large-v3-turbo"


def test_fetch_mlx_uses_local_dir(tmp_path: Path, monkeypatch) -> None:
    import sys
    import types

    from dictado import download_model as dm

    # Fake module + restored env: importing the real huggingface_hub here
    # (with HF_HUB_OFFLINE=0) would freeze it online for later tests.
    huggingface_hub = types.ModuleType("huggingface_hub")
    monkeypatch.setitem(sys.modules, "huggingface_hub", huggingface_hub)
    for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY",
                "HF_HUB_DISABLE_PROGRESS_BARS", "TQDM_DISABLE"):
        monkeypatch.setenv(var, "1")

    seen = {}

    def fake_snapshot(repo_id, local_dir=None, **kw):
        seen.update(repo_id=repo_id, local_dir=local_dir)
        return local_dir

    huggingface_hub.snapshot_download = fake_snapshot
    dest = tmp_path / "mlx-community" / "whisper-small-mlx"
    dm._fetch_mlx("mlx-community/whisper-small-mlx", dest)
    assert seen == {"repo_id": "mlx-community/whisper-small-mlx", "local_dir": str(dest)}


def test_legacy_mlx_folder_is_migrated(tmp_path: Path) -> None:
    from dictado.download_model import migrate_legacy_mlx_dirs

    old = tmp_path / "whisper-small-mlx"
    old.mkdir()
    (old / "config.json").write_text("{}")
    (old / "weights.npz").write_bytes(b"w")
    migrate_legacy_mlx_dirs(["mlx-community/whisper-small-mlx", "small"], tmp_path)
    assert model_ready(tmp_path / "mlx-community" / "whisper-small-mlx")
    assert not old.exists()
