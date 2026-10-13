"""Download Whisper weights once. This command is the only networked step."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dictado.config import default_model_dir


def main(argv: list[str] | None = None) -> None:
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ["TRANSFORMERS_OFFLINE"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
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
    root.mkdir(parents=True, exist_ok=True)
    from faster_whisper.utils import download_model

    for name in names:
        dest = root / Path(name).name
        dest.mkdir(parents=True, exist_ok=True)
        print(f"Descargando {name} en {dest}", flush=True)
        saved = download_model(name, output_dir=str(dest), local_files_only=False)
        print(f"Listo {name}: {saved}", flush=True)


if __name__ == "__main__":
    main()
