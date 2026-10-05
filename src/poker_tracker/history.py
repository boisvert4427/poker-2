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
    snapshot_text: str | None = None


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
    raw = Path(path).read_bytes()
    # Winamax real-money histories are commonly written in Windows-1252
    # (the euro sign is a single byte), whereas older play-money files are
    # UTF-8.  Never silently replace bytes here: that broke the hand header
    # and prevented both seat names and actions from reaching the BDD.
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def freeze_history_file(history_file: object | None) -> HistoryFile | None:
    """Freeze history at capture time so later writes cannot alter analysis."""
    path = str(getattr(history_file, "path", "") or "")
    if not path:
        return None
    try:
        text = read_history_text(path)
    except (OSError, UnicodeError):
        text = ""
    return HistoryFile(
        path=path,
        last_modified=float(getattr(history_file, "last_modified", 0.0) or 0.0),
        size=int(getattr(history_file, "size", 0) or 0),
        snapshot_text=text,
    )


def table_layout_from_history(history_file: object | None) -> str | None:
    """Read the table capacity from the newest Winamax ``Table:`` line."""
    path = str(getattr(history_file, "path", history_file) or "")
    if not path:
        return None
    try:
        text = read_history_text(path)
    except (OSError, UnicodeError):
        return None
    matches = re.findall(
        r"^Table:\s*'.+?'\s+(\d+)\s*-?\s*max\b",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not matches:
        return None
    return {3: "3max", 5: "5max"}.get(int(matches[-1]))


def latest_hand_block_key(history_file: object | None) -> str:
    """Return a stable key for the last hand block in a Winamax history file."""
    path = getattr(history_file, "path", history_file)
    if not path:
        return ""
    text = getattr(history_file, "snapshot_text", None)
    if text is None:
        try:
            text = read_history_text(str(path))
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
    raw = (window_title or "").strip()
    if not raw or raw.lower() in {"winamax", "playground"}:
        return ""
    match = TABLE_TOKEN_RE.match(raw)
    if match:
        raw = match.group(1).strip()
    # Actual Winamax table captions look like
    # "Aalen 07 - 0,01-0,02 - No Limit Holdem". The history filename uses
    # only the first segment: ``..._Aalen 07_real_holdem_no-limit.txt``.
    return raw.split(" - ", 1)[0].strip()
