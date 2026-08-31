from pathlib import Path
from PIL import Image, ImageDraw
import json, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from poker_tracker.config import load_calibration
from poker_tracker.ocr import _scaled_rect

source = ROOT / "sessions" / "20260412_114742" / "snapshot_2026-04-12T11-56-16.png"
output = ROOT / "data" / "ocr_dataset" / "hero_10_problem_current_zones.png"
subzones = json.loads((ROOT / "data" / "ocr_dataset" / "hero_card_subzones.json").read_text(encoding="utf-8"))["zones"]
with Image.open(source).convert("RGB") as image:
    hero = image.crop(_scaled_rect(image.width, image.height, *load_calibration()["zones"]["hero"]))
draw = ImageDraw.Draw(hero)
colors = [(255, 0, 0), (0, 90, 255)]
for index, color in enumerate(colors, start=1):
    zone = subzones[f"hero_card_{index}_value"]
    box = _scaled_rect(hero.width, hero.height, *zone)
    draw.rectangle(box, outline=color, width=3)
hero = hero.resize((hero.width * 4, hero.height * 4), Image.Resampling.NEAREST)
output.parent.mkdir(parents=True, exist_ok=True)
hero.save(output)
print(output)
