from pathlib import Path
from PIL import Image, ImageDraw
import json, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from poker_tracker.config import load_calibration
from poker_tracker.ocr import _scaled_rect

ROOT = Path(__file__).resolve().parents[1]
name = "snapshot_2026-04-12T11-48-15.png"
source = ROOT / "sessions" / "20260412_114742" / name
reference = ROOT / "data" / "ocr_dataset" / "references" / "hero_value_crops" / "card_2" / "4" / "snapshot_2026-04-12T11-48-15_4s.png"
output = ROOT / "data" / "ocr_dataset" / "hero_runtime_vs_reference_4.png"
zones = json.loads((ROOT / "data" / "ocr_dataset" / "hero_card_subzones.json").read_text(encoding="utf-8"))["zones"]

with Image.open(source).convert("RGB") as image:
    hero = image.crop(_scaled_rect(image.width, image.height, *load_calibration()["zones"]["hero"]))
    runtime = hero.crop(_scaled_rect(hero.width, hero.height, *zones["hero_card_2_value"]))
with Image.open(reference).convert("RGB") as ref:
    ref = ref.copy()

size = (220, 260)
sheet = Image.new("RGB", (size[0] * 2, size[1] + 35), "white")
runtime = runtime.resize(size, Image.Resampling.NEAREST)
ref = ref.resize(size, Image.Resampling.NEAREST)
sheet.paste(runtime, (0, 0))
sheet.paste(ref, (size[0], 0))
draw = ImageDraw.Draw(sheet)
draw.text((5, size[1] + 5), "crop direct", fill="black")
draw.text((size[0] + 5, size[1] + 5), "référence 4s", fill="black")
sheet.save(output)
print(output)
