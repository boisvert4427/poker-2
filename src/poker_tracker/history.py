from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class HistoryFile:
    path: str
    last_modified: float
    size: int


TABLE_TOKEN_RE = re.compile(r"^Winamax\s+(.+?)$", re.IGNORECASE)


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


def find_history_file_for_table(history_locations: Iterable[str], table_title: str) -> HistoryFile | None:
    table_token = extract_table_token(table_title)
    if not table_token:
        return None

    candidates: list[Path] = []
    for location in history_locations:
        path = Path(location)
        if not path.exists() or not path.is_dir():
            continue
        candidates.extend(child for child in path.iterdir() if child.is_file() and child.suffix.lower() == ".txt")

    token_lower = table_token.lower()
    matching = [item for item in candidates if token_lower in item.stem.lower()]
    if not matching:
        return None

    latest = max(matching, key=lambda item: item.stat().st_mtime)
    stat = latest.stat()
    return HistoryFile(path=str(latest), last_modified=stat.st_mtime, size=stat.st_size)


def read_history_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def extract_table_token(window_title: str) -> str:
    match = TABLE_TOKEN_RE.match((window_title or "").strip())
    if not match:
        return ""
    raw = match.group(1).strip()
    return raw.strip()
