from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from PIL import Image, ImageFilter, ImageOps

from .config import load_calibration
from .ocr import OcrSnapshot, _find_tesseract, _run_tesseract, _scaled_rect, run_local_ocr_on_image


REVIEW_FIELDS = [
    "top_left_cards_visible",
    "top_left_name",
    "top_left_stack",
    "top_right_cards_visible",
    "top_right_name",
    "top_right_stack",
    "left_cards_visible",
    "left_name",
    "left_stack",
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
PLAYER_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_/-]{2,}")
POT_TEXT_RE = re.compile(r"(Pot(?:\s+total)?\s*:\s*[\d.,]+\s*BB)", re.IGNORECASE)
POT_TOTAL_TEXT_RE = re.compile(r"(Pot\s+total\s*:\s*[\d.,]+\s*BB)", re.IGNORECASE)
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
    name_rows = _extract_name_rows(ocr_snapshot.text, hero_name=live.get("hero_name", ""))
    stack_rows = _extract_stack_rows(ocr_snapshot.text)
    stack_candidates = _extract_stack_candidates(ocr_snapshot.text)
    def zone_text(name: str) -> str:
        return ((zones.get(name) or {}).text or "").strip() if zones.get(name) else ""

    def zone_image_path(name: str) -> str:
        return ((zones.get(name) or {}).image_path or "").strip() if zones.get(name) else ""

    board_text = zone_text("board")
    board_cards = _extract_board_cards_from_image(ocr_snapshot.image_path) or _extract_board_cards(board_text)
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
            _clean_player_name(zone_text("top_left_name")),
            _row_value(name_rows, 0, 0),
            _candidate_name(name_candidates, 0),
        ),
        "top_left_stack": first_non_empty(
            _extract_stack(zone_text("top_left_stack")),
            _candidate_value(stack_candidates, 0),
            _row_value(stack_rows, 0, 0),
            _extract_stack(top_left_opponent),
        ),
        "top_right_cards_visible": _detect_cards_visible(zone_image_path("top_right_cards")),
        "top_right_name": first_non_empty(
            _clean_player_name(zone_text("top_right_name")),
            _row_value(name_rows, 0, 1),
            _candidate_name(name_candidates, 1),
        ),
        "top_right_stack": first_non_empty(
            _extract_stack(zone_text("top_right_stack")),
            _candidate_value(stack_candidates, 1),
            _row_value(stack_rows, 0, 1),
        ),
        "left_cards_visible": _detect_cards_visible(zone_image_path("left_cards")),
        "left_name": first_non_empty(
            _clean_player_name(zone_text("left_name")),
            _row_value(name_rows, 1, 0),
            _clean_player_name(top_left_opponent),
            _candidate_name(name_candidates, 2),
        ),
        "left_stack": first_non_empty(
            _extract_stack(zone_text("left_stack")),
            _row_value(stack_rows, 1, 0),
            _candidate_value(stack_candidates, 2),
            _extract_stack(top_left_opponent),
        ),
        "right_cards_visible": _detect_cards_visible(zone_image_path("right_cards")),
        "right_name": first_non_empty(
            _clean_player_name(zone_text("right_name")),
            _row_value(name_rows, 1, 1),
            _clean_player_name(right_opponent),
            _candidate_name(name_candidates, 3),
        ),
        "right_stack": first_non_empty(
            _extract_stack(zone_text("right_stack")),
            _row_value(stack_rows, 1, 1),
            _candidate_value(stack_candidates, 3),
            _extract_stack(right_opponent),
        ),
        "hero_name": first_non_empty(
            hero_name_from_block,
            _clean_player_name(zone_text("hero_name")),
            live.get("hero_name", ""),
        ),
        "hero_stack": first_non_empty(
            hero_stack_from_block,
            _extract_stack(zone_text("hero_stack")),
        ),
        "hero_status": _clean_ocr_text(zone_text("hero_status")),
        "pot_value": first_non_empty(
            _extract_pot_value(zone_text("pot_value")),
            pot_from_block,
            _extract_pot_value(full_text),
            live.get("pot_text", ""),
        ),
        "dealer_button": first_non_empty(
            _detect_dealer_owner(ocr_snapshot.image_path),
            _clean_ocr_text(zone_text("dealer_button")),
        ),
        "board_card_1": board_cards[0] if len(board_cards) > 0 else "",
        "board_card_2": board_cards[1] if len(board_cards) > 1 else "",
        "board_card_3": board_cards[2] if len(board_cards) > 2 else "",
        "board_card_4": board_cards[3] if len(board_cards) > 3 else "",
        "board_card_5": board_cards[4] if len(board_cards) > 4 else "",
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
        local_field = (local_payload.get("fields", {}).get(field, {}) or {})
        openai_field = (openai_payload.get("fields", {}).get(field, {}) or {})
        local_value = _normalize_compare_value(local_field.get("value", ""))
        openai_value = _normalize_compare_value(openai_field.get("value", ""))
        matched = local_value == openai_value and bool(openai_value or local_value)
        local_box = local_field.get("box")
        openai_box = openai_field.get("box")
        comparison["fields"][field] = {
            "local": local_value,
            "openai": openai_value,
            "match": matched,
            "local_box": local_box,
            "openai_box": openai_box,
            "box_distance": _box_distance(local_box, openai_box),
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
        "left_cards_visible": "left_cards",
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

    if red_ratio > 0.78 and bright_ratio > 0.18 and dark_ratio < 0.20:
        return "visible"
    if dark_ratio > 0.45 or (red_ratio > 0.50 and bright_ratio < 0.18):
        return "not_visible"
    return "uncertain"


def _extract_board_cards(board_text: str) -> list[str]:
    cleaned = _clean_ocr_text(board_text).replace("10", "T").replace("O", "Q")
    rank_matches = [match.group(1).upper() for match in BOARD_RANK_RE.finditer(cleaned)]
    cards = [rank.lower() for rank in rank_matches[:5]]
    while len(cards) < 5:
        cards.append("")
    return cards


def _extract_board_cards_from_image(image_path: str) -> list[str]:
    image_file = Path(image_path)
    if not image_file.exists():
        return []

    try:
        image = Image.open(image_file).convert("RGB")
    except OSError:
        return []

    engine_path = _find_tesseract()
    if not engine_path:
        return []

    calibration = load_calibration().get("zones", {})
    cards: list[str] = []
    for index in range(1, 6):
        zone_name = f"board_card_{index}"
        ratios = calibration.get(zone_name)
        if not ratios:
            cards.append("")
            continue
        rect = _scaled_rect(image.width, image.height, *ratios)
        crop = image.crop(rect)
        rank = _extract_card_rank(crop, engine_path)
        suit = _extract_card_suit(crop)
        if rank and suit:
            cards.append(f"{rank}{suit}")
        elif rank:
            cards.append(rank)
        else:
            cards.append("")
    return cards


def _extract_card_rank(card_image: Image.Image, engine_path: str) -> str:
    rank_crop = card_image.crop((0, 0, max(1, int(card_image.width * 0.45)), max(1, int(card_image.height * 0.35))))
    processed = ImageOps.autocontrast(rank_crop.convert("L"))
    processed = processed.resize((processed.width * 4, processed.height * 4))
    processed = processed.filter(ImageFilter.SHARPEN)
    processed = processed.point(lambda p: 255 if p > 165 else 0)

    temp_dir = Path(Path.cwd()) / "tmp_board_rank"
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / "rank.png"
    processed.save(temp_path)

    completed = _run_tesseract(engine_path, str(temp_path), psm="10")
    text = (completed.stdout or "").strip().upper()
    text = text.replace("110", "10").replace("10.", "10").replace("1O", "10").replace("O", "Q")
    if text in {"10", "T"}:
        return "t"
    if text[:1] in {"A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"}:
        return "t" if text[0] == "T" else text[0].lower()
    return ""


def _extract_card_suit(card_image: Image.Image) -> str:
    pixels = list(card_image.getdata())
    total = max(1, len(pixels))
    red_ratio = sum(1 for r, g, b in pixels if r > 120 and r > g * 1.2 and r > b * 1.2) / total
    blue_ratio = sum(1 for r, g, b in pixels if b > 80 and b > r * 1.15 and b > g * 1.15) / total
    green_ratio = sum(1 for r, g, b in pixels if g > 80 and g > r * 1.1 and g > b * 1.05) / total
    dark_ratio = sum(1 for r, g, b in pixels if (r + g + b) / 3 < 60) / total

    if red_ratio > 0.12:
        return "h"
    if green_ratio > 0.15:
        return "c"
    if blue_ratio > 0.08:
        return "d"
    if dark_ratio > 0.18:
        return "s"
    return ""


def _detect_dealer_owner(image_path: str) -> str:
    image_file = Path(image_path)
    if not image_file.exists():
        return ""
    try:
        image = Image.open(image_file).convert("RGB")
    except OSError:
        return ""

    pixels = image.load()
    points: list[tuple[int, int]] = []
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = pixels[x, y]
            if r > 150 and g > 110 and 40 < b < 120 and r > g * 1.05:
                points.append((x, y))

    if len(points) < 20:
        return ""

    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)

    calibration = load_calibration().get("zones", {})
    seat_boxes = {
        "top_left": calibration.get("top_left_name"),
        "top_right": calibration.get("top_right_name"),
        "left": calibration.get("left_name"),
        "right": calibration.get("right_name"),
        "hero": calibration.get("hero_name"),
    }

    best_name = ""
    best_distance = None
    for seat_name, ratios in seat_boxes.items():
        if not ratios:
            continue
        rect = _scaled_rect(image.width, image.height, *ratios)
        seat_cx = (rect[0] + rect[2]) / 2
        seat_cy = (rect[1] + rect[3]) / 2
        distance = ((cx - seat_cx) ** 2 + (cy - seat_cy) ** 2) ** 0.5
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_name = seat_name
    return best_name


def _clean_ocr_text(value: str) -> str:
    return " ".join(part.strip() for part in value.splitlines() if part.strip()).strip()


def _normalize_card_value(value: str) -> str:
    token = _clean_ocr_text(value).lower().replace("10", "t")
    token = token.replace(" ", "")
    if len(token) >= 2 and token[0] in "a23456789tjqk" and token[1] in "shdc":
        return token[:2]
    return ""


def _normalize_compare_value(value: str) -> str:
    normalized = " ".join(str(value or "").strip().lower().split())
    card = _normalize_card_value(normalized)
    if card:
        return card
    if normalized.startswith("pot total :"):
        return normalized.replace("pot total :", "pot :").strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?\s*bb", normalized):
        return f"pot : {normalized}"
    return normalized


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
    candidates = []
    for token in cleaned.split():
        token = token.strip("~—-_=.,:;()[]{}<>")
        token = token.replace("|", "l")
        token = token.replace("/3", "73")
        token = token.replace("/", "7")
        token = _normalize_player_name(token)
        if PLAYER_NAME_RE.fullmatch(token):
            candidates.append(token)
    return " ".join(candidates[:2]).strip()


def _extract_pot_value(text: str) -> str:
    cleaned = _clean_ocr_text(text)
    total_match = POT_TOTAL_TEXT_RE.search(cleaned)
    if total_match:
        return total_match.group(1)
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


def _extract_name_rows(text: str, hero_name: str) -> list[list[str]]:
    rows: list[list[str]] = []
    hero_name = hero_name.lower().strip()
    for raw_line in text.splitlines():
        row: list[str] = []
        for token in raw_line.split():
            cleaned = _clean_player_name(token)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered == hero_name or lowered in NAME_BLACKLIST:
                continue
            row.append(cleaned)
        if len(row) >= 2:
            rows.append(row[:2])
    return rows


def _extract_stack_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_line in text.splitlines():
        cleaned = _clean_ocr_text(raw_line)
        stacks = [match.group(0) for match in STACK_RE.finditer(cleaned)]
        if len(stacks) >= 2:
            rows.append(stacks[:2])
            continue
        loose = []
        for match in BB_LIKE_RE.finditer(cleaned):
            amount = _normalize_bb_amount(match.group(1))
            if amount:
                loose.append(f"{amount} BB")
        if len(loose) >= 2:
            rows.append(loose[:2])
    return rows


def _extract_stack_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for match in BB_LIKE_RE.finditer(_clean_ocr_text(text)):
        amount = _normalize_bb_amount(match.group(1))
        if not amount:
            continue
        token = f"{amount} BB"
        if token not in candidates:
            candidates.append(token)
    return candidates


def _row_value(rows: list[list[str]], row_index: int, col_index: int) -> str:
    if 0 <= row_index < len(rows):
        row = rows[row_index]
        if 0 <= col_index < len(row):
            return row[col_index]
    return ""


def _candidate_value(values: list[str], index: int) -> str:
    return values[index] if 0 <= index < len(values) else ""


def _normalize_player_name(token: str) -> str:
    lowered = token.lower()
    if lowered.startswith("temivi"):
        return f"J{token[1:]}"
    return token


def _normalize_bb_amount(amount: str) -> str:
    value = amount.replace(",", ".")
    if value.endswith("68") and len(value) > 3 and "." not in value:
        value = value[:-2]
    if value.endswith("88") and len(value) > 3 and "." not in value:
        value = value[:-2]
    if value.endswith("."):
        value = value[:-1]
    return value.replace(".", ",") if "." in value else value


def _box_distance(left: Any, right: Any) -> float | None:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return None
    try:
        diffs = [
            abs(float(left["left"]) - float(right["left"])),
            abs(float(left["top"]) - float(right["top"])),
            abs(float(left["right"]) - float(right["right"])),
            abs(float(left["bottom"]) - float(right["bottom"])),
        ]
    except (KeyError, TypeError, ValueError):
        return None
    return round(sum(diffs) / 4, 4)
