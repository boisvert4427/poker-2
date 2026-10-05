from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
import re

from PIL import Image, ImageFilter, ImageGrab, ImageOps

from .config import calibration_profile, detect_calibration_profile, load_calibration
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
    calibration_profile: str = "5max"


def capture_window(window: WinamaxWindow, *, destination: str | Path | None = None) -> str | None:
    left, top, right, bottom = window.rect
    if right <= left or bottom <= top:
        return None

    if destination is None:
        temp_dir = Path(tempfile.gettempdir()) / "winamax_poker_tracker"
        temp_dir.mkdir(parents=True, exist_ok=True)
        image_path = temp_dir / f"table_{window.pid}_{window.hwnd}.png"
    else:
        image_path = Path(destination)
        image_path.parent.mkdir(parents=True, exist_ok=True)

    # Several live workers can capture the same table concurrently. A unique
    # temporary file prevents one worker from replacing another worker's PNG.
    temp_image_path = image_path.with_name(
        f".{image_path.stem}.{uuid.uuid4().hex}.tmp{image_path.suffix or '.png'}"
    )

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

    table_profile = detect_calibration_profile(image_path)
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

    with calibration_profile(table_profile):
        zones = _run_zoned_ocr(engine_path, image_path, profile=profile)
    return OcrSnapshot(
        image_path=image_path,
        engine_available=True,
        engine_path=engine_path,
        status="ok_minimal" if profile == "minimal" else "ok",
        text=full_text,
        zones=zones,
        calibration_profile=table_profile,
    )


def run_local_ocr_on_image(image_path: str | Path) -> OcrSnapshot:
    return run_local_ocr_on_image_with_profile(image_path, profile="full")


def run_local_ocr_on_image_with_profile(
    image_path: str | Path,
    profile: str = "full",
    excluded_seats: set[str] | None = None,
) -> OcrSnapshot:
    image_path = str(image_path)
    table_profile = detect_calibration_profile(image_path)
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

    with calibration_profile(table_profile):
        zones = _run_zoned_ocr(
            engine_path, image_path, profile=profile, excluded_seats=excluded_seats
        )
    return OcrSnapshot(
        image_path=image_path,
        engine_available=True,
        engine_path=engine_path,
        status="ok_minimal" if profile == "minimal" else "ok",
        text=full_text,
        zones=zones,
        calibration_profile=table_profile,
    )


def read_call_amount_retry(image_path: str | Path) -> str:
    """One bounded retry on the centre button, with a different segmentation.

    Preserve the label alongside its amount so callers cannot mistake a raise
    sizing for the amount to call. Never combine different capture frames.
    """
    engine = _find_tesseract()
    if not engine:
        return ""
    with Image.open(image_path) as source:
        rect = next(rect for name, rect, _ in _zone_definitions(*source.size)
                    if name == "action_center")
        crop = source.crop(rect).convert("L")
    # The upper half contains only the amount ("8 BB", "3,5 BB"). Reading
    # CALL and the keyboard shortcut at the same time was the source of the
    # remaining failures.
    amount_crop = crop.crop((0, 0, crop.width, max(1, int(crop.height * 0.58))))
    amount_crop = ImageOps.autocontrast(amount_crop)
    amount_crop = amount_crop.resize((amount_crop.width * 4, amount_crop.height * 4))
    with tempfile.TemporaryDirectory(prefix="poker_call_retry_") as directory:
        amount_target = Path(directory) / "amount.png"
        amount_crop.save(amount_target)
        amount_result = _run_tesseract(
            engine,
            str(amount_target),
            psm="6",
            extra_args=["-c", "tessedit_char_whitelist=0123456789,.BBC"],
        )
        amount_text = (amount_result.stdout or "").strip().replace(" ", "")
        # Preserve the unit: a numeric-only whitelist can turn BB into 6/8
        # and silently concatenate it with the actual amount (4 BB -> 46).
        match = re.fullmatch(r"(\d+(?:[.,]\d+)?)BB(?:C)?", amount_text)
        if amount_result.returncode == 0 and match:
            return f"{match.group(1)} BB CALL"

        target = Path(directory) / "center.png"
        crop = ImageOps.autocontrast(crop).resize((crop.width * 3, crop.height * 3))
        crop.save(target)
        result = _run_tesseract(engine, str(target), psm="6")
        return result.stdout.strip() if result.returncode == 0 else ""


def run_action_ocr_on_image(image_path: str | Path) -> dict[str, str]:
    image_path = str(image_path)
    engine_path = _find_tesseract()
    if not engine_path:
        return {}

    image = Image.open(image_path)
    width, height = image.size
    action_names = {"action_left", "action_center", "action_right", "hero_status", "hero", "actions"}
    results: dict[str, str] = {}
    temp_dir = Path(tempfile.gettempdir()) / "winamax_poker_tracker"
    jobs: list[tuple[str, str, Path]] = []
    for name, rect, psm in _zone_definitions(width, height):
        if name not in action_names:
            continue
        if name in {"hero_status", "hero"}:
            cropped = _preprocess_text_zone(image.crop(rect))
        else:
            cropped = _preprocess_actions_zone(image.crop(rect))
        zone_path = temp_dir / f"{Path(image_path).stem}_{name}_fast.png"
        cropped.save(zone_path)
        jobs.append((name, psm, zone_path))

    def read_fast_zone(job: tuple[str, str, Path]) -> tuple[str, str]:
        name, psm, zone_path = job
        completed = _run_tesseract(engine_path, str(zone_path), psm=psm)
        raw_text = ((completed.stdout or "") if completed.returncode == 0 else "").strip()
        return name, raw_text

    with ThreadPoolExecutor(max_workers=min(6, len(jobs))) as executor:
        raw_results = dict(executor.map(read_fast_zone, jobs))

    for name in ("action_left", "action_center", "action_right", "hero_status", "hero"):
        raw_text = raw_results.get(name, "")
        if name in {"hero_status", "hero"}:
            results[name] = " ".join(part.strip() for part in raw_text.splitlines() if part.strip())
        else:
            results[name] = _normalize_action_ocr_text(raw_text)
    raw_actions = raw_results.get("actions", "")
    if raw_actions:
        hint_text = _normalize_fast_hint_text(raw_actions)
        if hint_text:
            results["actions_hint"] = hint_text
        text = _normalize_action_fallback_text(raw_actions)
        if text:
            results["actions"] = text

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


def _run_zoned_ocr(
    engine_path: str,
    image_path: str,
    profile: str = "full",
    excluded_seats: set[str] | None = None,
) -> dict[str, OcrZoneResult]:
    image = Image.open(image_path)
    width, height = image.size
    temp_dir = Path(tempfile.gettempdir()) / "winamax_poker_tracker"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zones: dict[str, OcrZoneResult] = {}
    allowed = _zone_profile_names(profile)
    excluded_seats = set(excluded_seats or ())
    image_only_zones = {"top_left_cards", "top_right_cards", "left_cards", "right_cards"}

    jobs: list[tuple[str, tuple[int, int, int, int], str, Path]] = []
    for name, rect, psm in _zone_definitions(width, height):
        if allowed is not None and name not in allowed:
            continue
        if any(name in {f"{seat}_stack", f"{seat}_bet"} for seat in excluded_seats):
            continue
        if name in {"left_action", "right_action"}:
            # Lateral action labels extend below the old crop; shift without
            # changing its size, scaled to the captured window height.
            shift = round(height * 8 / 1048)
            x0, y0, x1, y1 = rect
            rect = (x0, y0 + shift, x1, min(height, y1 + shift))
        cropped = image.crop(rect)
        skip_empty_bet = (
            profile.startswith("live")
            and name in {"top_left_bet", "top_right_bet", "left_bet", "right_bet", "hero_bet"}
            and not _bet_marker_visible(cropped)
        )
        if name in {"actions", "action_left", "action_center", "action_right"}:
            cropped = _preprocess_actions_zone(cropped)
        elif name in {"top_left_action", "top_right_action", "left_action", "right_action"}:
            cropped = _preprocess_villain_action(cropped)
        elif name in {
            "pot",
            "pot_value",
            "hero",
            "hero_name",
            "hero_stack",
            "hero_status",
            "top_left_name",
            "top_left_stack",
            "top_left_bet",
            "top_left_action",
            "top_right_name",
            "top_right_stack",
            "top_right_bet",
            "top_right_action",
            "left_name",
            "left_stack",
            "left_bet",
            "left_action",
            "right_name",
            "right_stack",
            "right_bet",
            "right_action",
            "hero_bet",
            "dealer_button",
        }:
            cropped = _preprocess_text_zone(cropped)
        elif name in {"board_card_1", "board_card_2", "board_card_3", "board_card_4", "board_card_5"}:
            cropped = _preprocess_card_zone(cropped)
        zone_path = temp_dir / f"{Path(image_path).stem}_{name}.png"
        cropped.save(zone_path)
        # Card-back presence is determined from pixels by
        # ``_detect_cards_visible``. OCR text from these four crops is never
        # consumed, so launching Tesseract here was strictly redundant.
        if profile.startswith("live") and (name in image_only_zones or skip_empty_bet):
            zones[name] = OcrZoneResult(name=name, image_path=str(zone_path), text="", rect=rect)
            continue
        jobs.append((name, rect, psm, zone_path))

    def read_zone(job: tuple[str, tuple[int, int, int, int], str, Path]) -> tuple[str, tuple[int, int, int, int], Path, str]:
        name, rect, psm, zone_path = job
        completed = _run_tesseract(engine_path, str(zone_path), psm=psm)
        text = ((completed.stdout or "") if completed.returncode == 0 else (completed.stderr or "")).strip()
        return name, rect, zone_path, text

    # Each zone is independent.  Running the Tesseract processes concurrently
    # removes the sequential process-startup cost while keeping the same OCR
    # settings and the same fallback behavior.
    # Live contains many tiny independent crops. Tesseract is constrained to
    # one OpenMP thread per process, so a larger pool reduces startup waves
    # without multiplying the internal OCR thread count.
    worker_limit = 16 if profile.startswith("live") else 8
    worker_count = min(worker_limit, max(1, len(jobs)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(read_zone, jobs))
    for name, rect, zone_path, text in results:
        zones[name] = OcrZoneResult(name=name, image_path=str(zone_path), text=text, rect=rect)

    return zones


def _bet_marker_visible(crop: Image.Image) -> bool:
    """Detect either an orange chip or the yellow amount label."""
    pixels = list(crop.convert("RGB").getdata())
    if not pixels:
        return False
    orange = sum(
        1
        for red, green, blue in pixels
        if red > 130 and 45 < green < 190 and blue < 120 and red > green * 1.25
    )
    yellow = sum(
        1
        for red, green, blue in pixels
        if red > 150 and green > 110 and blue < 120
        and red > blue * 1.45 and green > blue * 1.25
    )
    muted_yellow = sum(
        1
        for red, green, blue in pixels
        if red > 70 and green > 90 and blue < 65
        and red > blue * 2.0 and green > blue * 2.4
    )
    return (
        orange / len(pixels) >= 0.025
        or yellow / len(pixels) >= 0.015
        or muted_yellow / len(pixels) >= 0.015
    )


def _zone_profile_names(profile: str) -> set[str] | None:
    if profile == "full":
        return None
    if profile == "live":
        return {
            "top_left_cards",
            "top_left_name",
            "top_left_stack",
            "top_left_bet",
            "top_left_action",
            "top_right_cards",
            "top_right_name",
            "top_right_stack",
            "top_right_bet",
            "top_right_action",
            "left_cards",
            "left_name",
            "left_stack",
            "left_bet",
            "left_action",
            "right_cards",
            "right_name",
            "right_stack",
            "right_bet",
            "right_action",
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
            "hero_bet",
            "hero_status",
            "dealer_button",
            "actions",
            "action_left",
            "action_center",
            "action_right",
        }
    if profile == "live_without_hero_cards":
        return _zone_profile_names("live") - {"hero", "hero_status"}
    if profile == "live_without_hero_and_board":
        return _zone_profile_names("live") - {
            "hero", "hero_status", "board", "board_card_1", "board_card_2",
            "board_card_3", "board_card_4", "board_card_5",
        }
    if profile == "live_without_hero_board_and_names":
        return _zone_profile_names("live_without_hero_and_board") - {
            "top_left_name", "top_right_name", "left_name", "right_name", "hero_name",
        }
    if profile in {"live_dynamic", "live_dynamic_with_board"}:
        dynamic = {
            "top_left_stack", "top_left_bet",
            "top_left_action",
            "top_right_stack", "top_right_bet", "top_right_action",
            "left_stack", "left_bet", "left_action",
            "right_stack", "right_bet", "right_action",
            "hero_stack", "hero_bet", "hero_status", "hero",
            "pot", "pot_value",
            "actions", "action_left", "action_center", "action_right",
        }
        if profile == "live_dynamic_with_board":
            dynamic.update({
                "board", "board_card_1", "board_card_2", "board_card_3",
                "board_card_4", "board_card_5",
            })
        return dynamic
    if profile in {"live_dynamic_flop", "live_dynamic_turn", "live_dynamic_river"}:
        dynamic = _zone_profile_names("live_dynamic") or set()
        indexes = {
            "live_dynamic_flop": (1, 2, 3),
            "live_dynamic_turn": (4,),
            "live_dynamic_river": (5,),
        }[profile]
        dynamic.update(f"board_card_{index}" for index in indexes)
        return dynamic
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
    definitions = [
        ("top_bar", _scaled_rect(width, height, *zones["top_bar"]), "6"),
        ("top_left_cards", _scaled_rect(width, height, *zones["top_left_cards"]), "6"),
        ("top_left_name", _scaled_rect(width, height, *zones["top_left_name"]), "7"),
        ("top_left_stack", _scaled_rect(width, height, *zones["top_left_stack"]), "7"),
        ("top_left_bet", _scaled_rect(width, height, *zones["top_left_bet"]), "7"),
        ("top_left_action", _scaled_rect(width, height, *zones["top_left_action"]), "7"),
        ("top_right_cards", _scaled_rect(width, height, *zones["top_right_cards"]), "6"),
        ("top_right_name", _scaled_rect(width, height, *zones["top_right_name"]), "7"),
        ("top_right_stack", _scaled_rect(width, height, *zones["top_right_stack"]), "7"),
        ("top_right_bet", _scaled_rect(width, height, *zones["top_right_bet"]), "7"),
        ("top_right_action", _scaled_rect(width, height, *zones["top_right_action"]), "7"),
        ("left_cards", _scaled_rect(width, height, *zones["left_cards"]), "6"),
        ("left_name", _scaled_rect(width, height, *zones["left_name"]), "7"),
        ("left_stack", _scaled_rect(width, height, *zones["left_stack"]), "7"),
        ("left_bet", _scaled_rect(width, height, *zones["left_bet"]), "7"),
        ("left_action", _scaled_rect(width, height, *zones["left_action"]), "7"),
        ("right_cards", _scaled_rect(width, height, *zones["right_cards"]), "6"),
        ("right_name", _scaled_rect(width, height, *zones["right_name"]), "7"),
        ("right_stack", _scaled_rect(width, height, *zones["right_stack"]), "7"),
        ("right_bet", _scaled_rect(width, height, *zones["right_bet"]), "7"),
        ("right_action", _scaled_rect(width, height, *zones["right_action"]), "7"),
        ("pot", _scaled_rect(width, height, *zones["pot"]), "6"),
        ("pot_value", _scaled_rect(width, height, *zones["pot_value"]), "7"),
        ("board", _scaled_rect(width, height, *zones["board"]), "6"),
        ("board_card_1", _scaled_rect(width, height, *zones.get("board_card_1_value", zones["board_card_1"])), "10"),
        ("board_card_2", _scaled_rect(width, height, *zones.get("board_card_2_value", zones["board_card_2"])), "10"),
        ("board_card_3", _scaled_rect(width, height, *zones.get("board_card_3_value", zones["board_card_3"])), "10"),
        ("board_card_4", _scaled_rect(width, height, *zones.get("board_card_4_value", zones["board_card_4"])), "10"),
        ("board_card_5", _scaled_rect(width, height, *zones.get("board_card_5_value", zones["board_card_5"])), "10"),
        ("hero", _scaled_rect(width, height, *zones["hero"]), "6"),
        ("hero_name", _scaled_rect(width, height, *zones["hero_name"]), "7"),
        ("hero_stack", _scaled_rect(width, height, *zones["hero_stack"]), "7"),
        ("hero_bet", _scaled_rect(width, height, *zones["hero_bet"]), "7"),
        ("hero_status", _scaled_rect(width, height, *zones["hero_status"]), "7"),
        ("dealer_button", _scaled_rect(width, height, *zones["dealer_button"]), "10"),
        ("actions", _scaled_rect(width, height, *zones["actions"]), "6"),
        ("action_left", _scaled_rect(width, height, *zones["action_left"]), "8"),
        ("action_center", _scaled_rect(width, height, *zones["action_center"]), "8"),
        ("action_right", _scaled_rect(width, height, *zones["action_right"]), "8"),
        ("left_opponent", _scaled_rect(width, height, *zones["left_opponent"]), "6"),
        ("right_opponent", _scaled_rect(width, height, *zones["right_opponent"]), "6"),
    ]
    if calibration.get("profile") == "3max":
        unsupported = {
            "left_cards", "left_name", "left_stack", "left_bet", "left_action", "left_opponent", "dealer_left",
            "right_cards", "right_name", "right_stack", "right_bet", "right_action", "right_opponent", "dealer_right",
        }
        definitions = [item for item in definitions if item[0] not in unsupported]
    return definitions


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


def _preprocess_villain_action(image: Image.Image) -> Image.Image:
    """Isolate yellow/orange action labels, including dimmed FOLD text."""
    rgb = image.convert("RGB")
    mask = Image.new("L", rgb.size, 255)
    mask.putdata([
        0 if r > 90 and g > 55 and r > b * 1.5 and g > b * 1.3 else 255
        for r, g, b in rgb.getdata()
    ])
    return mask.resize((mask.width * 3, mask.height * 3))


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
