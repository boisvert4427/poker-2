from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
CALIBRATION_FILE = CONFIG_DIR / "calibration.json"


DEFAULT_CALIBRATION = {
    "zones": {
        "top_bar": [0.16, 0.00, 0.84, 0.08],
        "pot": [0.34, 0.28, 0.66, 0.40],
        "board": [0.27, 0.16, 0.73, 0.33],
        "hero": [0.24, 0.68, 0.76, 0.86],
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
