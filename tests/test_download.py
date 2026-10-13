from pathlib import Path

from dictado.download_model import download_models, model_ready


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
