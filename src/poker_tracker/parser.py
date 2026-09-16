from __future__ import annotations

import re
from dataclasses import dataclass, field


HEADER_RE = re.compile(
    r"Winamax Poker - (?P<game_type>.+?) - HandId: #(?P<hand_id>[\d-]+) - "
    r"(?P<variant>.+?) \((?P<sb>[\d.]+)(?:\s*[€$£])?\s*/\s*(?P<bb>[\d.]+)(?:\s*[€$£])?\) - (?P<played_at>.+)"
)
TABLE_RE = re.compile(r"Table: '(?P<table_name>.+?)' (?P<table_format>.+?) Seat #(?P<button>\d+) is the button")
SEAT_RE = re.compile(r"Seat (?P<seat>\d+): (?P<player>.+?) \((?P<stack>[\d.]+)(?:\s*[€$£])?\)")
DEALT_RE = re.compile(r"Dealt to (?P<hero>.+?) \[(?P<cards>.+)\]")
BOARD_RE = re.compile(r"\[(?P<cards>[^\]]+)\]")
SUMMARY_BOARD_RE = re.compile(r"^Board:\s+\[(?P<cards>[^\]]+)\]")
TOTAL_POT_RE = re.compile(r"^Total pot\s+(?P<pot>[\d.]+)(?:\s*[€$£])?")
HAND_START_RE = re.compile(r"^Winamax Poker - .+? - HandId: #", re.MULTILINE)


@dataclass(slots=True)
class ParsedHand:
    hand_id: str = ""
    source_file: str = ""
    game_type: str = ""
    variant: str = ""
    small_blind: float = 0.0
    big_blind: float = 0.0
    played_at: str = ""
    table_name: str = ""
    table_format: str = ""
    button_seat: int | None = None
    hero_name: str = ""
    hero_cards: str = ""
    seats: list[dict[str, str]] = field(default_factory=list)
    streets: dict[str, list[str]] = field(default_factory=dict)
    summary: list[str] = field(default_factory=list)
    board_by_street: dict[str, str] = field(default_factory=dict)
    current_street: str = ""
    is_complete: bool = False
    total_pot: float = 0.0


def split_winamax_hands(raw_text: str) -> list[str]:
    """Split a Winamax history file using hand headers, not blank lines."""
    starts = [match.start() for match in HAND_START_RE.finditer(raw_text)]
    if not starts:
        stripped = raw_text.strip()
        return [stripped] if stripped else []
    chunks: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(raw_text)
        chunk = raw_text[start:end].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def parse_winamax_hand(raw_text: str) -> ParsedHand:
    # Some callers provide a complete daily history file. In that case the
    # live view must parse only the newest hand instead of merging every hand.
    chunks = split_winamax_hands(raw_text)
    if chunks:
        raw_text = chunks[-1]
    lines = [line.rstrip() for line in raw_text.splitlines() if line.strip()]
    hand = ParsedHand(streets={}, board_by_street={})
    current_street = "meta"

    for line in lines:
        if not hand.hand_id:
            header_match = HEADER_RE.match(line)
            if header_match:
                hand.hand_id = header_match.group("hand_id")
                hand.game_type = header_match.group("game_type")
                hand.variant = header_match.group("variant")
                hand.small_blind = float(header_match.group("sb"))
                hand.big_blind = float(header_match.group("bb"))
                hand.played_at = header_match.group("played_at")
                continue

        if not hand.table_name:
            table_match = TABLE_RE.match(line)
            if table_match:
                hand.table_name = table_match.group("table_name")
                hand.table_format = table_match.group("table_format")
                hand.button_seat = int(table_match.group("button"))
                continue

        seat_match = SEAT_RE.match(line)
        if seat_match:
            hand.seats.append(
                {
                    "seat": seat_match.group("seat"),
                    "player": seat_match.group("player"),
                    "stack": seat_match.group("stack"),
                }
            )
            continue

        dealt_match = DEALT_RE.match(line)
        if dealt_match:
            hand.hero_name = dealt_match.group("hero")
            hand.hero_cards = dealt_match.group("cards")
            continue

        if line.startswith("*** "):
            marker_end = line.find("***", 4)
            if marker_end < 0:
                continue
            street_label = line[4:marker_end].strip()
            current_street = street_label.replace("-", "_").replace("/", "_").lower()
            hand.current_street = current_street
            hand.streets.setdefault(current_street, [])
            board_parts = BOARD_RE.findall(line[marker_end + 3 :])
            if board_parts and current_street in {"flop", "turn", "river"}:
                hand.board_by_street[current_street] = " ".join(
                    " ".join(board_parts).split()
                )
            continue

        if current_street == "summary":
            hand.summary.append(line)
            summary_board_match = SUMMARY_BOARD_RE.match(line)
            if summary_board_match:
                hand.board_by_street["summary"] = summary_board_match.group("cards")
            total_pot_match = TOTAL_POT_RE.match(line)
            if total_pot_match:
                hand.total_pot = float(total_pot_match.group("pot"))
        else:
            hand.streets.setdefault(current_street, []).append(line)

    hand.is_complete = bool(hand.summary)
    return hand
