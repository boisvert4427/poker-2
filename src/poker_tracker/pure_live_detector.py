from __future__ import annotations

import csv
from difflib import SequenceMatcher
import io
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from .ocr import OcrSnapshot, run_local_ocr_on_image


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
]

STACK_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*BB\b", re.IGNORECASE)
PLAYER_NAME_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_]{3,}(?:\s+\d+)?\b")
POT_TEXT_RE = re.compile(r"(Pot(?:\s+total)?\s*:\s*[\d.,]+\s*BB)", re.IGNORECASE)
BB_VALUE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:BB|B8|68|BES|B)\b", re.IGNORECASE)
NAME_BLACKLIST = {
    "winamax",
    "wichita",
    "anaheim",
    "holdem",
    "limit",
    "playground",
    "move",
    "straight",
    "all",
    "in",
    "allin",
    "hauteur",
    "autorebuy",
    "dautorebuy",
    "tu",
    "pass",
    "avec",
    "pots",
    "pot",
    "blind",
    "small",
    "big",
    "cashgame",
    "recaver",
    "thi",
    "ply",
    "gar",
    "ote",
    "ria",
    "absent",
    "total",
    "adelante",
}

SEAT_SEARCH_REGIONS = {
    "top_left": (0.22, 0.11, 0.40, 0.22),
    "top_right": (0.56, 0.11, 0.74, 0.22),
    "right": (0.66, 0.55, 0.86, 0.66),
    "hero": (0.40, 0.73, 0.58, 0.84),
}

DEALER_SEARCH_REGIONS = {
    "left": (0.08, 0.54, 0.18, 0.68),
    "top_left": (0.26, 0.19, 0.36, 0.31),
    "top_right": (0.60, 0.19, 0.70, 0.31),
    "right": (0.70, 0.54, 0.80, 0.68),
    "hero": (0.43, 0.64, 0.55, 0.75),
}


class LiveSeatMemory:
    def __init__(self) -> None:
        self.names: dict[str, str] = {}
        self.dealer_owner: str = ""
        self.hand_id: str = ""

    def refine(self, fields: dict[str, dict[str, Any]], hand_id: str = "") -> dict[str, dict[str, Any]]:
        if hand_id and self.hand_id and hand_id != self.hand_id:
            self.names = {}
            self.dealer_owner = ""
        if hand_id:
            self.hand_id = hand_id

        for seat in ("top_left", "top_right", "right"):
            name_key = f"{seat}_name"
            stack_key = f"{seat}_stack"
            cards_key = f"{seat}_cards_visible"
            current_name = (fields.get(name_key, {}) or {}).get("value", "")
            current_stack = (fields.get(stack_key, {}) or {}).get("value", "")
            cards_visible = (fields.get(cards_key, {}) or {}).get("value", "")
            remembered = self.names.get(seat, "")

            if _is_plausible_name(current_name):
                if remembered:
                    if _looks_like_same_player(current_name, remembered):
                        best = remembered if len(remembered) >= len(current_name) else current_name
                        self.names[seat] = best
                        fields[name_key]["value"] = best
                    else:
                        fields[name_key]["value"] = remembered
                        fields[name_key]["visible"] = True
                else:
                    self.names[seat] = current_name
                continue

            if seat == "top_right" and not current_name and not current_stack and cards_visible == "not_visible":
                continue

            if remembered:
                fields[name_key]["value"] = remembered
                fields[name_key]["visible"] = True

        current_dealer = (fields.get("dealer_button", {}) or {}).get("value", "")
        if current_dealer:
            if not self.dealer_owner:
                self.dealer_owner = current_dealer
            elif self.dealer_owner != current_dealer:
                fields["dealer_button"]["value"] = self.dealer_owner
                fields["dealer_button"]["visible"] = True
        elif self.dealer_owner:
            fields["dealer_button"]["value"] = self.dealer_owner
            fields["dealer_button"]["visible"] = True
        return fields


def analyze_live_image(
    image_path: str | Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = run_local_ocr_on_image(image_path)
    fields = detect_live_fields(snapshot, metadata=metadata or {})
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


def save_live_analysis(image_path: str | Path, metadata: dict[str, Any] | None = None) -> Path:
    image_path = Path(image_path)
    payload = analyze_live_image(image_path, metadata=metadata)
    target = image_path.with_suffix(".live.json")
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def detect_live_fields(ocr_snapshot: OcrSnapshot, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    zones = ocr_snapshot.zones or {}
    full_text = _clean_text(ocr_snapshot.text)
    hero_name = ((metadata.get("live_snapshot") or {}).get("hero_name", "") or "").strip()
    name_candidates = _extract_name_candidates(ocr_snapshot.text, hero_name=hero_name)
    tsv_words = _extract_tsv_words(ocr_snapshot.image_path)
    seat_names = _seat_names_from_tsv(tsv_words, ocr_snapshot.image_path, hero_name=hero_name)
    player_map = {**_assign_player_names(name_candidates), **seat_names}
    stack_candidates = _extract_stack_candidates(ocr_snapshot.text)
    dealer_owner = _detect_dealer_owner(ocr_snapshot.image_path, zones)

    def zone_text(name: str) -> str:
        zone = zones.get(name)
        return (zone.text or "").strip() if zone else ""

    def zone_image_path(name: str) -> str:
        zone = zones.get(name)
        return (zone.image_path or "").strip() if zone else ""

    hero_block = _clean_text(zone_text("hero"))
    left_block = _clean_text(zone_text("left_opponent"))
    right_block = _clean_text(zone_text("right_opponent"))

    values = {
        "top_left_cards_visible": _detect_cards_visible(zone_image_path("top_left_cards")),
        "top_left_name": _first_non_empty(
            seat_names.get("top_left", ""),
            _plausible_name(_clean_player_name(zone_text("top_left_name"))),
            player_map.get("top_left", ""),
        ),
        "top_left_stack": _first_non_empty(
            _extract_stack(zone_text("top_left_stack")),
            _extract_stack(left_block) if "top_left" in player_map else "",
            stack_candidates.get("top_left", ""),
        ),
        "top_right_cards_visible": _detect_cards_visible(zone_image_path("top_right_cards")),
        "top_right_name": _first_non_empty(
            seat_names.get("top_right", ""),
            _plausible_name(_clean_player_name(zone_text("top_right_name"))),
            player_map.get("top_right", ""),
        ),
        "top_right_stack": _first_non_empty(
            _extract_stack(zone_text("top_right_stack")),
            stack_candidates.get("top_right", ""),
        ),
        "right_cards_visible": _detect_cards_visible(zone_image_path("right_cards")),
        "right_name": _first_non_empty(
            seat_names.get("right", ""),
            _plausible_name(_clean_player_name(zone_text("right_name"))),
            _plausible_name(_clean_player_name(right_block)),
            player_map.get("right", ""),
        ),
        "right_stack": _first_non_empty(
            _extract_stack(zone_text("right_stack")),
            _extract_stack(right_block),
            stack_candidates.get("right", ""),
        ),
        "hero_name": _first_non_empty(
            _extract_hero_name(hero_block),
            _plausible_name(_clean_player_name(zone_text("hero_name"))),
            hero_name,
            seat_names.get("hero", ""),
        ),
        "hero_stack": _first_non_empty(
            _extract_stack(hero_block),
            _extract_stack(zone_text("hero_stack")),
            stack_candidates.get("hero", ""),
        ),
        "hero_status": _clean_text(zone_text("hero_status")),
        "pot_value": _first_non_empty(
            _extract_pot_value(zone_text("pot_value")),
            _extract_pot_value(zone_text("pot")),
            _extract_pot_value(full_text),
        ),
        "dealer_button": dealer_owner,
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


def _clean_text(value: str) -> str:
    return " ".join(part.strip() for part in value.splitlines() if part.strip()).strip()


def _first_non_empty(*values: str) -> str:
    for value in values:
        if value and value != "-":
            return value
    return ""


def _extract_hero_name(text: str) -> str:
    for token in _clean_text(text).split():
        low = token.lower()
        if low.endswith("bb") or low in {"wa", "tu", "pass"}:
            continue
        if PLAYER_NAME_RE.fullmatch(token):
            return token
    return ""


def _clean_player_name(text: str) -> str:
    cleaned = _clean_text(text).replace("Â©", " ").replace("â€™", "'")
    candidates = []
    for match in PLAYER_NAME_RE.findall(cleaned):
        token = " ".join(match.split())
        if token.lower() in NAME_BLACKLIST:
            continue
        candidates.append(token)
    return candidates[0] if candidates else ""


def _extract_name_candidates(text: str, hero_name: str) -> list[str]:
    candidates: list[str] = []
    for raw_line in text.splitlines():
        cleaned = _clean_text(raw_line)
        if not cleaned:
            continue
        for match in PLAYER_NAME_RE.findall(cleaned):
            token = " ".join(match.split())
            low = token.lower()
            if low in NAME_BLACKLIST or low == hero_name.lower():
                continue
            if not _is_plausible_name(token):
                continue
            if token not in candidates:
                candidates.append(token)
    return candidates


def _assign_player_names(candidates: list[str]) -> dict[str, str]:
    filtered = [candidate for candidate in candidates if candidate]
    if len(filtered) >= 3:
        return {
            "top_left": filtered[0],
            "top_right": filtered[1],
            "right": filtered[2],
        }
    if len(filtered) == 2:
        return {
            "top_left": filtered[0],
            "right": filtered[1],
        }
    if len(filtered) == 1:
        return {"top_left": filtered[0]}
    return {}


def _is_plausible_name(value: str) -> bool:
    token = " ".join((value or "").split()).strip()
    if not token:
        return False
    if token.lower() in NAME_BLACKLIST:
        return False
    head = token.split()[0]
    if len(head) < 4:
        return False
    if not re.search(r"[aeiouyAEIOUY]", head):
        return False
    return True


def _plausible_name(value: str) -> str:
    return value if _is_plausible_name(value) else ""


def _looks_like_same_player(left: str, right: str) -> bool:
    a = " ".join((left or "").lower().split())
    b = " ".join((right or "").lower().split())
    if not a or not b:
        return False
    if a == b:
        return True
    if a.startswith(b[:5]) or b.startswith(a[:5]):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.72


def _extract_stack(text: str) -> str:
    cleaned = _clean_text(text)
    match = STACK_RE.search(cleaned)
    if match:
        return _normalize_stack_token(match.group(0))

    raw_match = BB_VALUE_RE.search(cleaned)
    if raw_match:
        amount = _normalize_numeric_token(raw_match.group(1))
        return f"{amount} BB" if amount else ""
    return ""


def _extract_stack_candidates(text: str) -> dict[str, str]:
    values = []
    for match in BB_VALUE_RE.finditer(_clean_text(text)):
        amount = _normalize_numeric_token(match.group(1))
        if not amount:
            continue
        if amount not in values:
            values.append(amount)

    filtered = []
    for amount in values:
        if amount in {"0,01", "0,02", "2", "4", "9"}:
            continue
        filtered.append(f"{amount} BB")

    mapping: dict[str, str] = {}
    if len(filtered) >= 1:
        mapping["top_left"] = filtered[0]
    if len(filtered) >= 2:
        mapping["right"] = filtered[-2] if len(filtered) > 2 else filtered[-1]
    if len(filtered) >= 3:
        mapping["hero"] = filtered[-1]
    return mapping


def _normalize_stack_token(token: str) -> str:
    amount = _normalize_numeric_token(token)
    return f"{amount} BB" if amount else ""


def _normalize_numeric_token(token: str) -> str:
    token = token.strip().replace("BB", "").replace("B", "").strip()
    token = token.replace(".", ",")
    token = re.sub(r"[^0-9,]", "", token)
    if not token:
        return ""
    if "," in token:
        head, tail = token.split(",", 1)
        tail = re.sub(r"[^0-9]", "", tail)[:1]
        return f"{head},{tail}" if tail else head
    if len(token) >= 3 and token[-1].isdigit():
        return f"{token[:-1]},{token[-1]}"
    return token


def _extract_pot_value(text: str) -> str:
    cleaned = _clean_text(text)
    match = POT_TEXT_RE.search(cleaned)
    if match:
        return _normalize_pot_token(match.group(1))
    bb_match = BB_VALUE_RE.search(cleaned)
    if bb_match:
        amount = _normalize_numeric_token(bb_match.group(1))
        return f"Pot : {amount} BB" if amount else ""
    return ""


def _normalize_pot_token(token: str) -> str:
    amount_match = re.search(r"(\d+(?:[.,]\d+)?)", token)
    if not amount_match:
        return ""
    amount = _normalize_numeric_token(amount_match.group(1))
    return f"Pot : {amount} BB" if amount else ""


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


def _detect_dealer_owner(image_path: str, zones: dict[str, Any]) -> str:
    if not image_path or not Path(image_path).exists():
        return ""
    try:
        image = Image.open(image_path).convert("RGB")
    except OSError:
        return ""

    candidates = _yellow_components(image)
    if not candidates:
        candidates = _orange_components(image)
    if not candidates:
        return ""

    try:
        width, height = image.size
    except OSError:
        return ""
    best_name = ""
    best_area = 0
    for seat, region in DEALER_SEARCH_REGIONS.items():
        x1, y1, x2, y2 = region[0] * width, region[1] * height, region[2] * width, region[3] * height
        seat_components = [
            component
            for component in candidates
            if x1 <= component["centroid"][0] <= x2 and y1 <= component["centroid"][1] <= y2
        ]
        if not seat_components:
            continue
        area = max(component.get("area", 0) for component in seat_components)
        if area > best_area:
            best_area = area
            best_name = seat
    if best_name:
        return best_name

    anchors = _seat_anchors(zones)
    if not anchors:
        return ""
    best_fallback = ""
    best_score = None
    for component in candidates:
        centroid = component["centroid"]
        nearest = min(
            anchors.items(),
            key=lambda item: (item[1][0] - centroid[0]) ** 2 + (item[1][1] - centroid[1]) ** 2,
        )
        dist2 = (nearest[1][0] - centroid[0]) ** 2 + (nearest[1][1] - centroid[1]) ** 2
        score = dist2 / max(component.get("area", 1), 1)
        if best_score is None or score < best_score:
            best_score = score
            best_fallback = nearest[0]
    return best_fallback


def _extract_tsv_words(image_path: str) -> list[dict[str, Any]]:
    if not image_path or not Path(image_path).exists():
        return []
    exe = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
    if not exe.exists():
        return []
    startupinfo = None
    creationflags = 0
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    except AttributeError:
        startupinfo = None

    completed = subprocess.run(
        [str(exe), image_path, "stdout", "--psm", "6", "tsv"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []

    words: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(completed.stdout), delimiter="\t"):
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            left = int(row.get("left") or 0)
            top = int(row.get("top") or 0)
            width = int(row.get("width") or 0)
            height = int(row.get("height") or 0)
            conf = float(row.get("conf") or 0)
        except ValueError:
            continue
        words.append(
            {
                "text": text,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "conf": conf,
                "center_x": left + width / 2,
                "center_y": top + height / 2,
            }
        )
    return words


def _seat_names_from_tsv(words: list[dict[str, Any]], image_path: str, hero_name: str) -> dict[str, str]:
    if not words or not image_path:
        return {}
    try:
        width, height = Image.open(image_path).size
    except OSError:
        return {}

    results: dict[str, str] = {}
    for seat, region in SEAT_SEARCH_REGIONS.items():
        left, top, right, bottom = region
        x1, y1, x2, y2 = left * width, top * height, right * width, bottom * height
        region_words = [
            word
            for word in words
            if x1 <= word["center_x"] <= x2 and y1 <= word["center_y"] <= y2 and _is_candidate_word(word, hero_name)
        ]
        if not region_words:
            continue
        region_words.sort(key=lambda item: (item["top"], item["left"]))
        grouped = _group_words_by_line(region_words)
        candidates = [_words_to_name(line) for line in grouped]
        candidates = [candidate for candidate in candidates if _is_plausible_name(candidate)]
        if candidates:
            results[seat] = max(candidates, key=len)
    return results


def _is_candidate_word(word: dict[str, Any], hero_name: str) -> bool:
    text = " ".join((word.get("text") or "").split()).strip()
    if not text:
        return False
    low = text.lower()
    if low == hero_name.lower():
        return True
    if low in NAME_BLACKLIST:
        return False
    if not (re.search(r"[a-zA-Z]", text) or re.fullmatch(r"\d+", text)):
        return False
    if word.get("conf", 0) < 40:
        return False
    return True


def _group_words_by_line(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (item["top"], item["left"])):
        placed = False
        center_y = word["center_y"]
        for line in lines:
            avg_y = sum(item["center_y"] for item in line) / len(line)
            if abs(center_y - avg_y) <= max(10, word["height"] * 0.8):
                line.append(word)
                placed = True
                break
        if not placed:
            lines.append([word])
    for line in lines:
        line.sort(key=lambda item: item["left"])
    return lines


def _words_to_name(words: list[dict[str, Any]]) -> str:
    tokens: list[str] = []
    for word in words:
        text = " ".join((word.get("text") or "").split()).strip()
        if not text:
            continue
        if text.lower() in NAME_BLACKLIST:
            continue
        if re.fullmatch(r"\d+", text):
            if tokens:
                tokens.append(text)
            continue
        tokens.append(text)
    return " ".join(tokens[:2]).strip()


def _seat_anchors(zones: dict[str, Any]) -> dict[str, tuple[float, float]]:
    anchors: dict[str, tuple[float, float]] = {}
    zone_map = {
        "top_left": "top_left_name",
        "top_right": "top_right_name",
        "right": "right_name",
        "hero": "hero_name",
        "left": "left_opponent",
    }
    for name, zone_name in zone_map.items():
        zone = zones.get(zone_name)
        if not zone:
            continue
        left, top, right, bottom = zone.rect
        anchors[name] = ((left + right) / 2, (top + bottom) / 2)
    return anchors


def _orange_components(image: Image.Image) -> list[dict[str, Any]]:
    width, height = image.size
    step = 3
    pixels = image.load()
    mask: dict[tuple[int, int], bool] = {}
    for y in range(0, height, step):
        for x in range(0, width, step):
            r, g, b = pixels[x, y]
            if r > 170 and g > 90 and b < 120 and r > g * 0.95:
                mask[(x // step, y // step)] = True

    visited: set[tuple[int, int]] = set()
    components: list[dict[str, Any]] = []
    for start in mask:
        if start in visited:
            continue
        queue = [start]
        visited.add(start)
        pts = []
        while queue:
            cx, cy = queue.pop()
            pts.append((cx, cy))
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if (nx, ny) in mask and (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append((nx, ny))
        if len(pts) < 20:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        width_cells = max_x - min_x + 1
        height_cells = max_y - min_y + 1
        aspect = width_cells / max(1, height_cells)
        if aspect < 0.5 or aspect > 1.8:
            continue
        centroid = ((sum(xs) / len(xs)) * step, (sum(ys) / len(ys)) * step)
        score = len(pts) / max(1, width_cells * height_cells)
        components.append({"centroid": centroid, "score": score, "area": len(pts)})
    return components


def _yellow_components(image: Image.Image) -> list[dict[str, Any]]:
    width, height = image.size
    step = 2
    pixels = image.load()
    mask: dict[tuple[int, int], bool] = {}
    for y in range(0, height, step):
        for x in range(0, width, step):
            r, g, b = pixels[x, y]
            if r > 180 and g > 130 and b < 150 and r > g * 0.92:
                mask[(x // step, y // step)] = True

    visited: set[tuple[int, int]] = set()
    components: list[dict[str, Any]] = []
    for start in mask:
        if start in visited:
            continue
        queue = [start]
        visited.add(start)
        pts = []
        while queue:
            cx, cy = queue.pop()
            pts.append((cx, cy))
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if (nx, ny) in mask and (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append((nx, ny))
        if len(pts) < 20:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        width_cells = max_x - min_x + 1
        height_cells = max_y - min_y + 1
        aspect = width_cells / max(1, height_cells)
        if aspect < 0.5 or aspect > 1.8:
            continue
        area = len(pts)
        if area > 260:
            continue
        centroid = ((sum(xs) / len(xs)) * step, (sum(ys) / len(ys)) * step)
        score = area / max(1, width_cells * height_cells)
        components.append({"centroid": centroid, "score": score, "area": area})
    return components
