from pathlib import Path

import pytest

from dictado.config import Config, load_config


def test_missing_file_uses_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "no-esta.yaml")
    assert config.hotkey == "ctrl_r"
    assert config.model == "large-v3-turbo"
    assert config.model_fallback == "small"
    assert config.language == "auto"
    assert config.device == "auto"
    assert config.paste_restore_delay_ms == 450


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("hotkey: ctrl_r\nno_existe: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="desconocidas"):
        load_config(path)


def test_language_and_device_are_checked(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("language: fr\n", encoding="utf-8")
    with pytest.raises(ValueError, match="language"):
        load_config(path)


def test_model_path_joins_the_model_dir(tmp_path: Path) -> None:
    config = Config(model_dir=str(tmp_path))
    assert config.model_path("large-v3-turbo") == tmp_path / "large-v3-turbo"
    nested = tmp_path / "ya"
    nested.mkdir()
    assert config.model_path(str(nested)) == nested
