from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class HistoryFile:
    path: str
    last_modified: float
    size: int


def find_latest_history_file(history_locations: Iterable[str]) -> HistoryFile | None:
    candidates: list[Path] = []
    for location in history_locations:
        path = Path(location)
        if not path.exists() or not path.is_dir():
            continue
        candidates.extend(child for child in path.iterdir() if child.is_file() and child.suffix.lower() == ".txt")

    if not candidates:
        return None

    latest = max(candidates, key=lambda item: item.stat().st_mtime)
    stat = latest.stat()
    return HistoryFile(path=str(latest), last_modified=stat.st_mtime, size=stat.st_size)


def read_history_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")
