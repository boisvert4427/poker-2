from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from poker_tracker.config import load_calibration
from poker_tracker.ocr import _scaled_rect


DATASET = ROOT / "data" / "ocr_dataset"
MANIFEST = DATASET / "manifest.json"
FIELDS = {
    "hero_cards": "hero",
    "board_card_1": "board_card_1",
    "board_card_2": "board_card_2",
    "board_card_3": "board_card_3",
    "board_card_4": "board_card_4",
    "board_card_5": "board_card_5",
    "top_left_cards_visible": "top_left_cards",
    "top_right_cards_visible": "top_right_cards",
    "left_cards_visible": "left_cards",
    "right_cards_visible": "right_cards",
    "top_left_name": "top_left_name",
    "top_right_name": "top_right_name",
    "left_name": "left_name",
    "right_name": "right_name",
    "top_left_stack": "top_left_stack",
    "top_right_stack": "top_right_stack",
    "left_stack": "left_stack",
    "right_stack": "right_stack",
    "hero_stack": "hero_stack",
    "pot_value": "pot_value",
}


def label_value(fields: dict, field: str) -> str:
    if field.startswith("board_card_"):
        cards = str(fields.get("board", "") or "").split()
        index = int(field.rsplit("_", 1)[1]) - 1
        return cards[index] if index < len(cards) else ""
    value = fields.get(field, "")
    if isinstance(value, dict):
        return str(value.get("value", "") or "")
    return str(value or "")


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    calibration = load_calibration().get("zones", {})
    labels: dict[str, list[dict[str, str]]] = {field: [] for field in FIELDS}

    for record in manifest["records"]:
        image_path = ROOT / record["image"]
        image = Image.open(image_path).convert("RGB")
        split = record["split"]
        stem = Path(record["filename"]).stem
        for field, zone_name in FIELDS.items():
            ratios = calibration.get(zone_name)
            if not ratios:
                continue
            crop_dir = DATASET / "crops" / field / split
            crop_dir.mkdir(parents=True, exist_ok=True)
            crop_path = crop_dir / f"{stem}.png"
            image.crop(_scaled_rect(image.width, image.height, *ratios)).save(crop_path)
            labels[field].append({
                "image": str(crop_path.relative_to(ROOT)),
                "label": label_value(record["fields"], field),
                "source": record["image"],
                "split": split,
            })

    (DATASET / "crop_labels.json").write_text(
        json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({field: len(rows) for field, rows in labels.items()}, indent=2))


if __name__ == "__main__":
    main()
