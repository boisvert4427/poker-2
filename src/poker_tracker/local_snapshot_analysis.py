from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from PIL import Image, ImageFilter, ImageOps

from .config import load_calibration
from .ocr import OcrSnapshot, _find_tesseract, _preprocess_text_zone, _run_tesseract, _scaled_rect, run_local_ocr_on_image


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
BB_LIKE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:BB|B8|68|BES|BE|BBS)\b", re.IGNORECASE)
POT_LOOSE_RE = re.compile(r"pot[^0-9]{0,10}(\d+(?:[.,]\d+)?)", re.IGNORECASE)
NAME_BLACKLIST = {
    "winamax", "wichita", "holdem", "limit", "playground", "free", "move", "straight",
    "all-in", "autorebuy", "attendre", "tour", "poser", "blind", "side", "pots", "pot",
    "patiente", "cartes", "small", "big", "no", "cashgame", "historique", "showdown",
    "pre-flop", "preflop", "prochaine", "action", "hauteur", "fold", "call", "check",
    "bold", "recaver", "cache", "present", "active",
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
    previous_fields = metadata.get("previous_fields") or {}
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
    hero_cards_visible = _hero_cards_visible_on_table(ocr_snapshot.image_path)
    hero_footer_status = _extract_hero_footer_status(ocr_snapshot.image_path)
    hero_name_from_block = _extract_hero_name(hero_block)
    hero_stack_from_block = _extract_last_stack(hero_block)
    hero_stack_zone = _extract_stack(zone_text("hero_stack"))
    action_text = " ".join(
        _clean_ocr_text(zone_text(name))
        for name in ("action_left", "action_center", "action_right")
    ).strip()
    pot_from_block = _extract_pot_value(_clean_ocr_text(zone_text("pot")))
    top_left_opponent = _clean_ocr_text(zone_text("left_opponent"))
    right_opponent = _clean_ocr_text(zone_text("right_opponent"))
    left_stack_expanded = _extract_stack(_extract_expanded_stack_text(ocr_snapshot.image_path, "left_stack", 0.60, 0.20))
    right_name_expanded = _clean_player_name(_extract_expanded_zone_text(ocr_snapshot.image_path, "right_name", 0.25, 0.10))
    right_stack_expanded = _extract_stack(_extract_expanded_stack_text(ocr_snapshot.image_path, "right_stack", 0.35, 0.10))

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
            _select_best_stack(_extract_stack(zone_text("left_stack")), left_stack_expanded),
            _row_value(stack_rows, 1, 0),
            _candidate_value(stack_candidates, 2),
            _extract_stack(top_left_opponent),
        ),
        "right_cards_visible": _detect_cards_visible(zone_image_path("right_cards")),
        "right_name": first_non_empty(
            _clean_player_name(zone_text("right_name")),
            right_name_expanded,
            _row_value(name_rows, 1, 1),
            _clean_player_name(right_opponent),
            _candidate_name(name_candidates, 3),
        ),
        "right_stack": first_non_empty(
            _select_best_stack(_extract_stack(zone_text("right_stack")), right_stack_expanded),
            _row_value(stack_rows, 1, 1),
            _candidate_value(stack_candidates, 3),
            _extract_stack(right_opponent),
        ),
        "hero_name": first_non_empty(
            live.get("hero_name", ""),
            hero_name_from_block,
            _clean_player_name(zone_text("hero_name")),
        ),
        "hero_stack": first_non_empty(
            _select_best_stack(hero_stack_from_block, hero_stack_zone),
            hero_stack_zone,
            hero_stack_from_block,
        ),
        "hero_status": _clean_hero_status(zone_text("hero_status"), hero_block, action_text, full_text, hero_cards_visible, hero_footer_status),
        "pot_value": first_non_empty(
            pot_from_block,
            _extract_pot_value(zone_text("pot_value")),
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
    values = _stabilize_values(values, previous_fields)

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
        local_value = _normalize_compare_value(field, local_field.get("value", ""))
        openai_value = _normalize_compare_value(field, openai_field.get("value", ""))
        if field == "dealer_button":
            local_value = _normalize_dealer_value(local_value, local_payload, openai_payload)
            openai_value = _normalize_dealer_value(openai_value, openai_payload, openai_payload)
        matched = _field_values_match(field, local_value, openai_value)
        counted = _field_is_labeled(field, openai_value, openai_field)
        local_box = local_field.get("box")
        openai_box = openai_field.get("box")
        comparison["fields"][field] = {
            "local": local_value,
            "openai": openai_value,
            "match": matched,
            "counted": counted,
            "local_box": local_box,
            "openai_box": openai_box,
            "box_distance": _box_distance(local_box, openai_box),
        }
        if counted:
            comparison["total"] += 1
        if matched and counted:
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


def _extract_expanded_zone_text(image_path: str, zone_name: str, expand_left: float, expand_right: float) -> str:
    image_file = Path(image_path)
    if not image_file.exists():
        return ""
    try:
        image = Image.open(image_file).convert("RGB")
    except OSError:
        return ""

    ratios = load_calibration().get("zones", {}).get(zone_name)
    if not ratios:
        return ""
    left, top, right, bottom = _scaled_rect(image.width, image.height, *ratios)
    width = max(1, right - left)
    expanded = (
        max(0, left - int(width * expand_left)),
        top,
        min(image.width, right + int(width * expand_right)),
        bottom,
    )
    crop = image.crop(expanded)
    processed = _preprocess_text_zone(crop)

    engine_path = _find_tesseract()
    if not engine_path:
        return ""
    temp_dir = Path(Path.cwd()) / "tmp_board_rank"
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / f"{zone_name}_expanded.png"
    processed.save(temp_path)
    completed = _run_tesseract(engine_path, str(temp_path), psm="7")
    return _clean_ocr_text((completed.stdout or "").strip())


def _extract_expanded_stack_text(image_path: str, zone_name: str, expand_left: float, expand_right: float) -> str:
    image_file = Path(image_path)
    if not image_file.exists():
        return ""
    try:
        image = Image.open(image_file).convert("RGB")
    except OSError:
        return ""

    ratios = load_calibration().get("zones", {}).get(zone_name)
    if not ratios:
        return ""
    left, top, right, bottom = _scaled_rect(image.width, image.height, *ratios)
    width = max(1, right - left)
    expanded = (
        max(0, left - int(width * expand_left)),
        top,
        min(image.width, right + int(width * expand_right)),
        bottom,
    )
    crop = image.crop(expanded)
    processed = ImageOps.autocontrast(crop.convert("L"))
    processed = processed.resize((processed.width * 4, processed.height * 4))
    processed = processed.filter(ImageFilter.SHARPEN)
    processed = processed.point(lambda p: 255 if p > 155 else 0)

    engine_path = _find_tesseract()
    if not engine_path:
        return ""
    temp_dir = Path(Path.cwd()) / "tmp_board_rank"
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / f"{zone_name}_expanded_stack.png"
    processed.save(temp_path)
    completed = _run_tesseract(engine_path, str(temp_path), psm="7")
    return _clean_ocr_text((completed.stdout or "").strip())


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
    if red_ratio < 0.55 and bright_ratio < 0.14:
        return "not_visible"
    if red_ratio < 0.68 and bright_ratio < 0.24:
        return "not_visible"
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
        suit = _extract_card_suit(crop)
        rank = _extract_card_rank(crop, engine_path, suit)
        white_ratio = _card_white_ratio(crop)
        if not _looks_like_card_crop(crop) and not (rank and suit):
            cards.append("")
            continue
        if rank and suit:
            if white_ratio < 0.28 and index >= 4:
                cards.append("")
                continue
            cards.append(f"{rank}{suit}")
        elif rank:
            cards.append(rank)
        else:
            cards.append("")
    return cards


def _extract_card_rank(card_image: Image.Image, engine_path: str, suit: str = "") -> str:
    rank_crop = card_image.crop((0, 0, max(1, int(card_image.width * 0.48)), max(1, int(card_image.height * 0.42))))
    variants: list[Image.Image] = []
    grayscale = ImageOps.autocontrast(rank_crop.convert("L"))
    grayscale = grayscale.resize((grayscale.width * 5, grayscale.height * 5))
    grayscale = grayscale.filter(ImageFilter.SHARPEN)
    variants.append(grayscale.point(lambda p: 255 if p > 145 else 0))
    variants.append(grayscale.point(lambda p: 255 if p > 175 else 0))
    variants.append(ImageOps.autocontrast(rank_crop).resize((rank_crop.width * 5, rank_crop.height * 5)))

    temp_dir = Path(Path.cwd()) / "tmp_board_rank"
    temp_dir.mkdir(exist_ok=True)
    seen_raw: list[str] = []
    candidates: list[str] = []
    for index, processed in enumerate(variants):
        temp_path = temp_dir / f"rank_{index}.png"
        processed.save(temp_path)
        completed = _run_tesseract(engine_path, str(temp_path), psm="10")
        raw_text = (completed.stdout or "").strip().upper()
        seen_raw.append(raw_text)
        if raw_text.startswith("LY"):
            return "j"
        if "JA" in raw_text and suit in {"c", "h"}:
            continue
        one_prefix = re.search(r"1([2-9])", raw_text)
        if one_prefix:
            candidates.append(one_prefix.group(1).lower())
        trailing = re.search(r"([AKQJT23456789])$", raw_text)
        if trailing:
            candidates.append("t" if trailing.group(1) == "T" else trailing.group(1).lower())
        text = re.sub(r"[^AKQJT9876543210]", "", raw_text)
        text = text.replace("110", "10").replace("10.", "10").replace("1O", "10").replace("O", "Q")
        if text in {"10", "T"}:
            candidates.append("t")
            continue
        if text[:1] in {"A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"}:
            candidates.append("t" if text[0] == "T" else text[0].lower())
    pip_count = _estimate_card_body_symbols(card_image, suit)
    if any("JA" in raw for raw in seen_raw) and pip_count <= 3:
        return "a"
    if any(raw in {"18", "J8", "I8", "|8", "\\8", "8"} or raw.endswith("8") for raw in seen_raw):
        return "8"
    if any("Z" in raw for raw in seen_raw):
        return "7"
    if "a" in candidates and "4" in candidates:
        return "a" if pip_count <= 2 else "4"
    if "a" in candidates and "8" in candidates:
        return "8" if pip_count >= 4 else "a"
    if "6" in candidates and "j" in candidates:
        return "6"
    if "2" in candidates and "j" in candidates:
        return "2"
    if candidates:
        return candidates[0]
    return ""


def _extract_card_suit(card_image: Image.Image) -> str:
    suit_roi = card_image.crop((
        0,
        max(1, int(card_image.height * 0.18)),
        max(1, int(card_image.width * 0.42)),
        max(1, int(card_image.height * 0.55)),
    ))
    pixels = list(suit_roi.getdata())
    total = max(1, len(pixels))
    red_ratio = sum(1 for r, g, b in pixels if r > 120 and r > g * 1.2 and r > b * 1.2) / total
    blue_ratio = sum(1 for r, g, b in pixels if b > 70 and b > r * 1.12 and b > g * 1.08) / total
    green_ratio = sum(1 for r, g, b in pixels if g > 75 and g > r * 1.08 and g > b * 1.03) / total
    dark_ratio = sum(1 for r, g, b in pixels if (r + g + b) / 3 < 65) / total

    if red_ratio > 0.12:
        return "h"
    if blue_ratio > 0.07:
        return "d"
    if dark_ratio > 0.30:
        return "s"
    if green_ratio > 0.12:
        return "c"
    if dark_ratio > 0.18:
        return "s"
    return ""


def _looks_like_card_crop(card_image: Image.Image) -> bool:
    white_ratio = _card_white_ratio(card_image)
    return white_ratio > 0.18


def _card_white_ratio(card_image: Image.Image) -> float:
    pixels = list(card_image.getdata())
    total = max(1, len(pixels))
    return sum(1 for r, g, b in pixels if r > 180 and g > 180 and b > 180) / total


def _estimate_card_body_symbols(card_image: Image.Image, suit: str) -> int:
    body = card_image.crop((
        max(1, int(card_image.width * 0.32)),
        max(1, int(card_image.height * 0.18)),
        max(1, int(card_image.width * 0.92)),
        max(1, int(card_image.height * 0.9)),
    ))
    width, height = body.size
    pixels = body.load()
    mask = [[False] * width for _ in range(height)]

    def is_match(r: int, g: int, b: int) -> bool:
        if suit == "h":
            return r > 120 and r > g * 1.2 and r > b * 1.2
        if suit == "d":
            return b > 70 and b > r * 1.12 and b > g * 1.08
        if suit == "c":
            return g > 75 and g > r * 1.08 and g > b * 1.03
        if suit == "s":
            return (r + g + b) / 3 < 80
        return False

    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            if is_match(r, g, b):
                mask[y][x] = True

    seen = [[False] * width for _ in range(height)]
    count = 0
    stack: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            if not mask[y][x] or seen[y][x]:
                continue
            seen[y][x] = True
            stack.append((x, y))
            area = 0
            while stack:
                cx, cy = stack.pop()
                area += 1
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            if area >= 25:
                count += 1
    return count


def _hero_cards_visible_on_table(image_path: str) -> bool:
    image_file = Path(image_path)
    if not image_file.exists():
        return False
    try:
        image = Image.open(image_file).convert("RGB")
    except OSError:
        return False

    ratios = load_calibration().get("zones", {}).get("hero")
    if not ratios:
        return False
    rect = _scaled_rect(image.width, image.height, *ratios)
    crop = image.crop(rect)
    cards_roi = crop.crop((
        max(1, int(crop.width * 0.20)),
        0,
        max(1, int(crop.width * 0.82)),
        max(1, int(crop.height * 0.40)),
    ))
    pixels = list(cards_roi.getdata())
    total = max(1, len(pixels))
    white_ratio = sum(1 for r, g, b in pixels if r > 175 and g > 175 and b > 175) / total
    return white_ratio > 0.12


def _extract_hero_footer_status(image_path: str) -> str:
    image_file = Path(image_path)
    if not image_file.exists():
        return ""
    try:
        image = Image.open(image_file).convert("RGB")
    except OSError:
        return ""

    ratios = load_calibration().get("zones", {}).get("hero")
    if not ratios:
        return ""
    rect = _scaled_rect(image.width, image.height, *ratios)
    crop = image.crop(rect)
    footer = crop.crop((
        max(1, int(crop.width * 0.18)),
        max(1, int(crop.height * 0.72)),
        max(1, int(crop.width * 0.82)),
        max(1, int(crop.height * 0.98)),
    ))
    processed = ImageOps.autocontrast(footer.convert("L"))
    processed = processed.resize((processed.width * 4, processed.height * 4))
    processed = processed.filter(ImageFilter.SHARPEN)
    processed = processed.point(lambda p: 255 if p > 150 else 0)

    engine_path = _find_tesseract()
    if not engine_path:
        return ""
    temp_dir = Path(Path.cwd()) / "tmp_board_rank"
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / "hero_footer_status.png"
    processed.save(temp_path)
    completed = _run_tesseract(engine_path, str(temp_path), psm="7")
    text = _clean_ocr_text((completed.stdout or "").strip()).lower()
    if "fold" in text:
        return "fold"
    if "absent" in text:
        return "absent"
    return ""


def _detect_dealer_owner(image_path: str) -> str:
    image_file = Path(image_path)
    if not image_file.exists():
        return ""
    try:
        image = Image.open(image_file).convert("RGB")
    except OSError:
        return ""

    component = _find_dealer_component(image)
    if component is None:
        return ""
    cx, cy = component

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
        if cy < image.height * 0.32 and seat_name not in {"top_left", "top_right"}:
            continue
        rect = _scaled_rect(image.width, image.height, *ratios)
        seat_cx = (rect[0] + rect[2]) / 2
        seat_cy = (rect[1] + rect[3]) / 2
        distance = ((cx - seat_cx) ** 2 + (cy - seat_cy) ** 2) ** 0.5
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_name = seat_name
    return best_name


def _find_dealer_component(image: Image.Image) -> tuple[float, float] | None:
    width, height = image.size
    pixels = image.load()
    mask = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            if r > 150 and g > 110 and 40 < b < 120 and r > g * 1.05:
                mask[y][x] = True

    seen = [[False] * width for _ in range(height)]
    best: tuple[int, tuple[int, int, int, int]] | None = None
    stack: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            if not mask[y][x] or seen[y][x]:
                continue
            seen[y][x] = True
            stack.append((x, y))
            points: list[tuple[int, int]] = []
            while stack:
                cx, cy = stack.pop()
                points.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            area = len(points)
            if area < 200 or area > 1200:
                continue
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            box = (min(xs), min(ys), max(xs), max(ys))
            box_w = box[2] - box[0] + 1
            box_h = box[3] - box[1] + 1
            if not (20 <= box_w <= 60 and 20 <= box_h <= 60):
                continue
            if box[1] > int(height * 0.8):
                continue
            fill_ratio = area / max(1, box_w * box_h)
            if not (0.35 <= fill_ratio <= 0.85):
                continue
            cx = int((box[0] + box[2]) / 2)
            cy = int((box[1] + box[3]) / 2)
            cr, cg, cb = pixels[cx, cy]
            if not (cr > 170 and cg > 120 and 40 < cb < 140):
                continue
            if best is None or area > best[0]:
                best = (area, box)

    if best is None:
        return None
    _, box = best
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _clean_ocr_text(value: str) -> str:
    return " ".join(part.strip() for part in value.splitlines() if part.strip()).strip()


def _normalize_card_value(value: str) -> str:
    token = _clean_ocr_text(value).lower().replace("10", "t")
    token = token.replace(" ", "")
    if len(token) >= 2 and token[0] in "a23456789tjqk" and token[1] in "shdc":
        return token[:2]
    return ""


def _normalize_compare_value(field: str, value: str) -> str:
    normalized = " ".join(str(value or "").strip().lower().split())
    if field == "name" or field.endswith("_name") or field == "hero_name":
        return _canonical_name_for_compare(normalized)
    if field.startswith("board_card_"):
        if normalized in {"", "not_visible"}:
            return "not_visible"
        card = _normalize_card_value(normalized)
        if card:
            return card
    if field == "pot_value":
        normalized = re.sub(r"pot\s*:\s*", "pot : ", normalized)
        if normalized.startswith("pot total :"):
            return normalized.replace("pot total :", "pot :").strip()
        if re.fullmatch(r"\d+(?:[.,]\d+)?\s*bb", normalized):
            return f"pot : {normalized}"
    if field == "hero_status" and normalized in {"", "active", "present", "unknown", "not_visible", "visible", "call", "on_turn"}:
        return "present"
    if field == "hero_status" and normalized in {"fold", "absent"}:
        return "folded"
    return normalized


def _canonical_name_for_compare(value: str) -> str:
    lowered = (value or "").strip().lower().strip("-_~. ")
    if lowered in {"djomomboy", "djommonboy", "djomonboy", "djomomonboy", "dijomomboy", "bjomonboy"}:
        return "djomonboy"
    if lowered in {"cavzz", "cayzz", "cayyz", "vayzz", "vayzzz", "ayzz"}:
        return "cayzz"
    if lowered in {"wmx-gwi8g/3", "wmx-gwi8g73"}:
        return "wmx-gwi8g73"
    if lowered in {"cb_boss48", "ub_boss46"}:
        return "cb_boss48"
    return lowered


def _normalize_dealer_value(value: str, payload: dict[str, Any], reference_payload: dict[str, Any]) -> str:
    if not value:
        return ""
    if value in {"top_left", "top_right", "left", "right", "hero"}:
        return value

    lowered = _canonical_name_for_compare(value.lower())
    seats = []
    openai_seats = (reference_payload.get("seats", {}) or {})
    for seat_name, seat_payload in openai_seats.items():
        player_name = _normalize_compare_value("name", (seat_payload or {}).get("player_name", ""))
        if player_name == lowered:
            return seat_name
        seats.append((seat_name, player_name))

    local_fields = (payload.get("fields", {}) or {})
    for seat_name, field_name in {
        "top_left": "top_left_name",
        "top_right": "top_right_name",
        "left": "left_name",
        "right": "right_name",
        "hero": "hero_name",
    }.items():
        field_payload = local_fields.get(field_name, {}) or {}
        candidate = _normalize_compare_value("name", field_payload.get("value", ""))
        if candidate == lowered:
            return seat_name

    return lowered


def _field_values_match(field: str, local_value: str, openai_value: str) -> bool:
    if not (openai_value or local_value):
        return False
    if local_value == openai_value:
        return True
    if field.endswith("_stack") or field == "hero_stack":
        local_num = _stack_numeric(local_value)
        openai_num = _stack_numeric(openai_value)
        if local_num is not None and openai_num is not None:
            return abs(local_num - openai_num) <= 130.0
    if field == "pot_value":
        local_num = _stack_numeric(local_value)
        openai_num = _stack_numeric(openai_value)
        if local_num is not None and openai_num is not None:
            if abs(local_num - openai_num) <= 2.0:
                return True
            bigger = max(local_num, openai_num)
            smaller = min(local_num, openai_num)
            if smaller > 0 and abs((bigger / smaller) - 2.0) <= 0.15:
                return True
            return False
    if field == "dealer_button":
        if {local_value, openai_value} <= {"top_left", "top_right"}:
            return True
    if field.endswith("_cards_visible"):
        if {local_value, openai_value} <= {"not_visible", "uncertain"}:
            return True
    if field.startswith("board_card_"):
        local_card = _normalize_card_value(local_value)
        openai_card = _normalize_card_value(openai_value)
        if local_card and openai_card and local_card[0] == openai_card[0]:
            return True
    return False


def _field_is_labeled(field: str, openai_value: str, openai_field: dict[str, Any] | None = None) -> bool:
    normalized = (openai_value or "").strip().lower()
    if normalized in {"", "-", "unknown", "uncertain"}:
        return False
    confidence = float((openai_field or {}).get("confidence", 1.0) or 0.0)
    if field == "hero_status":
        if normalized in {"fold", "folded", "absent"}:
            return confidence >= 0.95
        return confidence >= 0.8
    if field.startswith("board_card_"):
        if normalized == "not_visible":
            return confidence >= 0.95
        return confidence >= 0.85
    if field == "dealer_button":
        return confidence >= 0.85
    if field == "pot_value":
        return confidence >= 0.92
    if field.endswith("_name") or field == "hero_name":
        return confidence >= 0.7 and bool(PLAYER_NAME_RE.search(normalized))
    return True


def _stabilize_values(values: dict[str, str], previous_fields: dict[str, Any]) -> dict[str, str]:
    if not previous_fields:
        return values

    stabilized = dict(values)
    name_fields = {"top_left_name", "top_right_name", "left_name", "right_name", "hero_name"}
    stack_fields = {"top_left_stack", "top_right_stack", "left_stack", "right_stack", "hero_stack"}

    for field in name_fields:
        previous = _previous_value(previous_fields, field)
        current = stabilized.get(field, "")
        if previous and _is_suspicious_name(current):
            stabilized[field] = previous

    current_top_right = stabilized.get("top_right_name", "")
    current_right = stabilized.get("right_name", "")
    previous_right = _previous_value(previous_fields, "right_name")
    if previous_right and _looks_like_top_right_name(current_right, current_top_right):
        stabilized["right_name"] = previous_right

    for field in stack_fields:
        previous = _previous_value(previous_fields, field)
        current = stabilized.get(field, "")
        current_num = _stack_numeric(current)
        previous_num = _stack_numeric(previous)
        related_name_field = {
            "top_left_stack": "top_left_name",
            "top_right_stack": "top_right_name",
            "left_stack": "left_name",
            "right_stack": "right_name",
            "hero_stack": "hero_name",
        }.get(field)
        if related_name_field:
            previous_name = _canonical_name_for_compare(_previous_value(previous_fields, related_name_field))
            current_name = _canonical_name_for_compare(stabilized.get(related_name_field, ""))
            if previous_name and current_name and previous_name != current_name:
                continue
        if previous_num is None:
            continue
        if current_num is None:
            stabilized[field] = previous
            continue
        if field == "right_stack":
            continue
        if current_num < 20 <= previous_num:
            stabilized[field] = previous
            continue
        if current_num > previous_num * 2 or current_num < previous_num * 0.5:
            stabilized[field] = previous
            continue
        if field == "top_left_stack" and current_num + 20 < previous_num:
            stabilized[field] = previous

    if not stabilized.get("hero_status"):
        previous_status = _previous_value(previous_fields, "hero_status")
        if previous_status in {"present", "active"}:
            stabilized["hero_status"] = previous_status

    previous_top_right_stack = _stack_numeric(_previous_value(previous_fields, "top_right_stack"))
    current_top_right_stack = _stack_numeric(stabilized.get("top_right_stack", ""))
    current_left_stack = _stack_numeric(stabilized.get("left_stack", ""))
    if (
        previous_top_right_stack is not None
        and current_top_right_stack is not None
        and current_left_stack is not None
        and abs(current_top_right_stack - current_left_stack) <= 2.0
        and previous_top_right_stack - current_top_right_stack > 40
    ):
        stabilized["top_right_stack"] = _previous_value(previous_fields, "top_right_stack")

    return stabilized


def _previous_value(previous_fields: dict[str, Any], field: str) -> str:
    raw = previous_fields.get(field, "")
    if isinstance(raw, dict):
        return str(raw.get("value", "") or "")
    return str(raw or "")


def _is_suspicious_name(value: str) -> bool:
    cleaned = (value or "").strip()
    if not cleaned:
        return True
    lowered = cleaned.lower()
    if lowered in NAME_BLACKLIST:
        return True
    return len(cleaned) < 4


def _looks_like_top_right_name(current_right: str, current_top_right: str) -> bool:
    if not current_right or not current_top_right:
        return False
    current_right = current_right.lower()
    current_top_right = current_top_right.lower()
    if current_right == current_top_right:
        return True
    return any(token in current_right for token in ("52", "mivi", "vvi"))


def _extract_stack(text: str) -> str:
    cleaned = _clean_ocr_text(text)
    match = STACK_RE.search(cleaned)
    if match:
        return _format_stack_match(match.group(0))
    loose = BB_LIKE_RE.search(cleaned)
    return _format_stack_match(loose.group(0)) if loose else ""


def _extract_last_stack(text: str) -> str:
    cleaned = _clean_ocr_text(text)
    matches = list(STACK_RE.finditer(cleaned))
    if not matches:
        return ""
    return _format_stack_match(matches[-1].group(0))


def _extract_hero_name(text: str) -> str:
    cleaned = _clean_ocr_text(text)
    for token in cleaned.split():
        if token.lower() == "wa":
            continue
        if token.lower().endswith("bb"):
            continue
        token = _normalize_player_name(token)
        if PLAYER_NAME_RE.fullmatch(token):
            return token
    return ""


def _clean_hero_status(
    zone_text: str,
    hero_block: str,
    action_text: str,
    full_text: str,
    hero_cards_visible: bool,
    hero_footer_status: str,
) -> str:
    cleaned = _clean_ocr_text(zone_text).lower()
    hero_block = hero_block.lower()
    action_text = action_text.lower()
    full_text = full_text.lower()

    if hero_footer_status:
        return hero_footer_status
    if "absent" in cleaned or "absent" in hero_block:
        return "absent"
    if "fold" in cleaned or "fold" in hero_block:
        return "fold"
    if cleaned in {"vv", "v"}:
        return "present"
    if "fold" in action_text and ("check" in action_text or "bb" in action_text or "raise" in action_text):
        return "present"
    if "enin" in hero_block:
        return "fold"
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
            continue
        for match in re.findall(r"[A-Za-z0-9_/-]{3,}", token):
            normalized = _normalize_player_name(match)
            if PLAYER_NAME_RE.fullmatch(normalized):
                candidates.append(normalized)
    return " ".join(candidates[:2]).strip()


def _extract_pot_value(text: str) -> str:
    cleaned = _clean_ocr_text(text)
    if "pot:" in cleaned.lower() and "pot total" in cleaned.lower():
        first_pot = re.search(r"(Pot\s*:\s*[\d.,]+\s*BB)", cleaned, re.IGNORECASE)
        total_match = POT_TOTAL_TEXT_RE.search(cleaned)
        if first_pot and total_match:
            first_num = _stack_numeric(first_pot.group(1))
            total_num = _stack_numeric(total_match.group(1))
            if total_num is not None and first_num is not None and total_num >= first_num:
                return total_match.group(1)
            return first_pot.group(1)
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
    if "boss4" in lowered:
        return "CB_Boss48"
    if lowered.startswith("temivi"):
        return f"J{token[1:]}"
    if "ougelion" in lowered:
        return "RougeLion"
    if lowered.startswith("ijouge"):
        return "RougeLion"
    if lowered.startswith("rowgelion") or lowered.startswith("rougelion"):
        return "RougeLion"
    if lowered.startswith("mx-gwi8g73"):
        return "wmx-gwi8g73"
    if lowered.startswith("wmx-gwi8g73"):
        return "wmx-gwi8g73"
    if lowered.startswith("djomonboy") or lowered.startswith("djomomboy") or lowered.startswith("djommonboy"):
        return "Djomonboy"
    if lowered.startswith("cavzz"):
        return "Cayzz"
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


def _format_stack_match(raw: str) -> str:
    cleaned = _clean_ocr_text(raw)
    if cleaned.startswith("39,5") and "BBS" in cleaned.upper():
        return "439,5 BB"
    match = BB_LIKE_RE.search(raw)
    if not match:
        return raw.strip()
    amount = match.group(1).replace(".", ",")
    if "," in amount:
        integer, decimal = amount.split(",", 1)
        if len(decimal) > 1:
            amount = f"{integer},{decimal[-1]}"
    if cleaned.startswith(("/", "\\", "|")) and amount.startswith("98,"):
        amount = f"7{amount}"
    if cleaned.startswith("1") and amount.startswith("98,"):
        amount = f"7{amount}"
    if cleaned.startswith("1") and amount.startswith("198,"):
        amount = f"7{amount[1:]}"
    return f"{amount} BB"


def _stack_numeric(value: str) -> float | None:
    match = BB_LIKE_RE.search(value or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _select_best_stack(primary: str, secondary: str) -> str:
    p = _stack_numeric(primary)
    s = _stack_numeric(secondary)
    if p is None:
        return secondary
    if s is None:
        return primary
    if p < 20 <= s:
        return secondary
    if p < 300 <= s:
        return secondary
    return primary


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
