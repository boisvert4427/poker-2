from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .history import read_history_text
from .parser import ParsedHand, parse_winamax_hand


@dataclass(slots=True)
class SnapshotHistoryTruth:
    hand_id: str
    table_name: str
    hero_name: str
    hero_cards: str
    big_blind: float
    hero_stack_bb: str
    pot_value_bb: str
    board_cards: list[str]
    players: list[dict[str, str]]
    positions: dict[str, dict[str, str]]
    dealer_owner: str


def truth_from_snapshot_metadata(metadata: dict[str, Any]) -> SnapshotHistoryTruth | None:
    live = metadata.get("live_snapshot") or {}
    hand_id = live.get("hand_id", "") or ""
    history_file = metadata.get("history_file", "") or ""
    if not hand_id or not history_file or not Path(history_file).exists():
        return None

    hand = _find_hand_in_history(history_file, hand_id)
    if hand is None:
        return None

    hero_stack_bb = _hero_stack_bb(hand)
    pot_value_bb = _pot_value_bb(hand)
    board_cards = _board_cards(hand)
    players = [seat for seat in hand.seats if seat.get("player") != hand.hero_name]
    positions = _position_map(hand)
    dealer_owner = _dealer_owner(hand, positions)

    return SnapshotHistoryTruth(
        hand_id=hand.hand_id,
        table_name=hand.table_name,
        hero_name=hand.hero_name,
        hero_cards=hand.hero_cards,
        big_blind=hand.big_blind,
        hero_stack_bb=hero_stack_bb,
        pot_value_bb=pot_value_bb,
        board_cards=board_cards,
        players=players,
        positions=positions,
        dealer_owner=dealer_owner,
    )


def _find_hand_in_history(history_file: str, hand_id: str) -> ParsedHand | None:
    raw = read_history_text(history_file)
    for chunk in raw.split("\n\n\n"):
        chunk = chunk.strip()
        if not chunk or hand_id not in chunk:
            continue
        hand = parse_winamax_hand(chunk)
        if hand.hand_id == hand_id:
            return hand
    return None


def _hero_stack_bb(hand: ParsedHand) -> str:
    if hand.big_blind <= 0:
        return ""
    for seat in hand.seats:
        if seat.get("player") == hand.hero_name:
            stack = seat.get("stack", "")
            if not stack:
                return ""
            value = float(stack) / hand.big_blind
            return _format_bb(value)
    return ""


def _pot_value_bb(hand: ParsedHand) -> str:
    if hand.big_blind <= 0 or hand.total_pot <= 0:
        return ""
    return _format_bb(hand.total_pot / hand.big_blind, prefix="Pot : ")


def _board_cards(hand: ParsedHand) -> list[str]:
    board = ""
    for key in ("summary", "river", "turn", "flop"):
        value = hand.board_by_street.get(key)
        if value:
            board = value
            break
    cards = [card.lower() for card in board.split()] if board else []
    while len(cards) < 5:
        cards.append("")
    return cards[:5]


def _format_bb(value: float, prefix: str = "") -> str:
    rounded = round(value, 1)
    if rounded.is_integer():
        text = str(int(rounded))
    else:
        text = f"{rounded:.1f}".replace(".", ",")
    return f"{prefix}{text} BB"


def _position_map(hand: ParsedHand) -> dict[str, dict[str, str]]:
    hero_seat = None
    seat_map = {int(seat["seat"]): seat for seat in hand.seats if seat.get("seat")}
    for seat in hand.seats:
        if seat.get("player") == hand.hero_name:
            hero_seat = int(seat["seat"])
            break
    if hero_seat is None:
        return {}

    def rel(offset: int) -> int:
        return ((hero_seat - 1 - offset) % 5) + 1

    mapping = {
        "hero": seat_map.get(hero_seat),
        "right": seat_map.get(rel(1)),
        "top_right": seat_map.get(rel(2)),
        "top_left": seat_map.get(rel(3)),
        "left": seat_map.get(rel(4)),
    }
    return {key: value for key, value in mapping.items() if value}


def _dealer_owner(hand: ParsedHand, positions: dict[str, dict[str, str]]) -> str:
    if hand.button_seat is None:
        return ""
    for position, seat in positions.items():
        if seat.get("seat") == str(hand.button_seat):
            return position if position != "hero" else hand.hero_name
    return ""
