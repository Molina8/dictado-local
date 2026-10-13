from datetime import datetime
from pathlib import Path

from dictado.history import append_history, read_history, transcript_record


def test_history_appends_and_reads_in_order(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    first = transcript_record("hola", "es", 1.2, "small", "cpu", datetime(2026, 10, 13, 9, 0, 0))
    second = transcript_record("hello", "en", 0.4, "large-v3-turbo", "cuda", datetime(2026, 10, 13, 9, 1, 0))
    append_history(first, path)
    append_history(second, path)
    rows = read_history(path)
    assert [row["text"] for row in rows] == ["hola", "hello"]
    assert rows[0]["language"] == "es"
    assert rows[1]["device"] == "cuda"
    assert rows[1]["duration_s"] == 0.4


def test_history_keeps_the_newest_entries_when_the_file_grows(tmp_path: Path, monkeypatch) -> None:
    import dictado.history as history

    monkeypatch.setattr(history, "MAX_ENTRIES", 2)
    monkeypatch.setattr(history, "TRIM_BYTES", 1)
    path = tmp_path / "history.jsonl"
    for index in range(5):
        append_history({"text": str(index)}, path)
    assert [row["text"] for row in read_history(path)] == ["3", "4"]
