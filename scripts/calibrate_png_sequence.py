from pathlib import Path

from PIL import Image, ImageDraw

from poker_tracker.config import load_calibration
from poker_tracker.ocr import _scaled_rect


ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "sessions" / "20260902_223643"
OUTPUT = SESSION / "calibration_png_only_batch20"
FIELDS = [
    "hero_card_1_value", "hero_card_2_value", "board_card_1", "board_card_2",
    "board_card_3", "board_card_4", "board_card_5", "pot", "pot_value",
    "hero_name", "hero_stack", "top_left_name", "top_left_stack",
    "top_right_name", "top_right_stack", "left_name", "left_stack",
    "right_name", "right_stack", "top_left_bet", "top_right_bet",
    "left_bet", "right_bet", "dealer_button",
]


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    zones = load_calibration()["zones"]
    files = sorted(path for path in SESSION.glob("snapshot_*.png") if path.parent == SESSION)[10:20]
    for index, path in enumerate(files, 1):
        image = Image.open(path).convert("RGB")
        draw = ImageDraw.Draw(image)
        for name in FIELDS:
            if name not in zones:
                continue
            rect = _scaled_rect(image.width, image.height, *zones[name])
            draw.rectangle(rect, outline="red", width=2)
            draw.text((rect[0], rect[1]), name, fill="yellow")
        image.save(OUTPUT / f"{index:03d}_{path.name}")
    print(f"PNG bruts: {len(files)}")
    print(f"Images controle: {len(list(OUTPUT.glob('*.png')))}")
    print(f"Dossier: {OUTPUT}")


if __name__ == "__main__":
    main()
