"""YAML configuration for the tray app."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

APP_DIR_NAME = "dictado-local"


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_DIR_NAME


def local_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_DIR_NAME


def default_config_path() -> Path:
    return app_data_dir() / "config.yaml"


def default_model_dir() -> Path:
    return local_data_dir() / "models"


def default_log_path() -> Path:
    return local_data_dir() / "logs" / "dictado.log"


@dataclass
class Config:
    hotkey: str = "ctrl_r"
    sample_rate: int = 16000
    min_record_ms: int = 300
    max_record_s: int = 120
    keep_mic_open: bool = True
    pre_roll_ms: int = 250
    input_device: int | None = None
    model: str = "large-v3-turbo"
    model_fallback: str = "small"
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = 1
    vad_filter: bool = True
    language: str = "auto"
    model_dir: str | None = None
    paste_restore_delay_ms: int = 250
    append_space: bool = False
    indicator: bool = True

    def resolved_model_dir(self) -> Path:
        if self.model_dir:
            return Path(os.path.expandvars(self.model_dir)).expanduser()
        return default_model_dir()

    def model_path(self, name: str) -> Path:
        candidate = Path(os.path.expandvars(name)).expanduser()
        if candidate.is_dir():
            return candidate
        return self.resolved_model_dir() / name


def load_config(path: Path | None = None) -> Config:
    config_path = path or _discover_config_path()
    raw: dict[str, Any] = {}
    if config_path is not None and config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"La configuracion de {config_path} tiene que ser un mapa YAML")
        raw = loaded
    known = {item.name for item in fields(Config)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"Claves desconocidas en la configuracion: {', '.join(unknown)}")
    config = Config(**raw)
    _validate(config)
    return config


def _discover_config_path() -> Path | None:
    env = os.environ.get("DICTADO_CONFIG")
    if env:
        return Path(env)
    local = Path.cwd() / "config.yaml"
    if local.is_file():
        return local
    default = default_config_path()
    if default.is_file():
        return default
    return None


def _validate(config: Config) -> None:
    if not str(config.hotkey).strip():
        raise ValueError("hotkey no puede estar vacio")
    if config.sample_rate < 8000:
        raise ValueError("sample_rate tiene que ser al menos 8000")
    if config.min_record_ms < 0:
        raise ValueError("min_record_ms no puede ser negativo")
    if config.max_record_s < 1:
        raise ValueError("max_record_s tiene que ser al menos 1")
    if config.beam_size < 1:
        raise ValueError("beam_size tiene que ser al menos 1")
    if config.language not in {"auto", "es", "en"}:
        raise ValueError("language tiene que ser auto, es o en")
    if config.device not in {"auto", "cuda", "cpu"}:
        raise ValueError("device tiene que ser auto, cuda o cpu")
    if config.paste_restore_delay_ms < 0:
        raise ValueError("paste_restore_delay_ms no puede ser negativo")
    if config.pre_roll_ms < 0:
        raise ValueError("pre_roll_ms no puede ser negativo")
