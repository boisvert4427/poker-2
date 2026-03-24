from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytesseract


# Ratios: (x, y, width, height) relative to the full image size.
# This keeps the system resolution-independent and easy to recalibrate.
ZONES_RATIO = {
    "table_header": (0.07, 0.00, 0.45, 0.05),
    "top_left_name": (0.25, 0.11, 0.16, 0.04),
    "top_left_stack": (0.26, 0.15, 0.14, 0.05),
    "top_right_name": (0.59, 0.11, 0.16, 0.04),
    "top_right_stack": (0.59, 0.15, 0.14, 0.05),
    "right_name": (0.71, 0.58, 0.12, 0.04),
    "right_stack": (0.69, 0.62, 0.14, 0.05),
    "bottom_name": (0.43, 0.74, 0.14, 0.04),
    "bottom_stack": (0.43, 0.78, 0.14, 0.05),
    "bottom_status": (0.44, 0.83, 0.12, 0.04),
    "board": (0.31, 0.34, 0.25, 0.16),
    "pot": (0.40, 0.48, 0.16, 0.06),
    "center_bottom_msg": (0.39, 0.88, 0.22, 0.04),
    "center_bottom_btn": (0.42, 0.92, 0.12, 0.05),
    # Useful additions that still follow the same ratio-only rule.
    "dealer_button": (0.54, 0.69, 0.05, 0.05),
    "hero_cards": (0.39, 0.67, 0.22, 0.08),
}


@dataclass(frozen=True)
class ZoneSpec:
    ratio: tuple[float, float, float, float]
    zone_type: str
    psm: int = 7
    whitelist: str | None = None
    preprocess: str = "text"
    color: tuple[int, int, int] = (0, 255, 0)


ZONE_SPECS: dict[str, ZoneSpec] = {
    "table_header": ZoneSpec(ZONES_RATIO["table_header"], "ocr", psm=7, preprocess="header"),
    "top_left_name": ZoneSpec(ZONES_RATIO["top_left_name"], "ocr", psm=7, preprocess="name"),
    "top_left_stack": ZoneSpec(
        ZONES_RATIO["top_left_stack"],
        "ocr",
        psm=7,
        whitelist="0123456789.,Bb€$",
        preprocess="stack",
        color=(255, 255, 0),
    ),
    "top_right_name": ZoneSpec(ZONES_RATIO["top_right_name"], "ocr", psm=7, preprocess="name"),
    "top_right_stack": ZoneSpec(
        ZONES_RATIO["top_right_stack"],
        "ocr",
        psm=7,
        whitelist="0123456789.,Bb€$",
        preprocess="stack",
        color=(255, 255, 0),
    ),
    "right_name": ZoneSpec(ZONES_RATIO["right_name"], "ocr", psm=7, preprocess="name"),
    "right_stack": ZoneSpec(
        ZONES_RATIO["right_stack"],
        "ocr",
        psm=7,
        whitelist="0123456789.,Bb€$",
        preprocess="stack",
        color=(255, 255, 0),
    ),
    "bottom_name": ZoneSpec(ZONES_RATIO["bottom_name"], "ocr", psm=7, preprocess="name"),
    "bottom_stack": ZoneSpec(
        ZONES_RATIO["bottom_stack"],
        "ocr",
        psm=7,
        whitelist="0123456789.,Bb€$",
        preprocess="stack",
        color=(255, 255, 0),
    ),
    "bottom_status": ZoneSpec(ZONES_RATIO["bottom_status"], "ocr", psm=7, preprocess="status", color=(255, 128, 0)),
    "board": ZoneSpec(ZONES_RATIO["board"], "non_ocr", color=(255, 0, 255)),
    "pot": ZoneSpec(
        ZONES_RATIO["pot"],
        "ocr",
        psm=7,
        whitelist="0123456789.,Bb€$:",
        preprocess="pot",
        color=(0, 255, 255),
    ),
    "center_bottom_msg": ZoneSpec(ZONES_RATIO["center_bottom_msg"], "ocr", psm=7, preprocess="status", color=(0, 128, 255)),
    "center_bottom_btn": ZoneSpec(ZONES_RATIO["center_bottom_btn"], "ocr", psm=8, preprocess="button", color=(0, 128, 255)),
    "dealer_button": ZoneSpec(ZONES_RATIO["dealer_button"], "non_ocr", color=(0, 0, 255)),
    "hero_cards": ZoneSpec(ZONES_RATIO["hero_cards"], "non_ocr", color=(128, 0, 255)),
}


def ratio_to_rect(image_shape: tuple[int, int, int] | tuple[int, int], ratio: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    height, width = image_shape[:2]
    rx, ry, rw, rh = ratio
    x = int(round(rx * width))
    y = int(round(ry * height))
    w = int(round(rw * width))
    h = int(round(rh * height))
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    w = max(1, min(w, width - x))
    h = max(1, min(h, height - y))
    return x, y, w, h


def crop_zone(image: np.ndarray, ratio: tuple[float, float, float, float]) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    x, y, w, h = ratio_to_rect(image.shape, ratio)
    return image[y : y + h, x : x + w].copy(), (x, y, w, h)


def preprocess_for_ocr(zone_image: np.ndarray, mode: str) -> np.ndarray:
    gray = cv2.cvtColor(zone_image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    if mode == "name":
        gray = cv2.equalizeHist(gray)
        return cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )

    if mode in {"stack", "pot"}:
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    if mode in {"button", "status", "header"}:
        gray = cv2.equalizeHist(gray)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    return gray


def run_ocr(zone_image: np.ndarray, spec: ZoneSpec) -> str:
    processed = preprocess_for_ocr(zone_image, spec.preprocess)
    config_parts = [f"--psm {spec.psm}", "--oem 3"]
    if spec.whitelist:
        config_parts.append(f"-c tessedit_char_whitelist={spec.whitelist}")
    text = pytesseract.image_to_string(processed, config=" ".join(config_parts))
    return normalize_text(text)


def normalize_text(text: str) -> str:
    return " ".join(part.strip() for part in text.splitlines() if part.strip())


def analyze_non_ocr_zone(zone_name: str, zone_image: np.ndarray) -> dict[str, Any]:
    hsv = cv2.cvtColor(zone_image, cv2.COLOR_BGR2HSV)
    mean_bgr = zone_image.mean(axis=(0, 1)).round(2).tolist()
    mean_hsv = hsv.mean(axis=(0, 1)).round(2).tolist()

    result: dict[str, Any] = {
        "kind": "non_ocr",
        "mean_bgr": mean_bgr,
        "mean_hsv": mean_hsv,
    }

    if zone_name == "board":
        result["note"] = "Board zone kept for card/template/color analysis, not OCR."
    elif zone_name == "dealer_button":
        result["note"] = "Dealer button zone kept for template or brightness/color detection."
    elif zone_name == "hero_cards":
        result["note"] = "Hero cards zone kept for card recognition, not OCR."
    return result


def analyze_table_image(image: np.ndarray) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for zone_name, spec in ZONE_SPECS.items():
        zone_img, rect = crop_zone(image, spec.ratio)
        zone_result: dict[str, Any] = {
            "type": spec.zone_type,
            "ratio": list(spec.ratio),
            "rect": list(rect),
        }

        if spec.zone_type == "ocr":
            zone_result["text"] = run_ocr(zone_img, spec)
        else:
            zone_result.update(analyze_non_ocr_zone(zone_name, zone_img))

        results[zone_name] = zone_result
    return results


def draw_debug_overlay(image: np.ndarray, results: dict[str, Any]) -> np.ndarray:
    output = image.copy()

    for zone_name, spec in ZONE_SPECS.items():
        x, y, w, h = results[zone_name]["rect"]
        color = spec.color
        cv2.rectangle(output, (x, y), (x + w, y + h), color, 2)

        label = zone_name
        if results[zone_name]["type"] == "ocr":
            text = results[zone_name].get("text", "")
            if text:
                label = f"{zone_name}: {text[:28]}"

        (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(output, (x, max(0, y - text_h - 10)), (x + text_w + 8, y), (20, 20, 20), -1)
        cv2.putText(output, label, (x + 4, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    return output


def load_image(image_path: Path) -> np.ndarray:
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Unable to load image: {image_path}")
    return image


def save_debug_image(output_path: Path, image: np.ndarray) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), image)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poker table OCR/debug script based on ratio-defined zones.")
    parser.add_argument("image", type=Path, help="Path to the poker table screenshot")
    parser.add_argument("--debug-output", type=Path, default=Path("debug/poker_table_debug.png"))
    parser.add_argument("--json-output", type=Path, default=Path("debug/poker_table_ocr.json"))
    parser.add_argument("--show", action="store_true", help="Display the debug overlay in an OpenCV window")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image = load_image(args.image)
    results = analyze_table_image(image)

    debug_image = draw_debug_overlay(image, results)
    save_debug_image(args.debug_output, debug_image)

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nDebug image saved to: {args.debug_output}")
    print(f"JSON output saved to: {args.json_output}")

    if args.show:
        cv2.imshow("Poker Table OCR Debug", debug_image)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
