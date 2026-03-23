from __future__ import annotations

import re
from dataclasses import dataclass, field


HEADER_RE = re.compile(
    r"Winamax Poker - (?P<game_type>.+?) - HandId: #(?P<hand_id>[\d-]+) - "
    r"(?P<variant>.+?) \((?P<sb>[\d.]+)/(?P<bb>[\d.]+)\) - (?P<played_at>.+)"
)
TABLE_RE = re.compile(r"Table: '(?P<table_name>.+?)' (?P<table_format>.+?) Seat #(?P<button>\d+) is the button")
SEAT_RE = re.compile(r"Seat (?P<seat>\d+): (?P<player>.+?) \((?P<stack>[\d.]+)\)")
DEALT_RE = re.compile(r"Dealt to (?P<hero>.+?) \[(?P<cards>.+)\]")
BOARD_RE = re.compile(r"\[(?P<cards>[^\]]+)\]")


@dataclass(slots=True)
class ParsedHand:
    hand_id: str = ""
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


def parse_winamax_hand(raw_text: str) -> ParsedHand:
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

        if line.startswith("*** ") and line.endswith(" ***"):
            current_street = line.strip("* ").replace("-", "_").replace("/", "_").lower()
            hand.current_street = current_street
            hand.streets.setdefault(current_street, [])
            board_match = BOARD_RE.search(line)
            if board_match and current_street in {"flop", "turn", "river"}:
                hand.board_by_street[current_street] = board_match.group("cards")
            continue

        if current_street == "summary":
            hand.summary.append(line)
        else:
            hand.streets.setdefault(current_street, []).append(line)

    hand.is_complete = bool(hand.summary)
    return hand
