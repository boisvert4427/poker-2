from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .parser import split_winamax_hands


@dataclass(slots=True)
class HistoryFile:
    path: str
    last_modified: float
    size: int


TABLE_TOKEN_RE = re.compile(r"^Winamax\s+(.+?)$", re.IGNORECASE)
HAND_ID_RE = re.compile(r"HandId:\s*#([\d-]+)")


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


def latest_hand_block_key(history_file: object | None) -> str:
    """Return a stable key for the last hand block in a Winamax history file."""
    path = getattr(history_file, "path", history_file)
    if not path:
        return ""
    try:
        text = Path(str(path)).read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return ""
    blocks = split_winamax_hands(text)
    if not blocks:
        return ""
    match = HAND_ID_RE.search(blocks[-1])
    if match:
        return match.group(1)
    # Header-less legacy files are rare; their first line is still a more
    # stable hand key than hashing actions appended during the hand.
    return blocks[-1].splitlines()[0].strip()


def extract_table_token(window_title: str) -> str:
    match = TABLE_TOKEN_RE.match((window_title or "").strip())
    if not match:
        return ""
    raw = match.group(1).strip()
    return raw.strip()
