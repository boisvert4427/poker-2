from __future__ import annotations

import json
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
CALIBRATION_FILE = CONFIG_DIR / "calibration.json"
_CALIBRATION_PROFILE: ContextVar[str] = ContextVar("poker_calibration_profile", default="5max")
_LOCKED_CALIBRATION_PROFILE: str | None = None


DEFAULT_CALIBRATION = {
    "zones": {
        "top_bar": [0.16, 0.00, 0.84, 0.08],
        "top_left_cards": [0.24, 0.03, 0.35, 0.13],
        "top_left_name": [0.25, 0.11, 0.41, 0.15],
        "top_left_stack": [0.26, 0.15, 0.40, 0.20],
        "top_left_action": [0.255, 0.235, 0.375, 0.285],
        "top_right_cards": [0.56, 0.03, 0.67, 0.13],
        "top_right_name": [0.59, 0.11, 0.75, 0.15],
        "top_right_stack": [0.59, 0.15, 0.73, 0.20],
        "top_right_action": [0.555, 0.235, 0.705, 0.285],
        "left_cards": [0.08, 0.45, 0.16, 0.58],
        "left_name": [0.05, 0.58, 0.18, 0.62],
        "left_stack": [0.05, 0.62, 0.19, 0.67],
        "left_action": [0.16, 0.645, 0.26, 0.685],
        "right_cards": [0.68, 0.45, 0.76, 0.58],
        "right_name": [0.71, 0.58, 0.83, 0.62],
        "right_stack": [0.69, 0.62, 0.83, 0.67],
        "right_action": [0.68, 0.645, 0.76, 0.685],
        "pot": [0.34, 0.28, 0.66, 0.40],
        "pot_value": [0.40, 0.48, 0.56, 0.54],
        "board": [0.27, 0.16, 0.73, 0.33],
        "board_card_1": [0.32, 0.30, 0.38, 0.44],
        "board_card_2": [0.38, 0.30, 0.44, 0.44],
        "board_card_3": [0.44, 0.30, 0.50, 0.44],
        "board_card_4": [0.50, 0.30, 0.56, 0.44],
        "board_card_5": [0.56, 0.30, 0.62, 0.44],
        "hero": [0.24, 0.68, 0.76, 0.86],
        "hero_name": [0.41, 0.75, 0.57, 0.79],
        "hero_stack": [0.41, 0.79, 0.57, 0.84],
        "hero_status": [0.42, 0.84, 0.56, 0.89],
        "top_left_bet": [0.338, 0.327, 0.375, 0.357],
        "top_right_bet": [0.538, 0.327, 0.583, 0.357],
        "left_bet": [0.265, 0.565, 0.302, 0.595],
        "right_bet": [0.615, 0.565, 0.652, 0.595],
        "hero_bet": [0.440, 0.635, 0.475, 0.665],
        "dealer_button": [0.62, 0.57, 0.68, 0.65],
        # Zones candidates du bouton dealer. Elles sont testées dans l'ordre
        # des sièges et la recherche s'arrête dès qu'un bouton est trouvé.
        # Coordinates calibrated from the actual orange dealer discs in the
        # reference screenshots (1936x1048, normalized here).
        "dealer_top_left": [0.36, 0.20, 0.45, 0.35],
        "dealer_top_right": [0.62, 0.23, 0.70, 0.39],
        "dealer_left": [0.20, 0.38, 0.30, 0.55],
        "dealer_right": [0.70, 0.38, 0.80, 0.55],
        "dealer_hero": [0.36, 0.60, 0.45, 0.75],
        "actions": [0.50, 0.72, 0.99, 0.96],
        "action_left": [0.74, 0.80, 0.82, 0.96],
        "action_center": [0.82, 0.80, 0.90, 0.96],
        "action_right": [0.90, 0.80, 0.99, 0.96],
        "left_opponent": [0.02, 0.46, 0.26, 0.70],
        "right_opponent": [0.74, 0.44, 0.98, 0.70],
    }
}


THREE_MAX_ZONE_OVERRIDES = {
    "top_left_cards": [0.18, 0.16, 0.235, 0.25],
    "top_left_name": [0.165, 0.245, 0.275, 0.28],
    "top_left_stack": [0.175, 0.282, 0.26, 0.325],
    "top_left_action": [0.15, 0.315, 0.32, 0.355],
    "top_left_bet": [0.275, 0.29, 0.33, 0.385],
    "top_right_cards": [0.66, 0.16, 0.715, 0.25],
    "top_right_name": [0.64, 0.245, 0.76, 0.28],
    "top_right_stack": [0.65, 0.282, 0.755, 0.325],
    "top_right_action": [0.625, 0.315, 0.78, 0.355],
    "top_right_bet": [0.60, 0.29, 0.65, 0.385],
    "dealer_top_left": [0.27, 0.22, 0.34, 0.32],
    "dealer_top_right": [0.63, 0.35, 0.70, 0.45],
}


def lock_calibration_profile(profile: str | None) -> None:
    """Lock the live layout after Winamax history has identified the table."""
    global _LOCKED_CALIBRATION_PROFILE
    _LOCKED_CALIBRATION_PROFILE = profile if profile in {"3max", "5max"} else None


def locked_calibration_profile() -> str | None:
    return _LOCKED_CALIBRATION_PROFILE


def detect_calibration_profile(image_path: str | Path) -> str:
    """Return the history-locked layout, or estimate it until history arrives."""
    if _LOCKED_CALIBRATION_PROFILE is not None:
        return _LOCKED_CALIBRATION_PROFILE
    try:
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            def text_density(rect: tuple[float, float, float, float]) -> float:
                crop = image.crop((int(rect[0] * image.width), int(rect[1] * image.height),
                                   int(rect[2] * image.width), int(rect[3] * image.height)))
                pixels = list(crop.getdata())
                return sum(max(p) > 170 and max(p) - min(p) < 55 for p in pixels) / max(1, len(pixels))
            three = text_density((0.16, 0.235, 0.28, 0.285)) + text_density((0.63, 0.235, 0.77, 0.285))
            five = text_density((0.255, 0.175, 0.365, 0.21)) + text_density((0.58, 0.175, 0.75, 0.21))
            return "3max" if three > max(0.035, five * 1.20) else "5max"
    except (OSError, ValueError):
        return "5max"


@contextmanager
def calibration_profile(profile: str):
    token = _CALIBRATION_PROFILE.set(profile if profile in {"3max", "5max"} else "5max")
    try:
        yield
    finally:
        _CALIBRATION_PROFILE.reset(token)


def load_calibration(profile: str | None = None) -> dict:
    selected = profile or _CALIBRATION_PROFILE.get()
    if not CALIBRATION_FILE.exists():
        data = DEFAULT_CALIBRATION.copy()
        data["zones"] = dict(DEFAULT_CALIBRATION["zones"])
        if selected == "3max":
            data["zones"].update(THREE_MAX_ZONE_OVERRIDES)
        data["profile"] = selected
        return data

    try:
        data = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = DEFAULT_CALIBRATION.copy()
        data["zones"] = dict(DEFAULT_CALIBRATION["zones"])
        if selected == "3max":
            data["zones"].update(THREE_MAX_ZONE_OVERRIDES)
        data["profile"] = selected
        return data

    zones = data.get("zones", {})
    merged = DEFAULT_CALIBRATION.copy()
    merged["zones"] = {**DEFAULT_CALIBRATION["zones"], **zones}
    if selected == "3max":
        merged["zones"].update(THREE_MAX_ZONE_OVERRIDES)
    merged["profile"] = selected
    return merged


def save_calibration(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CALIBRATION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
