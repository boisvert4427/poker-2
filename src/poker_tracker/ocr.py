from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageFilter, ImageGrab, ImageOps

from .config import load_calibration
from .detection import WinamaxWindow


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

    image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    image.save(image_path)
    return str(image_path)


def run_local_ocr(window: WinamaxWindow) -> OcrSnapshot:
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

    zones = _run_zoned_ocr(engine_path, image_path)
    return OcrSnapshot(
        image_path=image_path,
        engine_available=True,
        engine_path=engine_path,
        status="ok",
        text=(completed.stdout or "").strip(),
        zones=zones,
    )


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


def _run_tesseract(engine_path: str, image_path: str, psm: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [engine_path, image_path, "stdout", "--psm", psm],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )


def _run_zoned_ocr(engine_path: str, image_path: str) -> dict[str, OcrZoneResult]:
    image = Image.open(image_path)
    width, height = image.size
    temp_dir = Path(tempfile.gettempdir()) / "winamax_poker_tracker"
    zones: dict[str, OcrZoneResult] = {}

    for name, rect, psm in _zone_definitions(width, height):
        cropped = image.crop(rect)
        if name in {"actions", "action_left", "action_center", "action_right"}:
            cropped = _preprocess_actions_zone(cropped)
        elif name in {"pot", "hero"}:
            cropped = _preprocess_text_zone(cropped)
        zone_path = temp_dir / f"{Path(image_path).stem}_{name}.png"
        cropped.save(zone_path)
        completed = _run_tesseract(engine_path, str(zone_path), psm=psm)
        text = ((completed.stdout or "") if completed.returncode == 0 else (completed.stderr or "")).strip()
        zones[name] = OcrZoneResult(name=name, image_path=str(zone_path), text=text, rect=rect)

    return zones


def _zone_definitions(width: int, height: int) -> list[tuple[str, tuple[int, int, int, int], str]]:
    calibration = load_calibration()
    zones = calibration.get("zones", {})
    return [
        ("top_bar", _scaled_rect(width, height, *zones["top_bar"]), "6"),
        ("pot", _scaled_rect(width, height, *zones["pot"]), "6"),
        ("board", _scaled_rect(width, height, *zones["board"]), "6"),
        ("hero", _scaled_rect(width, height, *zones["hero"]), "6"),
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
    return (
        max(0, int(width * left_ratio)),
        max(0, int(height * top_ratio)),
        min(width, int(width * right_ratio)),
        min(height, int(height * bottom_ratio)),
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
