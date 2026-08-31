from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "data" / "ocr_dataset" / "crops" / "batch_01" / "hero_cards" / "snapshot_2026-04-12T11-49-00.png"
output = ROOT / "data" / "ocr_dataset" / "hero_card_1_problem_K.png"

image = Image.open(source).convert("RGB")
draw = ImageDraw.Draw(image)
width, height = image.size

# Zone actuelle de lecture de la valeur de la première carte héros.
box = (
    round(width * 0.18), round(height * 0.18),
    round(width * 0.32), round(height * 0.45),
)
draw.rectangle(box, outline=(255, 0, 0), width=3)
draw.text((box[0], max(0, box[1] - 18)), "hero_card_1_value", fill=(255, 0, 0))

# Agrandissement pour vérifier précisément ce que la zone contient.
image = image.crop((max(0, box[0] - 25), max(0, box[1] - 25),
                    min(width, box[2] + 25), min(height, box[3] + 25)))
image = image.resize((image.width * 5, image.height * 5), Image.Resampling.NEAREST)
output.parent.mkdir(parents=True, exist_ok=True)
image.save(output)
print(output)
