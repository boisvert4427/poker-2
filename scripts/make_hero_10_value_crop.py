from pathlib import Path
from PIL import Image
import json, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from poker_tracker.config import load_calibration
from poker_tracker.ocr import _scaled_rect

source = ROOT / "sessions" / "20260412_114742" / "snapshot_2026-04-12T11-56-16.png"
output = ROOT / "data" / "ocr_dataset" / "hero_10_exact_value_crop.png"
zones = json.loads((ROOT / "data" / "ocr_dataset" / "hero_card_subzones.json").read_text(encoding="utf-8"))["zones"]
with Image.open(source).convert("RGB") as image:
    hero = image.crop(_scaled_rect(image.width, image.height, *load_calibration()["zones"]["hero"]))
    value = hero.crop(_scaled_rect(hero.width, hero.height, *zones["hero_card_1_value"]))
    value.resize((320, 320), Image.Resampling.NEAREST).save(output)
print(output)
