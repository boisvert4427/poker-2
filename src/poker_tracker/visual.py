from __future__ import annotations

from dataclasses import dataclass

from PIL import Image
from .config import load_calibration


@dataclass(slots=True)
class ButtonVisualState:
    name: str
    rect: tuple[int, int, int, int]
    mean_brightness: float
    non_dark_ratio: float
    red_ratio: float
    green_ratio: float
    active: bool


def analyze_action_buttons(image_path: str) -> list[ButtonVisualState]:
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    zones = load_calibration().get("zones", {})
    regions = [
        ("left", _scaled_rect(width, height, *zones["action_left"])),
        ("center", _scaled_rect(width, height, *zones["action_center"])),
        ("right", _scaled_rect(width, height, *zones["action_right"])),
    ]

    results: list[ButtonVisualState] = []
    for name, rect in regions:
        results.append(_analyze_region(image, name, rect))
    return results


def _analyze_region(image: Image.Image, name: str, rect: tuple[int, int, int, int]) -> ButtonVisualState:
    x1, y1, x2, y2 = rect
    crop = image.crop(rect)
    pixels = list(crop.getdata())
    total = max(1, len(pixels))

    brightness_values = [(r + g + b) / 3 for r, g, b in pixels]
    mean_brightness = sum(brightness_values) / total
    non_dark_ratio = sum(1 for value in brightness_values if value > 45) / total
    red_ratio = sum(1 for r, g, b in pixels if r > 90 and r > g * 1.15 and r > b * 1.15) / total
    green_ratio = sum(1 for r, g, b in pixels if g > 90 and g > r * 1.10 and g > b * 1.10) / total

    active = non_dark_ratio > 0.08 or red_ratio > 0.015 or green_ratio > 0.015
    return ButtonVisualState(
        name=name,
        rect=(x1, y1, x2, y2),
        mean_brightness=mean_brightness,
        non_dark_ratio=non_dark_ratio,
        red_ratio=red_ratio,
        green_ratio=green_ratio,
        active=active,
    )


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
