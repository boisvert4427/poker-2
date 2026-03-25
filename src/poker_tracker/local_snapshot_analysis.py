from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from PIL import Image

from .history import read_history_text
from .history_truth import truth_from_snapshot_metadata
from .ocr import OcrSnapshot, run_local_ocr_on_image
from .parser import parse_winamax_hand


REVIEW_FIELDS = [
    "top_left_cards_visible",
    "top_left_name",
    "top_left_stack",
    "top_right_cards_visible",
    "top_right_name",
    "top_right_stack",
    "right_cards_visible",
    "right_name",
    "right_stack",
    "hero_name",
    "hero_stack",
    "hero_status",
    "pot_value",
    "dealer_button",
    "board_card_1",
    "board_card_2",
    "board_card_3",
    "board_card_4",
    "board_card_5",
]

STACK_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*BB\b", re.IGNORECASE)
PLAYER_NAME_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_]{2,}\b")
POT_TEXT_RE = re.compile(r"(Pot(?:\s+total)?\s*:\s*[\d.,]+\s*BB)", re.IGNORECASE)
BOARD_RANK_RE = re.compile(r"\b([2-9]|10|[AJQKT])\b", re.IGNORECASE)
BB_LIKE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:BB|B8|68|BES)\b", re.IGNORECASE)
POT_LOOSE_RE = re.compile(r"pot[^0-9]{0,10}(\d+(?:[.,]\d+)?)", re.IGNORECASE)
NAME_BLACKLIST = {
    "winamax", "wichita", "holdem", "limit", "playground", "free", "move", "straight",
    "all-in", "autorebuy", "attendre", "tour", "poser", "blind", "side", "pots", "pot",
    "patiente", "cartes", "small", "big", "no", "cashgame",
}


def analyze_snapshot_image(
    image_path: str | Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = run_local_ocr_on_image(image_path)
    fields = extract_review_values(snapshot, metadata or {})
    payload = {
        "image_path": str(image_path),
        "ocr_status": snapshot.status,
        "fields": fields,
        "zones": {
            name: {
                "text": zone.text,
                "rect": list(zone.rect),
                "image_path": zone.image_path,
            }
            for name, zone in snapshot.zones.items()
        },
    }
    return payload


def extract_review_values(ocr_snapshot: OcrSnapshot, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    live = metadata.get("live_snapshot") or {}
    zones = ocr_snapshot.zones or {}
    full_text = _clean_ocr_text(ocr_snapshot.text)
    name_candidates = _extract_name_candidates(ocr_snapshot.text, hero_name=live.get("hero_name", ""))
    history_hand = _load_matched_history_hand(metadata)
    history_truth = truth_from_snapshot_metadata(metadata)

    def zone_text(name: str) -> str:
        return ((zones.get(name) or {}).text or "").strip() if zones.get(name) else ""

    def zone_image_path(name: str) -> str:
        return ((zones.get(name) or {}).image_path or "").strip() if zones.get(name) else ""

    board_text = zone_text("board")
    board_cards = _extract_board_cards(board_text)
    hero_block = _clean_ocr_text(zone_text("hero"))
    hero_name_from_block = _extract_hero_name(hero_block)
    hero_stack_from_block = _extract_stack(hero_block)
    pot_from_block = _extract_pot_value(_clean_ocr_text(zone_text("pot")))
    top_left_opponent = _clean_ocr_text(zone_text("left_opponent"))
    right_opponent = _clean_ocr_text(zone_text("right_opponent"))

    def first_non_empty(*values: str) -> str:
        for value in values:
            if value and value != "-":
                return value
        return ""

    values = {
        "top_left_cards_visible": _detect_cards_visible(zone_image_path("top_left_cards")),
        "top_left_name": first_non_empty(
            _history_position_name(history_truth, "top_left"),
            _clean_player_name(zone_text("top_left_name")),
            _clean_player_name(top_left_opponent),
            _candidate_name(name_candidates, 0),
        ),
        "top_left_stack": first_non_empty(
            _history_position_stack(history_truth, "top_left"),
            _extract_stack(zone_text("top_left_stack")),
            _extract_stack(top_left_opponent),
        ),
        "top_right_cards_visible": _detect_cards_visible(zone_image_path("top_right_cards")),
        "top_right_name": first_non_empty(
            _history_position_name(history_truth, "top_right"),
            _clean_player_name(zone_text("top_right_name")),
        ),
        "top_right_stack": first_non_empty(
            _history_position_stack(history_truth, "top_right"),
            _extract_stack(zone_text("top_right_stack")),
        ),
        "right_cards_visible": _detect_cards_visible(zone_image_path("right_cards")),
        "right_name": first_non_empty(
            _history_position_name(history_truth, "right"),
            _clean_player_name(zone_text("right_name")),
            _clean_player_name(right_opponent),
            _candidate_name(name_candidates, 1),
        ),
        "right_stack": first_non_empty(
            _history_position_stack(history_truth, "right"),
            _extract_stack(zone_text("right_stack")),
            _extract_stack(right_opponent),
        ),
        "hero_name": first_non_empty(
            history_hand.hero_name if history_hand else "",
            hero_name_from_block,
            _clean_player_name(zone_text("hero_name")),
            live.get("hero_name", ""),
        ),
        "hero_stack": first_non_empty(
            _history_hero_stack_bb(history_hand),
            hero_stack_from_block,
            _extract_stack(zone_text("hero_stack")),
        ),
        "hero_status": _clean_ocr_text(zone_text("hero_status")),
        "pot_value": first_non_empty(
            history_truth.pot_value_bb if history_truth and live.get("is_complete") else "",
            pot_from_block,
            _extract_pot_value(zone_text("pot_value")),
            _extract_pot_value(full_text),
            live.get("pot_text", ""),
        ),
        "dealer_button": first_non_empty(
            history_truth.dealer_owner if history_truth and live.get("is_complete") else "",
            _clean_ocr_text(zone_text("dealer_button")),
        ),
        "board_card_1": (_history_board_card(history_truth, 0) if history_truth and live.get("is_complete") else "") or (board_cards[0] if len(board_cards) > 0 else ""),
        "board_card_2": (_history_board_card(history_truth, 1) if history_truth and live.get("is_complete") else "") or (board_cards[1] if len(board_cards) > 1 else ""),
        "board_card_3": (_history_board_card(history_truth, 2) if history_truth and live.get("is_complete") else "") or (board_cards[2] if len(board_cards) > 2 else ""),
        "board_card_4": (_history_board_card(history_truth, 3) if history_truth and live.get("is_complete") else "") or (board_cards[3] if len(board_cards) > 3 else ""),
        "board_card_5": (_history_board_card(history_truth, 4) if history_truth and live.get("is_complete") else "") or (board_cards[4] if len(board_cards) > 4 else ""),
    }

    result: dict[str, dict[str, Any]] = {}
    for field, value in values.items():
        zone_name = _zone_for_field(field)
        zone = zones.get(zone_name)
        result[field] = {
            "value": value,
            "visible": bool(value and value != "-"),
            "box": _rect_to_ratio(zone.rect, ocr_snapshot.image_path) if zone else None,
        }
    return result


def compare_local_to_openai(local_payload: dict[str, Any], openai_payload: dict[str, Any]) -> dict[str, Any]:
    comparison: dict[str, Any] = {"fields": {}, "matches": 0, "total": 0}
    for field in REVIEW_FIELDS:
        local_value = _normalize_compare_value((local_payload.get("fields", {}).get(field, {}) or {}).get("value", ""))
        openai_value = _normalize_compare_value((openai_payload.get("fields", {}).get(field, {}) or {}).get("value", ""))
        matched = local_value == openai_value and bool(openai_value or local_value)
        comparison["fields"][field] = {
            "local": local_value,
            "openai": openai_value,
            "match": matched,
        }
        comparison["total"] += 1
        if matched:
            comparison["matches"] += 1
    comparison["accuracy"] = round(comparison["matches"] / comparison["total"], 3) if comparison["total"] else 0.0
    return comparison


def save_local_analysis(image_path: str | Path, metadata: dict[str, Any] | None = None) -> Path:
    image_path = Path(image_path)
    payload = analyze_snapshot_image(image_path, metadata=metadata)
    target = image_path.with_suffix(".local.json")
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def _zone_for_field(field: str) -> str:
    mapping = {
        "top_left_cards_visible": "top_left_cards",
        "top_right_cards_visible": "top_right_cards",
        "right_cards_visible": "right_cards",
    }
    return mapping.get(field, field)


def _rect_to_ratio(rect: tuple[int, int, int, int], image_path: str) -> dict[str, float] | None:
    try:
        width, height = Image.open(image_path).size
    except OSError:
        return None
    left, top, right, bottom = rect
    return {
        "left": round(left / width, 4),
        "top": round(top / height, 4),
        "right": round(right / width, 4),
        "bottom": round(bottom / height, 4),
    }


def _detect_cards_visible(image_path: str) -> str:
    if not image_path or not Path(image_path).exists():
        return "-"
    try:
        image = Image.open(image_path).convert("RGB")
    except OSError:
        return "-"

    pixels = list(image.getdata())
    total = max(1, len(pixels))
    red_ratio = sum(1 for r, g, b in pixels if r > 120 and r > g * 1.2 and r > b * 1.2) / total
    bright_ratio = sum(1 for r, g, b in pixels if (r + g + b) / 3 > 160) / total
    dark_ratio = sum(1 for r, g, b in pixels if (r + g + b) / 3 < 40) / total

    if red_ratio > 0.06 or bright_ratio > 0.20:
        return "visible"
    if dark_ratio > 0.70:
        return "not_visible"
    return "uncertain"


def _extract_board_cards(board_text: str) -> list[str]:
    cleaned = _clean_ocr_text(board_text).replace("10", "T").replace("O", "Q")
    rank_matches = [match.group(1).upper() for match in BOARD_RANK_RE.finditer(cleaned)]
    cards = [rank.lower() for rank in rank_matches[:5]]
    while len(cards) < 5:
        cards.append("")
    return cards


def _clean_ocr_text(value: str) -> str:
    return " ".join(part.strip() for part in value.splitlines() if part.strip()).strip()


def _normalize_card_value(value: str) -> str:
    token = _clean_ocr_text(value).lower().replace("10", "t")
    token = token.replace(" ", "")
    if len(token) >= 2 and token[0] in "a23456789tjqk" and token[1] in "shdc":
        return token[:2]
    return ""


def _normalize_compare_value(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _extract_stack(text: str) -> str:
    cleaned = _clean_ocr_text(text)
    match = STACK_RE.search(cleaned)
    return match.group(0) if match else ""


def _extract_hero_name(text: str) -> str:
    cleaned = _clean_ocr_text(text)
    for token in cleaned.split():
        if token.lower() == "wa":
            continue
        if token.lower().endswith("bb"):
            continue
        if PLAYER_NAME_RE.fullmatch(token):
            return token
    return ""


def _clean_player_name(text: str) -> str:
    cleaned = _clean_ocr_text(text)
    candidates = [token for token in cleaned.split() if PLAYER_NAME_RE.fullmatch(token)]
    return " ".join(candidates[:2]).strip()


def _extract_pot_value(text: str) -> str:
    cleaned = _clean_ocr_text(text)
    match = POT_TEXT_RE.search(cleaned)
    if match:
        return match.group(1)
    loose_match = POT_LOOSE_RE.search(cleaned)
    if loose_match:
        amount = _normalize_bb_amount(loose_match.group(1))
        if amount:
            return f"Pot : {amount} BB"
    stack_match = STACK_RE.search(cleaned)
    if stack_match:
        return stack_match.group(0)
    bb_like = BB_LIKE_RE.search(cleaned)
    if bb_like:
        amount = _normalize_bb_amount(bb_like.group(1))
        if amount:
            return f"{amount} BB"
    return ""


def _extract_name_candidates(text: str, hero_name: str) -> list[str]:
    candidates: list[str] = []
    for raw_line in text.splitlines():
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]+|\d+", raw_line)
        filtered = [token for token in tokens if token.lower() not in NAME_BLACKLIST]
        if not filtered:
            continue
        joined = " ".join(filtered)
        if joined.lower() == hero_name.lower():
            continue
        if len(filtered) >= 2 and filtered[0].isalpha() and filtered[1].isdigit() and len(filtered[0]) >= 4:
            candidate = f"{filtered[0]} {filtered[1]}"
            if candidate.lower() != hero_name.lower() and candidate not in candidates:
                candidates.append(candidate)
            continue
        if len(filtered) == 1 and filtered[0].isalpha() and len(filtered[0]) >= 4:
            candidate = filtered[0]
            if candidate.lower() != hero_name.lower() and candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _candidate_name(candidates: list[str], index: int) -> str:
    return candidates[index] if 0 <= index < len(candidates) else ""


def _normalize_bb_amount(amount: str) -> str:
    value = amount.replace(",", ".")
    if value.endswith("68") and len(value) > 3 and "." not in value:
        value = value[:-2]
    if value.endswith("88") and len(value) > 3 and "." not in value:
        value = value[:-2]
    if value.endswith("."):
        value = value[:-1]
    return value.replace(".", ",") if "." in value else value


def _load_matched_history_hand(metadata: dict[str, Any]):
    history_file = metadata.get("history_file", "")
    live = metadata.get("live_snapshot") or {}
    hand_id = live.get("hand_id", "") or ""
    if not history_file or not hand_id or not Path(history_file).exists():
        return None
    raw = read_history_text(history_file)
    for chunk in raw.split("\n\n\n"):
        chunk = chunk.strip()
        if not chunk or hand_id not in chunk:
            continue
        hand = parse_winamax_hand(chunk)
        if hand.hand_id == hand_id:
            return hand
    return None


def _history_position_name(truth, position: str) -> str:
    if truth is None:
        return ""
    seat = truth.positions.get(position, {})
    return seat.get("player", "")


def _history_position_stack(truth, position: str) -> str:
    if truth is None:
        return ""
    seat = truth.positions.get(position, {})
    stack = seat.get("stack", "")
    if not stack or truth.big_blind <= 0:
        return ""
    try:
        value = float(stack) / truth.big_blind
    except ValueError:
        return ""
    return f"{_format_bb_value(value)} BB"


def _history_hero_stack_bb(hand) -> str:
    if hand is None:
        return ""
    for seat in hand.seats:
        if seat.get("player") == hand.hero_name:
            stack = seat.get("stack", "")
            return _stack_to_bb(hand, stack)
    return ""


def _history_board_card(truth, index: int) -> str:
    if truth is None:
        return ""
    if 0 <= index < len(truth.board_cards):
        return truth.board_cards[index]
    return ""


def _stack_to_bb(hand, stack: str) -> str:
    if hand is None or not stack or hand.big_blind <= 0:
        return ""
    value = float(stack) / hand.big_blind
    return f"{_format_bb_value(value)} BB"


def _format_bb_value(value: float) -> str:
    rounded = round(value, 1)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.1f}".replace(".", ",")
