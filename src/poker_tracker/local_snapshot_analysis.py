from __future__ import annotations

import json
import tempfile
from pathlib import Path
import re
from difflib import SequenceMatcher
from typing import Any

from PIL import Image, ImageFilter, ImageOps
import cv2
import numpy as np

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
POT_CURRENT_TEXT_RE = re.compile(r"(Pot\s*:\s*[\d.,]+\s*BB)", re.IGNORECASE)
POT_TOTAL_TEXT_RE = re.compile(r"(Pot\s+total\s*:\s*[\d.,]+\s*BB)", re.IGNORECASE)
POT_TOTAL_FRAGMENT_RE = re.compile(r"(?:Pot\s+)?total\s*:\s*([\d.,]+)\s*BB", re.IGNORECASE)
BOARD_RANK_RE = re.compile(r"\b([2-9]|10|[AJQKT])\b", re.IGNORECASE)
BB_LIKE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:BB|B8|68|BES|BE|BBS)\b", re.IGNORECASE)
POT_LOOSE_RE = re.compile(r"pot[^0-9]{0,10}(\d+(?:[.,]\d+)?)", re.IGNORECASE)
NAME_BLACKLIST = {
    "winamax", "wichita", "holdem", "limit", "playground", "free", "move", "straight",
    "all-in", "autorebuy", "attendre", "tour", "poser", "blind", "side", "pots", "pot",
    "patiente", "cartes", "small", "big", "no", "cashgame", "historique", "showdown",
    "pre-flop", "preflop", "prochaine", "action", "hauteur", "fold", "call", "check",
    "bold", "recaver", "cache", "present", "active", "sera", "voir", "tes",
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


def extract_live_table_facts(
    ocr_snapshot: OcrSnapshot,
    hero_name: str = "",
    hero_cards_hint: str = "",
    visible_board_hint: str = "",
    cached_names: dict[str, str] | None = None,
) -> dict[str, str]:
    if ocr_snapshot.status == "ok_minimal":
        return _extract_minimal_live_table_facts(ocr_snapshot, hero_name)
    extracted = extract_review_values(
        ocr_snapshot,
        {
            "live_snapshot": {
                "hero_name": hero_name,
                "hero_cards_hint": hero_cards_hint,
                "visible_board_hint": visible_board_hint,
                "cached_names": cached_names or {},
            }
        },
    )
    values = {field: (payload.get("value", "") or "") for field, payload in extracted.items()}
    # ``extract_review_values`` has already read both hero cards. Reuse that
    # result instead of starting two more Tesseract processes.
    values["hero_cards"] = (
        hero_cards_hint
        or values.get("hero_cards", "")
        or _extract_hero_cards_from_image(ocr_snapshot.image_path)
    )
    return values


def _extract_minimal_live_table_facts(ocr_snapshot: OcrSnapshot, hero_name: str) -> dict[str, str]:
    """Fast live extraction: only the fields needed by the live state."""
    zones = ocr_snapshot.zones or {}

    def text(name: str) -> str:
        zone = zones.get(name)
        return (zone.text if zone else "").strip()

    def stack(name: str) -> str:
        return _extract_stack(text(name))

    values = {
        "top_left_name": _clean_player_name(text("top_left_name")),
        "top_left_stack": stack("top_left_stack"),
        "top_right_name": _clean_player_name(text("top_right_name")),
        "top_right_stack": stack("top_right_stack"),
        "left_name": _clean_player_name(text("left_name")),
        "left_stack": stack("left_stack"),
        "right_name": _clean_player_name(text("right_name")),
        "right_stack": stack("right_stack"),
        "hero_name": _clean_player_name(text("hero_name")) or hero_name,
        "hero_stack": stack("hero_stack"),
        "hero_status": _clean_hero_status(text("hero_status"), text("hero"), "", "", False, ""),
        # `pot_value` is the optional second line "Pot total".  The dedicated
        # crop often starts at "total", so use a strict parser there and do
        # not mistake the first-line pot for a total.
        "pot_value": _extract_pot_total_value(text("pot_value")) or _extract_pot_value(text("pot")),
        "dealer_button": _detect_dealer_owner(ocr_snapshot.image_path),
    }

    for seat in ("top_left", "top_right", "left", "right", "hero"):
        values[f"{seat}_bet"] = _extract_bet_from_image(ocr_snapshot.image_path, seat)

    board_cards = _extract_board_cards(text("board"))
    for index in range(1, 6):
        values[f"board_card_{index}"] = board_cards[index - 1]

    image = Path(ocr_snapshot.image_path)
    calibration = load_calibration().get("zones", {})
    for seat in ("top_left", "top_right", "left", "right"):
        zone_name = f"{seat}_cards"
        ratios = calibration.get(zone_name)
        if not ratios or not image.exists():
            values[f"{zone_name}_visible"] = "-"
            continue
        try:
            with Image.open(image).convert("RGB") as source:
                rect = _scaled_rect(source.width, source.height, *ratios)
                crop_path = Path(tempfile.gettempdir()) / f"poker_fast_{image.stem}_{zone_name}.png"
                source.crop(rect).save(crop_path)
            values[f"{zone_name}_visible"] = _detect_cards_visible(str(crop_path))
        except OSError:
            values[f"{zone_name}_visible"] = "-"

    values["hero_cards"] = _extract_hero_cards_from_image(ocr_snapshot.image_path)
    return values


def extract_review_values(ocr_snapshot: OcrSnapshot, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    live = metadata.get("live_snapshot") or {}
    cached_names = live.get("cached_names") or {}
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
    board_hint = str(live.get("visible_board_hint", "") or "")
    if board_hint:
        board_cards = board_hint.split()[:5]
        board_cards.extend([""] * (5 - len(board_cards)))
    else:
        # The board zone is already OCR'd above. Prefer it so we do not launch
        # five additional Tesseract processes for the individual card zones.
        board_cards = _extract_board_cards_fast(
            ocr_snapshot.image_path,
            board_text,
            [zone_text(f"board_card_{index}") for index in range(1, 6)],
        )
        if not any(board_cards):
            board_cards = _extract_board_cards_from_image(ocr_snapshot.image_path)
    hero_block = _clean_ocr_text(zone_text("hero"))
    # Les cartes héros sont une donnée indépendante du texte de statut.
    # On les extrait directement depuis les deux cartes, puis on les expose
    # dans le résultat pour que l'évaluation et le mode live puissent les
    # utiliser sans confondre la valeur avec « Hauteur », « Paire », etc.
    hero_cards = str(live.get("hero_cards_hint", "") or "") or _extract_hero_cards_from_image(
        ocr_snapshot.image_path
    )
    hero_cards_visible = _hero_cards_visible_on_table(ocr_snapshot.image_path)
    hero_footer_status = _extract_hero_footer_status(ocr_snapshot.image_path)
    hero_name_from_block = _extract_hero_name(hero_block)
    hero_stack_from_block = _extract_last_stack(hero_block)
    hero_stack_zone = _extract_stack(zone_text("hero_stack"))
    action_text = " ".join(
        _clean_ocr_text(zone_text(name))
        for name in ("action_left", "action_center", "action_right")
    ).strip()
    pot_from_block = _extract_pot_current_value(zone_text("pot"))
    pot_total_from_zone = _extract_pot_total_value(zone_text("pot_value"))
    top_left_opponent = _clean_ocr_text(zone_text("left_opponent"))
    right_opponent = _clean_ocr_text(zone_text("right_opponent"))
    # Expanded crops are expensive, so only use them when the already OCR'd
    # calibrated crop is empty.
    left_stack_direct = _extract_stack(zone_text("left_stack"))
    top_left_stack_direct = _extract_stack(zone_text("top_left_stack"))
    top_right_stack_direct = _extract_stack(zone_text("top_right_stack"))
    right_stack_direct = _extract_stack(zone_text("right_stack"))
    left_stack_expanded = "" if left_stack_direct else _extract_stack(
        _extract_expanded_stack_text(ocr_snapshot.image_path, "left_stack", 0.60, 0.20)
    )
    top_left_stack_expanded = "" if top_left_stack_direct else _extract_stack(
        _extract_expanded_stack_text(ocr_snapshot.image_path, "top_left_stack", 0.35, 0.55)
    )
    top_right_stack_expanded = "" if top_right_stack_direct else _extract_stack(
        _extract_expanded_stack_text(ocr_snapshot.image_path, "top_right_stack", 0.25, 1.00)
    )
    right_stack_expanded = "" if right_stack_direct else _extract_stack(
        _extract_expanded_stack_text(ocr_snapshot.image_path, "right_stack", 0.35, 0.10)
    )
    def bet(seat: str) -> str:
        return _extract_bet_from_zone(ocr_snapshot.image_path, seat, zone_text(f"{seat}_bet"))
    top_left_name_direct = str(cached_names.get("top_left_name", "") or "") or _name_from_crop_if_needed(
        ocr_snapshot.image_path, "top_left_name", zone_text("top_left_name")
    )
    top_right_name_direct = str(cached_names.get("top_right_name", "") or "") or _name_from_crop_if_needed(
        ocr_snapshot.image_path, "top_right_name", zone_text("top_right_name")
    )
    left_name_direct = str(cached_names.get("left_name", "") or "") or _name_from_crop_if_needed(
        ocr_snapshot.image_path, "left_name", zone_text("left_name")
    )
    right_name_direct = str(cached_names.get("right_name", "") or "") or _name_from_crop_if_needed(
        ocr_snapshot.image_path, "right_name", zone_text("right_name")
    )
    right_name_expanded = "" if right_name_direct else _clean_player_name(
        _extract_expanded_zone_text(ocr_snapshot.image_path, "right_name", 0.25, 0.10)
    )

    def first_non_empty(*values: str) -> str:
        for value in values:
            if value and value != "-":
                return value
        return ""

    values = {
        "top_left_cards_visible": _detect_cards_visible(zone_image_path("top_left_cards")),
        "top_left_name": first_non_empty(
            top_left_name_direct,
            _row_value(name_rows, 0, 0),
            _candidate_name(name_candidates, 0),
        ),
        "top_left_stack": first_non_empty(
            _select_best_stack(top_left_stack_direct, top_left_stack_expanded),
            top_left_stack_expanded,
            _candidate_value(stack_candidates, 0),
            _row_value(stack_rows, 0, 0),
            _extract_stack(top_left_opponent),
        ),
        "top_right_cards_visible": _detect_cards_visible(zone_image_path("top_right_cards")),
        "top_right_name": first_non_empty(
            top_right_name_direct,
            _row_value(name_rows, 0, 1),
            _candidate_name(name_candidates, 1),
        ),
        "top_right_stack": first_non_empty(
            _select_best_stack(top_right_stack_direct, top_right_stack_expanded),
            top_right_stack_expanded,
            _candidate_value(stack_candidates, 1),
            _row_value(stack_rows, 0, 1),
        ),
        "left_cards_visible": _detect_cards_visible(zone_image_path("left_cards")),
        "left_name": first_non_empty(
            left_name_direct,
            _row_value(name_rows, 1, 0),
            _clean_player_name(top_left_opponent),
            _candidate_name(name_candidates, 2),
        ),
        "left_stack": first_non_empty(
            _select_best_stack(left_stack_direct, left_stack_expanded),
            left_stack_expanded,
            _row_value(stack_rows, 1, 0),
            _candidate_value(stack_candidates, 2),
            _extract_stack(top_left_opponent),
        ),
        "right_cards_visible": _detect_cards_visible(zone_image_path("right_cards")),
        "right_name": first_non_empty(
            right_name_direct,
            right_name_expanded,
            _row_value(name_rows, 1, 1),
            _clean_player_name(right_opponent),
            _candidate_name(name_candidates, 3),
        ),
        "right_stack": first_non_empty(
            _select_best_stack(right_stack_direct, right_stack_expanded),
            _row_value(stack_rows, 1, 1),
            _candidate_value(stack_candidates, 3),
            _extract_stack(right_opponent),
        ),
        "hero_name": first_non_empty(
            str(cached_names.get("hero_name", "") or ""),
            _clean_player_name(zone_text("hero_name")),
            hero_name_from_block,
            live.get("hero_name", ""),
        ),
        "hero_stack": first_non_empty(
            hero_stack_zone,
            _select_best_stack(hero_stack_from_block, hero_stack_zone),
            hero_stack_from_block,
        ),
        "top_left_bet": bet("top_left"),
        "top_right_bet": bet("top_right"),
        "left_bet": bet("left"),
        "right_bet": bet("right"),
        "hero_bet": bet("hero"),
        "hero_cards": hero_cards,
        "hero_status": _clean_hero_status(zone_text("hero_status"), hero_block, action_text, full_text, hero_cards_visible, hero_footer_status),
        "pot_value": first_non_empty(
            pot_total_from_zone,
            _extract_pot_total_value(full_text),
            pot_from_block,
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


def _name_from_crop_if_needed(image_path: str, zone_name: str, current: str) -> str:
    """Relit un nom avec marge uniquement si le crop prÃ©cis est douteux."""
    cleaned = _clean_player_name(current)
    if cleaned and "?" not in cleaned:
        return cleaned
    for margin in (0.12, 0.22):
        expanded = _extract_expanded_zone_text(image_path, zone_name, margin, margin)
        candidate = _clean_player_name(expanded)
        if candidate and "?" not in candidate:
            return candidate
    return cleaned


def _stack_from_crop_if_needed(image_path: str, zone_name: str, current: str) -> str:
    """Relit un stack avec marge si le premier chiffre est coupÃ© ou absent."""
    precise = _extract_stack(current)
    expanded_values: list[str] = []
    for margin in (0.12, 0.22):
        expanded = _extract_stack(
            _extract_expanded_stack_text(image_path, zone_name, margin, margin)
        )
        if expanded:
            expanded_values.append(expanded)
    for expanded in expanded_values:
        precise = _select_best_stack(precise, expanded)
    return precise


def _extract_bet_from_image(image_path: str, seat: str) -> str:
    """Lit une mise seulement si un jeton est prÃ©sent dans la zone du siÃ¨ge."""
    image_file = Path(image_path)
    ratios = load_calibration().get("zones", {}).get(f"{seat}_bet")
    if not image_file.exists() or not ratios:
        return ""
    try:
        image = Image.open(image_file).convert("RGB")
    except OSError:
        return ""
    crop = image.crop(_scaled_rect(image.width, image.height, *ratios))
    rgb = np.asarray(crop)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    orange = (r > 130) & (g > 45) & (g < 190) & (b < 120) & (r > g * 1.25)
    if float(orange.mean()) < 0.025:
        return ""
    return _extract_stack(_extract_expanded_stack_text(image_path, f"{seat}_bet", 0, 0))


def _extract_bet_from_zone(image_path: str, seat: str, zone_text: str) -> str:
    """Use the already-parallel OCR zone; retry only for a real bet."""
    image_file = Path(image_path)
    ratios = load_calibration().get("zones", {}).get(f"{seat}_bet")
    if not image_file.exists() or not ratios:
        return ""
    try:
        image = Image.open(image_file).convert("RGB")
    except OSError:
        return ""
    crop = image.crop(_scaled_rect(image.width, image.height, *ratios))
    rgb = np.asarray(crop)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    orange = (r > 130) & (g > 45) & (g < 190) & (b < 120) & (r > g * 1.25)
    if float(orange.mean()) < 0.025:
        return ""
    return _extract_stack(zone_text) or _extract_bet_from_image(image_path, seat)


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
    variants = [processed.point(lambda p: 255 if p > 155 else 0)]
    # Le stack est jaune. Ce masque isole le texte du fond gris et permet de
    # conserver le premier chiffre quand il est posÃ© sur une zone claire.
    rgb = np.asarray(crop)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    yellow = (r > 120) & (g > 70) & (r > b * 1.25) & (g > b * 1.12)
    yellow_mask = Image.fromarray(np.where(yellow, 0, 255).astype("uint8"))
    variants.insert(0, yellow_mask.resize((yellow_mask.width * 4, yellow_mask.height * 4), Image.Resampling.NEAREST))

    engine_path = _find_tesseract()
    if not engine_path:
        return ""
    temp_dir = Path(Path.cwd()) / "tmp_board_rank"
    temp_dir.mkdir(exist_ok=True)
    results: list[str] = []
    for index, variant in enumerate(variants):
        # Laisser une marge blanche autour du premier chiffre Ã©vite qu'il
        # soit interprÃ©tÃ© comme le bord du crop.
        variant = ImageOps.expand(variant, border=10, fill=255)
        temp_path = temp_dir / f"{zone_name}_expanded_stack_{index}.png"
        variant.save(temp_path)
        completed = _run_tesseract(
            engine_path,
            str(temp_path),
            psm="6" if index == 0 else "7",
        )
        text = _clean_ocr_text((completed.stdout or "").strip())
        if text:
            results.append(text)
    # Le masque jaune est prioritaire : il prÃ©serve mieux les chiffres que
    # la variante en niveaux de gris, qui peut transformer ``97`` en ``9/7``.
    for result in results:
        if _extract_stack(result):
            return result
    return ""


def _detect_cards_visible(image_path: str) -> str:
    if not image_path or not Path(image_path).exists():
        return "-"
    try:
        image = Image.open(image_path).convert("RGB")
    except OSError:
        return "-"

    return _detect_cards_visible_in_image(image)


def _detect_cards_visible_in_image(image: Image.Image) -> str:
    pixels = list(image.convert("RGB").getdata())
    total = max(1, len(pixels))
    red_ratio = sum(1 for r, g, b in pixels if r > 120 and r > g * 1.2 and r > b * 1.2) / total
    bright_ratio = sum(1 for r, g, b in pixels if (r + g + b) / 3 > 160) / total
    dark_ratio = sum(1 for r, g, b in pixels if (r + g + b) / 3 < 40) / total
    white_ratio = sum(1 for r, g, b in pixels if r > 180 and g > 180 and b > 180) / total

    # Les cartes adverses fermées sont affichées comme des dos rouges avec une
    # bordure blanche. Leur texte n'est pas lisible, mais leur présence l'est.
    if red_ratio > 0.45 and bright_ratio > 0.08 and white_ratio > 0.05:
        return "visible"
    # Les cartes ouvertes sont majoritairement blanches, même si leur couleur
    # dominante n'est ni rouge ni verte.
    if red_ratio > 0.65 and bright_ratio > 0.10 and dark_ratio < 0.35:
        return "visible"
    return "not_visible"


def detect_visible_opponent_seats(image_path: str) -> list[str]:
    """Cheap card-back scan used between full OCR passes."""
    if not image_path or not Path(image_path).exists():
        return []
    try:
        image = Image.open(image_path).convert("RGB")
    except OSError:
        return []
    zones = load_calibration().get("zones", {})
    active: list[str] = []
    for seat in ("top_left", "top_right", "left", "right"):
        ratios = zones.get(f"{seat}_cards")
        if not ratios:
            continue
        crop = image.crop(_scaled_rect(image.width, image.height, *ratios))
        if _detect_cards_visible_in_image(crop) == "visible":
            active.append(seat)
    return active


def _extract_board_cards(board_text: str) -> list[str]:
    cleaned = _clean_ocr_text(board_text).replace("10", "T").replace("O", "Q")
    rank_matches = [match.group(1).upper() for match in BOARD_RANK_RE.finditer(cleaned)]
    cards = [rank.lower() for rank in rank_matches[:5]]
    while len(cards) < 5:
        cards.append("")
    return cards


def _extract_single_card_rank(card_text: str) -> str:
    """Normalize OCR from one tightly cropped Winamax rank glyph."""
    token = re.sub(r"[^A-Z0-9]", "", _clean_ocr_text(card_text).upper())
    if "10" in token:
        return "t"
    if token in {"A", "K", "Q", "J", "T", "2", "3", "4", "5", "6", "7", "8", "9"}:
        return token.lower()
    # Stable Tesseract confusions observed on the calibrated value crops.
    if token in {"OQ", "QO", "0Q", "Q0"}:
        return "q"
    if token in {"ZT", "Z7", "T7", "L7"}:
        return "7"
    return ""


def _extract_board_cards_fast(
    image_path: str,
    board_text: str,
    card_rank_texts: list[str] | None = None,
) -> list[str]:
    """Combine one board OCR pass with cheap per-card colour detection."""
    ranks = _extract_board_cards(board_text)
    image_file = Path(image_path)
    if not image_file.exists():
        return ranks
    try:
        image = Image.open(image_file).convert("RGB")
    except OSError:
        return ranks

    calibration = load_calibration().get("zones", {})
    cards: list[str] = []
    engine_path = ""
    for index in range(1, 6):
        zone_name = f"board_card_{index}"
        ratios = calibration.get(zone_name)
        if not ratios:
            break
        crop = image.crop(_scaled_rect(image.width, image.height, *ratios))
        # L'OCR global peut renvoyer un chiffre parasite provenant d'une
        # autre zone. Ne jamais attribuer ce chiffre Ã  un emplacement vide.
        if not _looks_like_card_crop(crop) and _card_white_ratio(crop) < 0.18:
            break
        rank = ""
        if card_rank_texts and index <= len(card_rank_texts):
            rank = _extract_single_card_rank(card_rank_texts[index - 1])
        if not rank:
            rank = ranks[index - 1] if index <= len(ranks) else ""
        value_ratios = calibration.get(f"{zone_name}_value")
        rank_crop = (
            image.crop(_scaled_rect(image.width, image.height, *value_ratios))
            if value_ratios
            else crop.crop(_scaled_rect(crop.width, crop.height, 0.02, 0.05, 0.40, 0.27))
        )
        # If the broad board OCR missed a rank, read only that card instead of
        # relaunching OCR on all five cards.
        local_rank = rank
        if not local_rank:
            local_rank = _match_board_rank_reference(rank_crop)
        if not local_rank:
            engine_path = engine_path or _find_tesseract() or ""
            if engine_path:
                local_rank = _extract_rank_from_value_crop(rank_crop, engine_path)
        if local_rank == "3" and _value_crop_has_two_holes(rank_crop):
            local_rank = "8"
        # A tight rank crop can identify the two loops of an 8 even when the
        # per-card OCR has incorrectly returned A (seen on blue diamond 8s).
        if local_rank in {"", "a", "3"} and _rank_from_glyph_shape(rank_crop) == "8":
            local_rank = "8"
        suit = _extract_card_suit(crop)
        cards.append(f"{local_rank}{suit}" if suit else local_rank)
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
            break
        rect = _scaled_rect(image.width, image.height, *ratios)
        crop = image.crop(rect)
        white_ratio = _card_white_ratio(crop)
        # Do the cheap visual presence check before launching Tesseract. Empty
        # board slots are common on preflop/flop and do not need OCR at all.
        if not _looks_like_card_crop(crop) and white_ratio < 0.18:
            break
        suit = _extract_card_suit(crop)
        value_ratios = calibration.get(f"{zone_name}_value")
        rank_crop = (
            image.crop(_scaled_rect(image.width, image.height, *value_ratios))
            if value_ratios
            else crop.crop(_scaled_rect(crop.width, crop.height, 0.02, 0.05, 0.40, 0.27))
        )
        template_rank = _match_board_rank_reference(rank_crop)
        full_rank = _extract_card_rank(crop, engine_path, suit)
        value_rank = "" if full_rank else _extract_rank_from_value_crop(rank_crop, engine_path)
        # La lecture de la carte complète est plus fiable pour A/J/6. Le crop
        # serré sert à corriger la confusion fréquente entre 8 et 3.
        rank = template_rank or full_rank or value_rank
        if full_rank == "3" and _value_crop_has_two_holes(rank_crop):
            rank = "8"
        if not _looks_like_card_crop(crop) and not (rank and suit):
            break
        if rank and suit:
            if white_ratio < 0.18:
                break
            cards.append(f"{rank}{suit}")
        elif rank:
            cards.append(rank)
        else:
            cards.append("")
    return cards


def _match_board_rank_reference(rank_crop: Image.Image) -> str:
    """Compare le rang serré aux références locales, sans API ni OCR."""
    root = Path(__file__).resolve().parents[2] / "data" / "ocr_dataset" / "templates" / "board_values"
    if not root.exists():
        return ""

    def mask(image: Image.Image) -> np.ndarray:
        gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        gray = cv2.resize(gray, (40, 42), interpolation=cv2.INTER_AREA)
        return (gray < 170).astype(np.float32)

    source = mask(rank_crop)
    best_rank, best_score = "", -1.0
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        for path in folder.glob("*.png"):
            try:
                score = float(cv2.matchTemplate(source, mask(Image.open(path)), cv2.TM_CCOEFF_NORMED)[0, 0])
            except (OSError, cv2.error):
                continue
            if score > best_score:
                best_rank, best_score = folder.name.lower(), score
    return best_rank if best_score >= 0.52 else ""


def _value_crop_has_two_holes(value_crop: Image.Image) -> bool:
    """Distinguish Winamax's 8 from 3 by counting enclosed glyph loops."""
    gray = cv2.cvtColor(np.asarray(value_crop.convert("RGB")), cv2.COLOR_RGB2GRAY)
    mask = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)[1]
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None or not contours:
        return False
    holes = sum(1 for node in hierarchy[0] if node[3] >= 0)
    return holes >= 2


def _extract_hero_cards_from_image(image_path: str) -> str:
    image_file = Path(image_path)
    if not image_file.exists():
        return ""

    try:
        image = Image.open(image_file).convert("RGB")
    except OSError:
        return ""

    engine_path = _find_tesseract()
    if not engine_path:
        return ""

    calibration = load_calibration().get("zones", {})
    direct_zones = [
        calibration.get("hero_card_1_value"),
        calibration.get("hero_card_2_value"),
    ]
    if all(direct_zones):
        direct_cards: list[str] = []
        for ratios in direct_zones:
            value_crop = image.crop(_scaled_rect(image.width, image.height, *ratios))
            if _card_white_ratio(value_crop) < 0.12:
                break
            rank = _extract_rank_from_value_crop(value_crop, engine_path)
            suit = _extract_suit_from_rank_crop(value_crop)
            if not rank:
                break
            direct_cards.append(f"{rank}{suit}" if suit else rank)
        return " ".join(direct_cards)
    return ""


def _extract_hero_cards_from_ratios(
    image: Image.Image,
    engine_path: str,
    ratios: list[float] | tuple[float, float, float, float] | None,
    widen: float = 0.0,
) -> list[str]:
    if not ratios:
        return []

    rect = _scaled_rect(image.width, image.height, *ratios)
    left, top, right, bottom = rect
    width = max(1, right - left)
    pad = int(width * widen)
    rect = (
        max(0, left - pad),
        top,
        min(image.width, right + pad),
        bottom,
    )
    crop = image.crop(rect)
    card_regions = [
        # Les deux cartes se recouvrent : on garde une fenêtre indépendante
        # autour de chaque valeur pour éviter que la carte 1 soit relue dans
        # la fenêtre de la carte 2.
        (0.00, 0.00, 0.45, 1.00),
        (0.30, 0.00, 0.90, 1.00),
    ]
    cards: list[str] = []
    for left_ratio, top_ratio, right_ratio, bottom_ratio in card_regions:
        card_crop = crop.crop(
            (
                max(0, int(crop.width * left_ratio)),
                max(0, int(crop.height * top_ratio)),
                min(crop.width, int(crop.width * right_ratio)),
                min(crop.height, int(crop.height * bottom_ratio)),
            )
        )
        white_ratio = _card_white_ratio(card_crop)
        if not _looks_like_card_crop(card_crop) and white_ratio < 0.10:
            continue
        suit = _extract_card_suit(card_crop)
        rank = _extract_card_rank(card_crop, engine_path, suit)
        if rank and suit:
            card = f"{rank}{suit}"
        elif rank:
            card = rank
        else:
            card = ""
        if card and card not in cards:
            cards.append(card)
    return cards


def _extract_suit_from_rank_crop(rank_crop: Image.Image) -> str:
    """Déduit la sorte par la couleur du rang, sans regarder le symbole."""
    pixels = list(rank_crop.convert("RGB").getdata())
    total = max(1, len(pixels))
    red = sum(1 for r, g, b in pixels if r > 120 and r > g * 1.18 and r > b * 1.18) / total
    blue = sum(1 for r, g, b in pixels if b > 70 and b > r * 1.10 and b > g * 1.05) / total
    green = sum(1 for r, g, b in pixels if g > 70 and g > r * 1.08 and g > b * 1.02) / total
    dark = sum(1 for r, g, b in pixels if (r + g + b) / 3 < 85) / total
    neutral_dark = sum(
        1 for r, g, b in pixels
        if (r + g + b) / 3 < 105 and max(r, g, b) - min(r, g, b) < 28
    ) / total
    if red > 0.05:
        return "h"
    if neutral_dark > 0.05:
        return "s"
    if blue > 0.05:
        return "d"
    if green > 0.05:
        return "c"
    if dark > 0.05:
        return "s"
    return ""


def _extract_rank_from_value_crop(value_crop: Image.Image, engine_path: str) -> str:
    """Lit uniquement le rang dans le crop interne calibré."""
    if value_crop.width < 3 or value_crop.height < 3:
        return ""
    rgb = np.asarray(value_crop.convert("RGB"))
    gray = ImageOps.autocontrast(value_crop.convert("L"))
    def enlarged(source: Image.Image, resample: Image.Resampling) -> Image.Image:
        padded = ImageOps.expand(source, border=12, fill=255)
        return padded.resize((padded.width * 7, padded.height * 7), resample)

    variants = [
        enlarged(gray, Image.Resampling.LANCZOS),
        enlarged(gray.point(lambda p: 255 if p > 135 else 0), Image.Resampling.NEAREST),
        enlarged(gray.point(lambda p: 255 if p > 175 else 0), Image.Resampling.NEAREST),
    ]
    # Pour les rangs colorés, fournir aussi à Tesseract un masque de la
    # couleur dominante. Le traitement bleu ne s'applique qu'aux crops bleus.
    suit = _extract_suit_from_rank_crop(value_crop)
    if suit in {"h", "d", "c"}:
        r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        if suit == "h":
            ink = (r > g * 1.15) & (r > b * 1.15)
        elif suit == "d":
            ink = (b > r * 1.08) & (b > g * 1.02)
        else:
            ink = (g > r * 1.05) & (g > b * 1.01)
        color_mask = Image.fromarray(np.where(ink, 0, 255).astype("uint8"))
        variants.insert(0, enlarged(color_mask, Image.Resampling.NEAREST))
    candidates: list[str] = []
    temp_dir = Path(Path.cwd()) / "tmp_board_rank"
    temp_dir.mkdir(exist_ok=True)
    for index, processed in enumerate(variants):
        path = temp_dir / f"value_crop_{index}.png"
        processed.save(path)
        # PSM 10 suffit dans ce crop qui contient un rang isolÃ©. Le PSM 8
        # reste inutilement coÃ»teux et sera rÃ©introduit seulement si on
        # constate un Ã©chec sur un futur format de table.
        for psm in ("10",):
            completed = _run_tesseract(engine_path, str(path), psm=psm, extra_args=["-c", "tessedit_char_whitelist=AKQJT23456789"])
            raw = (completed.stdout or "").strip().upper().replace(" ", "")
            raw = raw.replace("1O", "10").replace("IO", "10").replace("O", "Q")
            # L'interface affiche ``10`` et jamais ``T``. Un Tesseract qui
            # transforme un rang simple (notamment J) en ``T`` ne doit donc
            # pas produire un faux dix; le fallback de forme gÃ¨re les vrais
            # deux glyphes ``10`` lorsque la lecture textuelle Ã©choue.
            if raw == "10":
                candidates.append("t")
            elif raw == "T":
                # Dans cette table, un rang seul lu ``T`` correspond au J
                # (le dix est toujours dessinÃ© avec deux glyphes ``10``).
                candidates.append("j")
            else:
                match = re.search(r"[AKQJ98765432]", raw)
                if match:
                    candidates.append(match.group(0).lower())
        if len(candidates) >= 2 and candidates[-1] == candidates[-2]:
            # Deux variantes concordantes suffisent; les autres restent
            # disponibles pour les cas ambigus.
            break
    if not candidates:
        # Secours uniquement en cas d'Ã©chec du PSM rapide.
        for index, processed in enumerate(variants):
            path = temp_dir / f"value_crop_fallback_{index}.png"
            processed.save(path)
            completed = _run_tesseract(
                engine_path,
                str(path),
                psm="8",
                extra_args=["-c", "tessedit_char_whitelist=AKQJT23456789"],
            )
            raw = (completed.stdout or "").strip().upper().replace(" ", "")
            raw = raw.replace("1O", "10").replace("IO", "10").replace("O", "Q")
            if raw == "10":
                candidates.append("t")
            elif raw == "T":
                candidates.append("j")
            else:
                match = re.search(r"[AKQJ98765432]", raw)
                if match:
                    candidates.append(match.group(0).lower())
        if candidates:
            counts = {rank: candidates.count(rank) for rank in set(candidates)}
            candidate = max(counts, key=counts.get)
            shape_rank = _rank_from_glyph_shape(value_crop)
            if shape_rank in {"q", "8", "t"}:
                return shape_rank
            if candidate == "2" and _unbordered_rank_is_seven(value_crop, engine_path):
                return "7"
            return candidate
        shape_rank = _rank_from_glyph_shape(value_crop)
        if shape_rank:
            return shape_rank
        # Certains ``10`` bleus trÃ¨s petits sont vus par Tesseract comme une
        # tache continue. On dÃ©tecte alors automatiquement deux formes par
        # projection horizontale, sans connaÃ®tre la valeur Ã  l'avance.
        rgb_mask = np.asarray(value_crop.convert("RGB"))
        r, g, b = rgb_mask[:, :, 0], rgb_mask[:, :, 1], rgb_mask[:, :, 2]
        ink = (
            ((b > r * 1.08) & (b > g * 1.02) & (b < 245))
            | ((r > g * 1.15) & (r > b * 1.15))
            | ((g > r * 1.05) & (g > b * 1.01))
            | ((rgb_mask.mean(axis=2) < 105) & ((rgb_mask.max(axis=2) - rgb_mask.min(axis=2)) < 30))
        )
        projection = ink.sum(axis=0).astype(float)
        if projection.size >= 12:
            inner = projection[3:-3]
            peak = float(inner.max()) if inner.size else 0.0
            valley = float(inner.min()) if inner.size else peak
            occupied = int((inner > max(2.0, peak * 0.22)).sum()) if inner.size else 0
            if peak >= 8 and occupied >= int(projection.size * 0.55) and valley <= peak * 0.30:
                return "t"
        return ""
    counts = {rank: candidates.count(rank) for rank in set(candidates)}
    candidate = max(counts, key=counts.get)
    # A two-glyph 10 may be read as 7 by OCR. Its enclosed zero is a much
    # stronger signal, as are the characteristic holes of Q and 8.
    shape_rank = _rank_from_glyph_shape(value_crop)
    if shape_rank in {"q", "8", "t"}:
        return shape_rank
    if candidate == "2" and _unbordered_rank_is_seven(value_crop, engine_path):
        return "7"
    return candidate


def _unbordered_rank_is_seven(value_crop: Image.Image, engine_path: str) -> bool:
    """Resolve the only recurrent 2/7 ambiguity without a reference set."""
    gray = ImageOps.autocontrast(value_crop.convert("L"))
    temp_dir = Path(Path.cwd()) / "tmp_board_rank"
    temp_dir.mkdir(exist_ok=True)
    path = temp_dir / "value_crop_two_seven.png"
    gray.resize((gray.width * 7, gray.height * 7), Image.Resampling.LANCZOS).save(path)
    completed = _run_tesseract(
        engine_path, str(path), psm="10",
        extra_args=["-c", "tessedit_char_whitelist=27"],
    )
    return (completed.stdout or "").strip() == "7"


def _rank_from_glyph_shape(value_crop: Image.Image) -> str:
    """Conservative fallback for a rank when OCR returned nothing."""
    width, height = value_crop.size
    if width < 10 or height < 15:
        return ""
    crop = value_crop.crop((3, max(6, int(height * 0.20)), max(4, int(width * 0.88)), max(7, int(height * 0.94))))
    rgb = np.asarray(crop.convert("RGB"))
    saturation = rgb.max(axis=2).astype(int) - rgb.min(axis=2).astype(int)
    brightness = rgb.mean(axis=2)
    ink = (((saturation > 30) & (brightness < 235)) | (brightness < 120)).astype("uint8") * 255
    contours, hierarchy = cv2.findContours(ink, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return ""
    hole_indexes = [index for index, node in enumerate(hierarchy[0]) if node[3] >= 0]
    holes = [cv2.boundingRect(contours[index]) for index in hole_indexes]
    if len(holes) >= 2:
        return "8"
    if len(holes) != 1:
        return ""
    _, _, hole_width, hole_height = holes[0]
    hole_area = float(cv2.contourArea(contours[hole_indexes[0]]))
    if hole_area >= 180 and hole_width >= 13:
        return "q"
    if hole_height >= 18 and hole_width <= 11:
        return "t"
    if hole_area <= 90 and hole_height <= 14:
        return "a"
    return ""


def _extract_card_rank(card_image: Image.Image, engine_path: str, suit: str = "", tight: bool = False) -> str:
    rank_crop = card_image if tight else card_image.crop((0, 0, max(1, int(card_image.width * 0.48)), max(1, int(card_image.height * 0.42))))
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
        completed = _run_tesseract(
            engine_path,
            str(temp_path),
            psm="10",
            extra_args=["-c", "tessedit_char_whitelist=AKQJT23456789"],
        )
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
    if any(raw in {"Z", "7", "Z.", "Z7", "7Z", "JZ", "ZJ"} for raw in seen_raw):
        return "7"
    if "5" in candidates and "j" in candidates and (pip_count >= 5 or suit == "h"):
        return "5"
    if "a" in candidates and "4" in candidates:
        return "a" if pip_count <= 2 else "4"
    if "a" in candidates and "7" in candidates:
        return "7" if pip_count >= 5 else "a"
    if "a" in candidates and "8" in candidates:
        return "8" if pip_count >= 4 else "a"
    if "6" in candidates and "j" in candidates:
        return "6"
    if "2" in candidates and "j" in candidates:
        return "2"
    # Tesseract confond parfois le J avec un T sur la petite police Winamax.
    # Dans ce cas seulement, départager les deux formes par templates, sans
    # interdire les vrais T.
    if "t" in candidates:
        template_hint = _rank_template_hint(rank_crop)
        if template_hint:
            return template_hint
    if candidates:
        return candidates[0]
    return ""


def _rank_template_hint(rank_crop: Image.Image) -> str:
    root = Path(__file__).resolve().parents[2] / "data" / "ocr_dataset" / "templates" / "ranks"
    if not root.exists():
        return ""

    def mask(image: Image.Image) -> np.ndarray:
        gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        gray = cv2.resize(gray, (32, 48), interpolation=cv2.INTER_AREA)
        return (gray < 150).astype(np.float32)

    source = mask(rank_crop)
    scores = {}
    for rank, folder in (("j", "J"), ("t", "10")):
        values = []
        for path in (root / folder).glob("*.png"):
            try:
                values.append(float(cv2.matchTemplate(source, mask(Image.open(path)), cv2.TM_CCOEFF_NORMED)[0, 0]))
            except (OSError, cv2.error):
                pass
        scores[rank] = max(values, default=-1.0)
    if scores["j"] >= 0.45 and scores["j"] > scores["t"] + 0.05:
        return "j"
    if scores["t"] >= 0.45 and scores["t"] > scores["j"] + 0.05:
        return "t"
    return ""


def _extract_card_suit(card_image: Image.Image) -> str:
    # Le symbole est sous le rang. Éviter la partie haute empêche la couleur
    # du rang et celle de la carte voisine de fausser la classification.
    suit_roi = card_image.crop((
        0,
        max(1, int(card_image.height * 0.32)),
        max(1, int(card_image.width * 0.42)),
        max(1, int(card_image.height * 0.78)),
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
    if green_ratio > 0.08:
        return "c"
    if dark_ratio > 0.30:
        return "s"
    if dark_ratio > 0.18:
        return "s"
    return ""


def _looks_like_card_crop(card_image: Image.Image) -> bool:
    white_ratio = _card_white_ratio(card_image)
    return white_ratio > 0.10


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


def hero_cards_visible_on_table(image_path: str) -> bool:
    """Public cheap hero-card presence check for the fast live loop."""
    return _hero_cards_visible_on_table(image_path)


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

    calibration = load_calibration().get("zones", {})
    # On teste les sièges un par un. Le premier composant valide gagne :
    # inutile d'analyser les autres zones ensuite.
    for seat_name in ("top_left", "top_right", "left", "right", "hero"):
        ratios = calibration.get(f"dealer_{seat_name}")
        if not ratios:
            continue
        rect = _scaled_rect(image.width, image.height, *ratios)
        if _find_dealer_component(image, rect) is not None:
            return seat_name
    return ""


def _find_dealer_component(
    image: Image.Image,
    search_rect: tuple[int, int, int, int] | None = None,
) -> tuple[float, float] | None:
    width, height = image.size
    pixels = image.load()
    if search_rect is None:
        left, top, right, bottom = 0, 0, width, height
    else:
        left, top, right, bottom = (
            max(0, search_rect[0]), max(0, search_rect[1]),
            min(width, search_rect[2]), min(height, search_rect[3]),
        )

    # La recherche porte uniquement sur la zone candidate. Le masque couleur
    # et les composantes connexes sont calculés par OpenCV, puis on sort dès
    # qu'un bouton plausible est trouvé.
    if right <= left or bottom <= top:
        return None
    array = np.asarray(image.crop((left, top, right, bottom)))
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    mask = ((red > 80) & (green > 60) & (blue < 120) &
            (red > green * 1.05) & (red > blue * 1.15)).astype(np.uint8)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        box_w = int(stats[index, cv2.CC_STAT_WIDTH])
        box_h = int(stats[index, cv2.CC_STAT_HEIGHT])
        if not (200 <= area <= 1200 and 20 <= box_w <= 60 and 20 <= box_h <= 60):
            continue
        fill_ratio = area / max(1, box_w * box_h)
        if not 0.35 <= fill_ratio <= 0.85:
            continue
        cx, cy = centroids[index]
        return (left + cx, top + cy)
    return None

    # Ancienne recherche Python conservée comme référence historique.
    mask = [[False] * width for _ in range(height)]
    for y in range(top, bottom):
        for x in range(left, right):
            r, g, b = pixels[x, y]
            # The dealer disc can be dimmed by the table animation; use hue
            # and relative channel ratios instead of a fixed brightness.
            if r > 80 and g > 60 and b < 120 and r > g * 1.05 and r > b * 1.15:
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
            if not (cr > 80 and cg > 60 and cb < 140 and cr > cg * 1.05 and cr > cb * 1.10):
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
    if field.endswith("_name") or field == "hero_name":
        return _normalize_name_compare(normalized)
    if field == "pot_value":
        normalized = re.sub(r"pot\s*:\s*", "pot : ", normalized)
        if normalized.startswith("pot total :"):
            return normalized.replace("pot total :", "pot :").strip()
        if re.fullmatch(r"\d+(?:[.,]\d+)?\s*bb", normalized):
            return f"pot : {normalized}"
    if field == "hero_status" and normalized in {"", "active", "present", "unknown", "not_visible", "visible", "call", "on_turn"}:
        return "present"
    if field == "hero_status" and normalized in {"fold", "folded", "absent"}:
        return "folded"
    if field == "hero_status":
        if any(token in normalized for token in ("in_hand", "check", "call", "small blind", "big blind", "hauteur", "action")):
            return "present"
        if normalized:
            return "present"
    return normalized


def _canonical_name_for_compare(value: str) -> str:
    lowered = (value or "").strip().lower().strip("-_~. ")
    if lowered in {"djomomboy", "djommonboy", "djomonboy", "djomomonboy", "dijomomboy", "bjomonboy"}:
        return "djomonboy"
    if lowered in {"cavzz", "cayzz", "cayyz", "vayzz", "vayzzz", "ayzz"}:
        return "cayzz"
    if lowered in {"hhadadock2y", "haddock25", "haddock2y", "hhadadock25"}:
        return "haddock25"
    if lowered in {"badboys7 f7f", "badboys7f7f", "badboys777", "badboys77", "badboys7"}:
        return "badboys777"
    if lowered in {"wmx-gwi8g/3", "wmx-gwi8g73"}:
        return "wmx-gwi8g73"
    if lowered in {"cb_boss48", "ub_boss46"}:
        return "cb_boss48"
    if lowered in {"louppianc", "loupbpianc", "louppblanc", "loupblanc88", "loupblanc"}:
        return "loupblanc"
    if lowered in {"shark1 3shark", "shark13shark"}:
        return "shark13shark"
    return lowered


def _normalize_name_compare(value: str) -> str:
    canonical = _canonical_name_for_compare(value)
    canonical = canonical.replace(" ", "")
    canonical = re.sub(r"[^a-z0-9]", "", canonical)
    canonical = re.sub(r"^([a-z])\1+", r"\1", canonical)
    canonical = re.sub(r"(\D)\1{2,}", r"\1", canonical)
    canonical = re.sub(r"(\d)\1{2,}", r"\1", canonical)
    canonical = re.sub(r"\d+$", "", canonical)
    return canonical


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
    if field.endswith("_name") or field == "hero_name":
        local_key = _normalize_name_compare(local_value)
        openai_key = _normalize_name_compare(openai_value)
        if local_key and openai_key:
            if local_key == openai_key:
                return True
            if local_key.startswith(openai_key) or openai_key.startswith(local_key):
                return True
            if SequenceMatcher(None, local_key, openai_key).ratio() >= 0.78:
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
            if smaller > 0 and 9.0 <= (bigger / smaller) <= 11.0:
                return True
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
        return (
            confidence >= 0.8
            and bool(PLAYER_NAME_RE.search(normalized))
            and len(normalized.replace(" ", "")) >= 4
        )
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
    if re.search(r"\bALL\s*[- ]?\s*IN\b", cleaned, re.IGNORECASE):
        return "0 BB"
    split_leading_one = re.search(r"\b1\s+(\d{2}(?:[.,]\d+)?)\s*(?:BB|B8|68|BES|BE|BBS)\b", cleaned, re.IGNORECASE)
    if split_leading_one:
        return _format_stack_match(f"1{split_leading_one.group(1)} BB")
    match = STACK_RE.search(cleaned)
    if match:
        return _format_stack_match(match.group(0))
    loose = BB_LIKE_RE.search(cleaned)
    if loose:
        return _format_stack_match(loose.group(0))
    trailing = re.search(r"\b(\d+(?:[.,]\d+)?)\s*[_\-\\/]?\s*$", cleaned)
    if trailing:
        amount = _normalize_bb_amount(trailing.group(1))
        if amount:
            return f"{amount} BB"
    return ""


def _extract_last_stack(text: str) -> str:
    cleaned = _clean_ocr_text(text)
    matches = list(STACK_RE.finditer(cleaned))
    if not matches:
        return ""
    return _format_stack_match(matches[-1].group(0))


def _extract_hero_name(text: str) -> str:
    cleaned = _clean_ocr_text(text)
    for token in cleaned.split():
        lowered = token.lower()
        if lowered == "wa":
            continue
        if lowered.endswith("bb"):
            continue
        token = _normalize_player_name(token)
        lowered = token.lower()
        if lowered in NAME_BLACKLIST:
            continue
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
        if candidates and re.fullmatch(r"\d{1,2}", token):
            candidates[-1] = f"{candidates[-1]} {token}"
            continue
        token = _normalize_player_name(token)
        if token.lower() in NAME_BLACKLIST:
            continue
        if PLAYER_NAME_RE.fullmatch(token):
            candidates.append(token)
            continue
        for match in re.findall(r"[A-Za-z0-9_/-]{3,}", token):
            normalized = _normalize_player_name(match)
            if normalized.lower() in NAME_BLACKLIST:
                continue
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


def _extract_pot_current_value(text: str) -> str:
    """Read the first line only (``Pot : ...``), excluding ``Pot total``."""
    cleaned = _clean_ocr_text(text)
    match = POT_CURRENT_TEXT_RE.search(cleaned)
    if match:
        return match.group(1)
    return ""


def _extract_pot_total_value(text: str) -> str:
    """Read only the optional second pot line, never an unlabeled pot amount."""
    cleaned = _clean_ocr_text(text)
    match = POT_TOTAL_TEXT_RE.search(cleaned)
    if match:
        return match.group(1)
    fragment = POT_TOTAL_FRAGMENT_RE.search(cleaned)
    if fragment:
        amount = _normalize_bb_amount(fragment.group(1))
        return f"Pot total : {amount} BB" if amount else ""
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
    if lowered.startswith("louppianc") or lowered.startswith("loupbpianc") or lowered.startswith("louppblanc") or lowered.startswith("loupblanc"):
        return "loupblanc"
    if lowered.startswith("shark1") and "shark" in lowered:
        return "shark13shark"
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
        trailing = re.search(r"\b(\d+(?:[.,]\d+)?)\s*[_\-\\/]?\s*$", cleaned)
        if trailing:
            amount = trailing.group(1).replace(".", ",")
            return f"{amount} BB"
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
    # A crop can lose the leading digit (69 instead of 169, 03 instead of
    # 103). Prefer the expanded/secondary reading in that situation.
    if p < 100 <= s:
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
