from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from poker_tracker.config import load_calibration
from poker_tracker.ocr import _scaled_rect


SESSION = ROOT / "sessions" / "20260412_114742"
DEFAULT_REFERENCES = ROOT / "data" / "ocr_dataset" / "references" / "codex_batch_01.json"
DEFAULT_OUTPUT = ROOT / "data" / "ocr_dataset" / "crops" / "batch_01"


def normalize_capture(capture: dict) -> dict:
    """Accept both the nested batch-1 schema and the flat batch-2 schema."""
    if "players" in capture:
        return capture

    fields = capture.get("fields", {})
    players = {}
    for seat in ("top_left", "top_right", "left", "right", "hero"):
        visible = fields.get(f"{seat}_cards_visible", "")
        players[seat] = {
            "name": fields.get(f"{seat}_name", ""),
            "stack": fields.get(f"{seat}_stack", ""),
            "cards": fields.get("hero_cards", "") if seat == "hero" else "",
            "cards_visible": visible in ("visible", "true", True),
            "bet": fields.get("bets", {}).get(seat, ""),
            "action": fields.get("action", "") if seat == "hero" else "",
            "present": bool(fields.get(f"{seat}_name", "")),
        }
    board = fields.get("board", "")
    return {
        "players": players,
        "board": board.split() if isinstance(board, str) and board else list(board or []),
        "pot": fields.get("pot", ""),
        "pot_total": fields.get("pot_value", ""),
        "dealer": fields.get("dealer_button", ""),
    }


def add_row(rows: list[dict], image: Image.Image, source: Path, output: Path, field: str, zone_name: str, label: object) -> None:
    ratios = load_calibration().get("zones", {}).get(zone_name)
    if not ratios:
        return
    crop_dir = output / field
    crop_dir.mkdir(parents=True, exist_ok=True)
    crop_path = crop_dir / source.name
    image.crop(_scaled_rect(image.width, image.height, *ratios)).save(crop_path)
    rows.append({
        "field": field,
        "zone": zone_name,
        "image": str(crop_path.relative_to(ROOT)),
        "source": str(source.relative_to(ROOT)),
        "label": label,
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--labels", type=Path)
    args = parser.parse_args()
    reference_path = args.reference if args.reference.is_absolute() else ROOT / args.reference
    output = args.output if args.output.is_absolute() else ROOT / args.output
    labels = args.labels or output.parent / f"clean_crop_labels_{output.name}.json"
    if not labels.is_absolute():
        labels = ROOT / labels

    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for filename, capture in reference["captures"].items():
        source = SESSION / filename
        with Image.open(source).convert("RGB") as image:
            capture = normalize_capture(capture)
            players = capture["players"]
            for seat, player in players.items():
                for value, zone in (("cards", f"{seat}_cards"), ("name", f"{seat}_name"), ("stack", f"{seat}_stack")):
                    label = player.get(value)
                    if value == "cards":
                        label = "visible" if player.get("cards_visible") else "hidden"
                    add_row(rows, image, source, output, f"{seat}_{value}", zone, label)
            for index, card in enumerate(capture.get("board", []), start=1):
                add_row(rows, image, source, output, f"board_card_{index}", f"board_card_{index}", card)
            for index in range(len(capture.get("board", [])) + 1, 6):
                add_row(rows, image, source, output, f"board_card_{index}", f"board_card_{index}", "")
            add_row(rows, image, source, output, "hero_cards", "hero", players["hero"].get("cards", ""))
            add_row(rows, image, source, output, "pot", "pot", capture.get("pot", ""))
            add_row(rows, image, source, output, "pot_total", "pot_value", capture.get("pot_total", ""))
            add_row(rows, image, source, output, "dealer", "dealer_button", capture.get("dealer", ""))
            for action_zone in ("action_left", "action_center", "action_right"):
                add_row(rows, image, source, output, action_zone, action_zone, "")
            for seat in ("left", "right"):
                player = players[seat]
                add_row(rows, image, source, output, f"{seat}_opponent", f"{seat}_opponent", {
                    "name": player.get("name", ""),
                    "stack": player.get("stack", ""),
                    "bet": player.get("bet", ""),
                    "action": player.get("action", ""),
                })

    labels.write_text(json.dumps({"version": 2, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"CAPTURES={len(reference['captures'])}")
    print(f"CROPS={len(rows)}")
    print("BET_ZONES=not_calibrated")
    print(f"LABELS={labels}")


if __name__ == "__main__":
    main()
