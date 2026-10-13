"""Local transcript history. One JSON object per line."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from dictado.config import local_data_dir

MAX_ENTRIES = 2000
TRIM_BYTES = 1_000_000


def history_path() -> Path:
    return local_data_dir() / "history.jsonl"


def append_history(record: dict[str, Any], path: Path | None = None) -> Path:
    target = path or history_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    _trim(target)
    return target


def transcript_record(
    text: str,
    language: str,
    duration_s: float,
    model: str,
    device: str,
    when: datetime | None = None,
) -> dict[str, Any]:
    moment = when or datetime.now().astimezone()
    return {
        "ts": moment.isoformat(timespec="seconds"),
        "text": text,
        "language": language,
        "duration_s": round(float(duration_s), 3),
        "model": model,
        "device": device,
    }


def read_history(path: Path | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    target = path or history_path()
    if not target.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    if limit is not None and limit >= 0:
        return rows[-limit:]
    return rows


def _trim(path: Path) -> None:
    if path.stat().st_size < TRIM_BYTES:
        return
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) <= MAX_ENTRIES:
        return
    path.write_text("\n".join(lines[-MAX_ENTRIES:]) + "\n", encoding="utf-8")
