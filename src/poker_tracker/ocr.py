from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
import re

from PIL import Image, ImageFilter, ImageGrab, ImageOps

from .config import load_calibration
from .detection import WinamaxWindow


ACTION_FAST_RE = re.compile(r"\b(FOLD|CALL|CHECK|BET|RAISE|ALL-?IN)\b", re.IGNORECASE)
ACTION_NOISE_MARKERS = (
    "voir tes cartes",
    "poser la big blind",
    "poser la small blind",
    "préselection",
    "preselection",
    "selection de la prochaine action",
    "autorebuy",
    "hauteur",
    "prochaine action",
    "attendre",
)


@dataclass(slots=True)
class OcrZoneResult:
    name: str
    image_path: str
    text: str
    rect: tuple[int, int, int, int]


@dataclass(slots=True)
class OcrSnapshot:
    image_path: str
    engine_available: bool
    engine_path: str
    status: str
    text: str
    zones: dict[str, OcrZoneResult] = field(default_factory=dict)


def capture_window(window: WinamaxWindow) -> str | None:
    left, top, right, bottom = window.rect
    if right <= left or bottom <= top:
        return None

    temp_dir = Path(tempfile.gettempdir()) / "winamax_poker_tracker"
    temp_dir.mkdir(parents=True, exist_ok=True)
    image_path = temp_dir / f"table_{window.pid}_{window.hwnd}.png"
    temp_image_path = image_path.with_suffix(".tmp.png")

    image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    image.save(temp_image_path)
    temp_image_path.replace(image_path)
    return str(image_path)


def run_local_ocr(window: WinamaxWindow) -> OcrSnapshot:
    return run_local_ocr_with_profile(window, profile="full")


def run_local_ocr_with_profile(window: WinamaxWindow, profile: str = "full") -> OcrSnapshot:
    image_path = capture_window(window)
    if image_path is None:
        return OcrSnapshot(
            image_path="",
            engine_available=False,
            engine_path="",
            status="capture_failed",
            text="Capture impossible pour cette fenetre.",
            zones={},
        )

    engine_path = _find_tesseract()
    if not engine_path:
        return OcrSnapshot(
            image_path=image_path,
            engine_available=False,
            engine_path="",
            status="tesseract_missing",
            text="Tesseract n'est pas installe ou introuvable dans le PATH.",
            zones={},
        )

    full_text = ""
    if profile == "full":
        completed = _run_tesseract(engine_path, image_path, psm="6")
        if completed.returncode != 0:
            return OcrSnapshot(
                image_path=image_path,
                engine_available=True,
                engine_path=engine_path,
                status="ocr_failed",
                text=(completed.stderr or "").strip() or "Erreur OCR inconnue.",
                zones={},
            )
        full_text = (completed.stdout or "").strip()

    zones = _run_zoned_ocr(engine_path, image_path, profile=profile)
    return OcrSnapshot(
        image_path=image_path,
        engine_available=True,
        engine_path=engine_path,
        status="ok_minimal" if profile == "minimal" else "ok",
        text=full_text,
        zones=zones,
    )


def run_local_ocr_on_image(image_path: str | Path) -> OcrSnapshot:
    return run_local_ocr_on_image_with_profile(image_path, profile="full")


def run_local_ocr_on_image_with_profile(image_path: str | Path, profile: str = "full") -> OcrSnapshot:
    image_path = str(image_path)
    engine_path = _find_tesseract()
    if not engine_path:
        return OcrSnapshot(
            image_path=image_path,
            engine_available=False,
            engine_path="",
            status="tesseract_missing",
            text="Tesseract n'est pas installe ou introuvable dans le PATH.",
            zones={},
        )

    full_text = ""
    if profile == "full":
        completed = _run_tesseract(engine_path, image_path, psm="6")
        if completed.returncode != 0:
            return OcrSnapshot(
                image_path=image_path,
                engine_available=True,
                engine_path=engine_path,
                status="ocr_failed",
                text=(completed.stderr or "").strip() or "Erreur OCR inconnue.",
                zones={},
            )
        full_text = (completed.stdout or "").strip()

    zones = _run_zoned_ocr(engine_path, image_path, profile=profile)
    return OcrSnapshot(
        image_path=image_path,
        engine_available=True,
        engine_path=engine_path,
        status="ok_minimal" if profile == "minimal" else "ok",
        text=full_text,
        zones=zones,
    )


def run_action_ocr_on_image(image_path: str | Path) -> dict[str, str]:
    image_path = str(image_path)
    engine_path = _find_tesseract()
    if not engine_path:
        return {}

    image = Image.open(image_path)
    width, height = image.size
    action_names = {"action_left", "action_center", "action_right", "hero_status", "hero"}
    results: dict[str, str] = {}
    temp_dir = Path(tempfile.gettempdir()) / "winamax_poker_tracker"

    for name, rect, psm in _zone_definitions(width, height):
        if name not in action_names:
            continue
        if name in {"hero_status", "hero"}:
            cropped = _preprocess_text_zone(image.crop(rect))
        else:
            cropped = _preprocess_actions_zone(image.crop(rect))
        zone_path = temp_dir / f"{Path(image_path).stem}_{name}_fast.png"
        cropped.save(zone_path)
        completed = _run_tesseract(engine_path, str(zone_path), psm=psm)
        raw_text = ((completed.stdout or "") if completed.returncode == 0 else "").strip()
        if name in {"hero_status", "hero"}:
            text = " ".join(part.strip() for part in raw_text.splitlines() if part.strip())
        else:
            text = _normalize_action_ocr_text(raw_text)
        results[name] = text

    for name, rect, psm in _zone_definitions(width, height):
        if name != "actions":
            continue
        cropped = _preprocess_actions_zone(image.crop(rect))
        zone_path = temp_dir / f"{Path(image_path).stem}_{name}_fast.png"
        cropped.save(zone_path)
        completed = _run_tesseract(engine_path, str(zone_path), psm=psm)
        raw_text = ((completed.stdout or "") if completed.returncode == 0 else "").strip()
        hint_text = _normalize_fast_hint_text(raw_text)
        if hint_text:
            results["actions_hint"] = hint_text
        text = _normalize_action_fallback_text(raw_text)
        if text:
            results["actions"] = text
        break

    return results


def _normalize_action_ocr_text(text: str) -> str:
    cleaned = " ".join(part.strip() for part in str(text or "").splitlines() if part.strip())
    lowered = cleaned.lower()
    if not cleaned:
        return ""
    if any(marker in lowered for marker in ACTION_NOISE_MARKERS):
        return ""

    matches: list[str] = []
    for match in ACTION_FAST_RE.findall(cleaned):
        token = str(match).upper().replace("ALLIN", "ALL-IN")
        if token not in matches:
            matches.append(token)
    if len(matches) != 1:
        return ""
    return matches[0]


def _normalize_action_fallback_text(text: str) -> str:
    cleaned = " ".join(part.strip() for part in str(text or "").splitlines() if part.strip())
    lowered = cleaned.lower()
    if not cleaned:
        return ""
    if any(marker in lowered for marker in ACTION_NOISE_MARKERS):
        return ""

    matches: list[str] = []
    for match in ACTION_FAST_RE.findall(cleaned):
        token = str(match).upper().replace("ALLIN", "ALL-IN")
        if token not in matches:
            matches.append(token)
    return " ".join(matches)


def _normalize_fast_hint_text(text: str) -> str:
    cleaned = " ".join(part.strip() for part in str(text or "").splitlines() if part.strip())
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    markers = [
        "preselection",
        "préselection",
        "selection de la prochaine action",
        "prochaine action",
        "tu as passe",
        "tu as passé",
        "voir tes cartes",
        "poser la big blind",
        "poser la small blind",
    ]
    for marker in markers:
        if marker in lowered:
            return marker.upper()
    return cleaned


def _find_tesseract() -> str:
    in_path = shutil.which("tesseract")
    if in_path:
        return in_path

    candidates = [
        Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
        Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def _run_tesseract(
    engine_path: str,
    image_path: str,
    psm: str,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    command = [engine_path, image_path, "stdout", "--psm", psm]
    if extra_args:
        command.extend(extra_args)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        startupinfo=startupinfo,
        creationflags=creationflags,
    )


def _run_zoned_ocr(engine_path: str, image_path: str, profile: str = "full") -> dict[str, OcrZoneResult]:
    image = Image.open(image_path)
    width, height = image.size
    temp_dir = Path(tempfile.gettempdir()) / "winamax_poker_tracker"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zones: dict[str, OcrZoneResult] = {}
    allowed = _zone_profile_names(profile)

    for name, rect, psm in _zone_definitions(width, height):
        if allowed is not None and name not in allowed:
            continue
        cropped = image.crop(rect)
        if name in {"actions", "action_left", "action_center", "action_right"}:
            cropped = _preprocess_actions_zone(cropped)
        elif name in {
            "pot",
            "pot_value",
            "hero",
            "hero_name",
            "hero_stack",
            "hero_status",
            "top_left_name",
            "top_left_stack",
            "top_right_name",
            "top_right_stack",
            "left_name",
            "left_stack",
            "right_name",
            "right_stack",
            "dealer_button",
        }:
            cropped = _preprocess_text_zone(cropped)
        elif name in {"board_card_1", "board_card_2", "board_card_3", "board_card_4", "board_card_5"}:
            cropped = _preprocess_card_zone(cropped)
        zone_path = temp_dir / f"{Path(image_path).stem}_{name}.png"
        cropped.save(zone_path)
        completed = _run_tesseract(engine_path, str(zone_path), psm=psm)
        text = ((completed.stdout or "") if completed.returncode == 0 else (completed.stderr or "")).strip()
        zones[name] = OcrZoneResult(name=name, image_path=str(zone_path), text=text, rect=rect)

    return zones


def _zone_profile_names(profile: str) -> set[str] | None:
    if profile == "full":
        return None
    if profile == "live":
        return {
            "top_left_cards",
            "top_left_name",
            "top_left_stack",
            "top_right_cards",
            "top_right_name",
            "top_right_stack",
            "left_cards",
            "left_name",
            "left_stack",
            "right_cards",
            "right_name",
            "right_stack",
            "pot",
            "pot_value",
            "board",
            "board_card_1",
            "board_card_2",
            "board_card_3",
            "board_card_4",
            "board_card_5",
            "hero",
            "hero_name",
            "hero_stack",
            "hero_status",
            "dealer_button",
            "action_left",
            "action_center",
            "action_right",
        }
    if profile == "minimal":
        return {
            "top_left_name", "top_left_stack",
            "top_right_name", "top_right_stack",
            "left_name", "left_stack",
            "right_name", "right_stack",
            "hero_name", "hero_stack", "hero_status",
            "pot", "pot_value", "board",
        }
    return None


def _zone_definitions(width: int, height: int) -> list[tuple[str, tuple[int, int, int, int], str]]:
    calibration = load_calibration()
    zones = calibration.get("zones", {})
    return [
        ("top_bar", _scaled_rect(width, height, *zones["top_bar"]), "6"),
        ("top_left_cards", _scaled_rect(width, height, *zones["top_left_cards"]), "6"),
        ("top_left_name", _scaled_rect(width, height, *zones["top_left_name"]), "7"),
        ("top_left_stack", _scaled_rect(width, height, *zones["top_left_stack"]), "7"),
        ("top_right_cards", _scaled_rect(width, height, *zones["top_right_cards"]), "6"),
        ("top_right_name", _scaled_rect(width, height, *zones["top_right_name"]), "7"),
        ("top_right_stack", _scaled_rect(width, height, *zones["top_right_stack"]), "7"),
        ("left_cards", _scaled_rect(width, height, *zones["left_cards"]), "6"),
        ("left_name", _scaled_rect(width, height, *zones["left_name"]), "7"),
        ("left_stack", _scaled_rect(width, height, *zones["left_stack"]), "7"),
        ("right_cards", _scaled_rect(width, height, *zones["right_cards"]), "6"),
        ("right_name", _scaled_rect(width, height, *zones["right_name"]), "7"),
        ("right_stack", _scaled_rect(width, height, *zones["right_stack"]), "7"),
        ("pot", _scaled_rect(width, height, *zones["pot"]), "6"),
        ("pot_value", _scaled_rect(width, height, *zones["pot_value"]), "7"),
        ("board", _scaled_rect(width, height, *zones["board"]), "6"),
        ("board_card_1", _scaled_rect(width, height, *zones["board_card_1"]), "10"),
        ("board_card_2", _scaled_rect(width, height, *zones["board_card_2"]), "10"),
        ("board_card_3", _scaled_rect(width, height, *zones["board_card_3"]), "10"),
        ("board_card_4", _scaled_rect(width, height, *zones["board_card_4"]), "10"),
        ("board_card_5", _scaled_rect(width, height, *zones["board_card_5"]), "10"),
        ("hero", _scaled_rect(width, height, *zones["hero"]), "6"),
        ("hero_name", _scaled_rect(width, height, *zones["hero_name"]), "7"),
        ("hero_stack", _scaled_rect(width, height, *zones["hero_stack"]), "7"),
        ("hero_status", _scaled_rect(width, height, *zones["hero_status"]), "7"),
        ("dealer_button", _scaled_rect(width, height, *zones["dealer_button"]), "10"),
        ("actions", _scaled_rect(width, height, *zones["actions"]), "6"),
        ("action_left", _scaled_rect(width, height, *zones["action_left"]), "8"),
        ("action_center", _scaled_rect(width, height, *zones["action_center"]), "8"),
        ("action_right", _scaled_rect(width, height, *zones["action_right"]), "8"),
        ("left_opponent", _scaled_rect(width, height, *zones["left_opponent"]), "6"),
        ("right_opponent", _scaled_rect(width, height, *zones["right_opponent"]), "6"),
    ]


def _scaled_rect(
    width: int,
    height: int,
    left_ratio: float,
    top_ratio: float,
    right_ratio: float,
    bottom_ratio: float,
) -> tuple[int, int, int, int]:
    # Backward-compatible: if a zone was entered as (left, top, width, height),
    # convert it on the fly instead of crashing the whole app.
    if right_ratio <= left_ratio:
        right_ratio = left_ratio + right_ratio
    if bottom_ratio <= top_ratio:
        bottom_ratio = top_ratio + bottom_ratio

    right_ratio = min(1.0, right_ratio)
    bottom_ratio = min(1.0, bottom_ratio)

    left = max(0, int(width * left_ratio))
    top = max(0, int(height * top_ratio))
    right = min(width, int(width * right_ratio))
    bottom = min(height, int(height * bottom_ratio))

    if right <= left:
        right = min(width, left + 1)
    if bottom <= top:
        bottom = min(height, top + 1)

    return (
        left,
        top,
        right,
        bottom,
    )


def _preprocess_actions_zone(image: Image.Image) -> Image.Image:
    processed = image.convert("L")
    processed = ImageOps.autocontrast(processed)
    processed = processed.resize((processed.width * 2, processed.height * 2))
    processed = processed.filter(ImageFilter.SHARPEN)
    processed = processed.point(lambda p: 255 if p > 150 else 0)
    return processed


def _preprocess_text_zone(image: Image.Image) -> Image.Image:
    processed = image.convert("L")
    processed = ImageOps.autocontrast(processed)
    processed = processed.resize((processed.width * 2, processed.height * 2))
    return processed


def _preprocess_card_zone(image: Image.Image) -> Image.Image:
    processed = image.convert("L")
    processed = ImageOps.autocontrast(processed)
    processed = processed.resize((processed.width * 3, processed.height * 3))
    processed = processed.filter(ImageFilter.SHARPEN)
    processed = processed.point(lambda p: 255 if p > 170 else 0)
    return processed
