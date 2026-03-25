from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
CALIBRATION_FILE = CONFIG_DIR / "calibration.json"


DEFAULT_CALIBRATION = {
    "zones": {
        "top_bar": [0.16, 0.00, 0.84, 0.08],
        "top_left_cards": [0.24, 0.03, 0.35, 0.13],
        "top_left_name": [0.25, 0.11, 0.41, 0.15],
        "top_left_stack": [0.26, 0.15, 0.40, 0.20],
        "top_right_cards": [0.56, 0.03, 0.67, 0.13],
        "top_right_name": [0.59, 0.11, 0.75, 0.15],
        "top_right_stack": [0.59, 0.15, 0.73, 0.20],
        "left_cards": [0.08, 0.45, 0.16, 0.58],
        "left_name": [0.05, 0.58, 0.18, 0.62],
        "left_stack": [0.05, 0.62, 0.19, 0.67],
        "right_cards": [0.68, 0.45, 0.76, 0.58],
        "right_name": [0.71, 0.58, 0.83, 0.62],
        "right_stack": [0.69, 0.62, 0.83, 0.67],
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
        "dealer_button": [0.62, 0.57, 0.68, 0.65],
        "actions": [0.50, 0.72, 0.99, 0.96],
        "action_left": [0.74, 0.80, 0.82, 0.96],
        "action_center": [0.82, 0.80, 0.90, 0.96],
        "action_right": [0.90, 0.80, 0.99, 0.96],
        "left_opponent": [0.02, 0.46, 0.26, 0.70],
        "right_opponent": [0.74, 0.44, 0.98, 0.70],
    }
}


def load_calibration() -> dict:
    if not CALIBRATION_FILE.exists():
        return DEFAULT_CALIBRATION.copy()

    try:
        data = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return DEFAULT_CALIBRATION.copy()

    zones = data.get("zones", {})
    merged = DEFAULT_CALIBRATION.copy()
    merged["zones"] = {**DEFAULT_CALIBRATION["zones"], **zones}
    return merged


def save_calibration(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CALIBRATION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
