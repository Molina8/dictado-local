import sys
from pathlib import Path

import pytest

from dictado.config import Config, load_config


def test_missing_file_uses_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "no-esta.yaml")
    # The default hotkey depends on the platform (ctrl_r on Windows,
    # alt_r on darwin); check both instead of assuming one.
    expected = "ctrl_r" if sys.platform != "darwin" else "alt_r"
    assert config.hotkey == expected
    assert config.model == "large-v3-turbo"
    assert config.model_fallback == "small"
    assert config.language == "auto"
    assert config.device == "auto"
    assert config.paste_restore_delay_ms == 450
    assert config.indicator is True
    assert config.indicator_position == "bottom-center"
    assert config.indicator_monitor == "cursor"
    assert config.indicator_scale == 1.0
    assert config.sound is True
    assert config.history is True
    assert config.start_with_windows is True
    assert config.check_updates is True


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


def test_frozen_app_reads_appdata_and_ignores_the_working_directory(tmp_path: Path, monkeypatch) -> None:
    roaming = tmp_path / "Roaming"
    folder = roaming / "dictado-local"
    folder.mkdir(parents=True)
    (folder / "config.yaml").write_text("hotkey: ctrl\nstart_with_windows: false\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("hotkey: ctrl+shift\n", encoding="utf-8")
    monkeypatch.delenv("DICTADO_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    # This path is the Windows frozen flow (APPDATA discovery); run it as
    # win32 on any CI OS so the assertions hold.
    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setattr(sys, "executable", str(tmp_path / "DictadoLocal.exe"))
    config = load_config()
    assert config.hotkey == "ctrl"
    assert config.start_with_windows is False


def test_check_updates_can_be_turned_off(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("check_updates: false\n", encoding="utf-8")
    assert load_config(path).check_updates is False


def test_indicator_layout_is_optional(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "indicator_position: top-center\nindicator_monitor: primary\nindicator_scale: 1\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.indicator_position == "top-center"
    assert config.indicator_monitor == "primary"
    assert config.indicator_scale == 1.0


def test_indicator_layout_is_checked(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("indicator_position: arriba\n", encoding="utf-8")
    with pytest.raises(ValueError, match="indicator_position"):
        load_config(path)
    path.write_text("indicator_monitor: ambos\n", encoding="utf-8")
    with pytest.raises(ValueError, match="indicator_monitor"):
        load_config(path)
    path.write_text("indicator_scale: 3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="indicator_scale"):
        load_config(path)
    path.write_text("indicator_scale: grande\n", encoding="utf-8")
    with pytest.raises(ValueError, match="indicator_scale"):
        load_config(path)


def test_model_path_joins_the_model_dir(tmp_path: Path) -> None:
    config = Config(model_dir=str(tmp_path))
    assert config.model_path("large-v3-turbo") == tmp_path / "large-v3-turbo"
    nested = tmp_path / "ya"
    nested.mkdir()
    assert config.model_path(str(nested)) == nested


def test_frozen_app_on_darwin_reads_application_support(tmp_path: Path, monkeypatch) -> None:
    """Darwin equivalent of the APPDATA frozen flow (review point 2)."""
    folder = tmp_path / "Library" / "Application Support" / "DictadoLocal"
    folder.mkdir(parents=True)
    (folder / "config.yaml").write_text("hotkey: alt_r\nstart_with_windows: false\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("hotkey: ctrl+shift\n", encoding="utf-8")
    monkeypatch.delenv("DICTADO_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "DictadoLocal.app"))
    config = load_config()
    assert config.hotkey == "alt_r"
    assert config.start_with_windows is False


def test_darwin_paths_live_in_library(monkeypatch, tmp_path: Path) -> None:
    from dictado.config import app_data_dir, default_log_path, default_model_dir

    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path), raising=False)
    assert app_data_dir() == tmp_path / "Library" / "Application Support" / "DictadoLocal"
    assert default_model_dir() == tmp_path / "Library" / "Application Support" / "DictadoLocal" / "models"
    assert default_log_path() == tmp_path / "Library" / "Logs" / "DictadoLocal" / "dictado.log"
