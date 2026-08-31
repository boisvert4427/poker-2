from pathlib import Path
from PIL import Image, ImageDraw
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from poker_tracker.config import load_calibration
from poker_tracker.ocr import _scaled_rect

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "sessions" / "20260412_114742" / "snapshot_2026-04-12T11-48-45.png"
output = ROOT / "data" / "ocr_dataset" / "hero_two_regions_current.png"
image = Image.open(source).convert("RGB")
zones = load_calibration()["zones"]
left, top, right, bottom = _scaled_rect(image.width, image.height, *zones["hero_status"])
crop = image.crop((left, top, right, bottom))
draw = ImageDraw.Draw(crop)
width, height = crop.size
regions = [(0.00, 0.00, 0.58, 1.00), (0.38, 0.00, 0.82, 1.00)]
colors = [(255, 0, 0), (0, 80, 255)]
for region, color in zip(regions, colors):
    box = (round(width * region[0]), round(height * region[1]), round(width * region[2]), round(height * region[3]))
    draw.rectangle(box, outline=color, width=3)
    # Zone réellement utilisée pour la couleur du symbole, relative à chaque carte.
    sx1, sy1, sx2, sy2 = box
    card_w, card_h = sx2 - sx1, sy2 - sy1
    suit_box = (sx1, sy1 + round(card_h * 0.32), sx1 + round(card_w * 0.42), sy1 + round(card_h * 0.78))
    draw.rectangle(suit_box, outline=(255, 220, 0), width=2)
crop = crop.resize((crop.width * 4, crop.height * 4), Image.Resampling.NEAREST)
output.parent.mkdir(parents=True, exist_ok=True)
crop.save(output)
print(output)
