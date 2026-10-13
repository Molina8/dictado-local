"""Download Whisper weights once. This command is the only networked step."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dictado.config import default_model_dir

log = logging.getLogger("dictado.download")


def model_ready(directory: Path) -> bool:
    return (directory / "model.bin").is_file()


def download_models(names: list[str], model_dir: Path, fetch=None) -> list[Path]:
    """Download any model that is not already in `model_dir`. Returns destinations."""
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ["TRANSFORMERS_OFFLINE"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["TQDM_DISABLE"] = "1"
    model_dir.mkdir(parents=True, exist_ok=True)
    if fetch is None:
        from faster_whisper.utils import download_model as fetch

    saved: list[Path] = []
    for name in names:
        dest = model_dir / Path(name).name
        if model_ready(dest):
            log.info("El modelo %s ya esta en %s", name, dest)
            saved.append(dest)
            continue
        dest.mkdir(parents=True, exist_ok=True)
        _say(f"Descargando {name} en {dest}")
        fetch(name, output_dir=str(dest), local_files_only=False)
        _say(f"Listo {name}: {dest}")
        saved.append(dest)
    return saved


def download_best_effort(names: list[str], model_dir: Path, fetch=None) -> list[str]:
    """Download each model. Returns the names that failed. One failure does not stop the rest."""
    failed: list[str] = []
    for name in names:
        try:
            download_models([name], model_dir, fetch=fetch)
        except Exception:
            log.exception("No se pudo descargar %s", name)
            failed.append(name)
    return failed


def _say(message: str) -> None:
    log.info(message)
    if sys.stdout is None:
        return
    try:
        print(message, flush=True)
    except Exception:
        return


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="dictado.download_model",
        description="Descarga modelos faster-whisper a la carpeta local",
    )
    parser.add_argument(
        "models",
        nargs="*",
        help="Nombres (large-v3-turbo, small, ...) o un id de Hugging Face",
    )
    parser.add_argument("--dir", dest="model_dir", default=None, help="Carpeta destino")
    args = parser.parse_args(argv)
    names = args.models or ["large-v3-turbo", "small"]
    root = Path(args.model_dir) if args.model_dir else default_model_dir()
    download_models(names, root)


if __name__ == "__main__":
    main()
