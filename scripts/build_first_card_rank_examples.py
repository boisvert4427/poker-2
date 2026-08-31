from __future__ import annotations
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "ocr_dataset" / "references" / "codex_verified_cards.json"
OUT = ROOT / "data" / "ocr_dataset" / "templates" / "hero_first_card_K_examples.png"

def main():
    refs = json.loads(REF.read_text(encoding="utf-8"))["captures"]
    selected = []
    for name, value in refs.items():
        cards = (value.get("hero_cards") or "").split()
        if cards and cards[0].lower().startswith("k"):
            path = ROOT / "data" / "ocr_dataset" / "crops" / ("batch_01" if "11-4" in name else "batch_02" if "11-5" in name and name < "snapshot_2026-04-12T11-53-11.png" else "batch_03") / "hero_cards" / name
            if path.exists():
                selected.append((name, cards[0], path))
    tile_w, tile_h = 260, 250
    sheet = Image.new("RGB", (tile_w * len(selected), tile_h), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (name, label, path) in enumerate(selected):
        with Image.open(path).convert("RGB") as image:
            image.thumbnail((tile_w - 10, 210))
            # La zone de référence ne couvre que le rang de la première carte.
            zone = (0.18, 0.20, 0.32, 0.42)
            box = (round(image.width * zone[0]), round(image.height * zone[1]),
                   round(image.width * zone[2]), round(image.height * zone[3]))
            ImageDraw.Draw(image).rectangle(box, outline=(255, 0, 0), width=3)
            sheet.paste(image, (i * tile_w + 5, 5))
        draw.text((i * tile_w + 5, 220), f"{name[-12:]} : {label}", fill="black")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT)
    print(f"EXAMPLES={len(selected)}")
    print(OUT)

if __name__ == "__main__":
    main()
