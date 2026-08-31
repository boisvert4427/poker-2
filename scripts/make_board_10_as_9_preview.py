from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "data" / "ocr_dataset" / "crops" / "batch_01" / "board_card_1" / "snapshot_2026-04-12T11-49-00.png"
output = ROOT / "data" / "ocr_dataset" / "board_10_read_as_9.png"

with Image.open(source).convert("RGB") as image:
    width, height = image.size
    box = (round(width * 0.02), round(height * 0.05), round(width * 0.40), round(height * 0.27))
    draw = ImageDraw.Draw(image)
    draw.rectangle(box, outline=(255, 0, 0), width=3)
    image = image.crop((0, 0, min(width, round(width * 0.65)), min(height, round(height * 0.70))))
    image = image.resize((image.width * 6, image.height * 6), Image.Resampling.NEAREST)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
print(output)
