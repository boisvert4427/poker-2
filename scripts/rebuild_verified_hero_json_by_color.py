from __future__ import annotations
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "ocr_dataset" / "references" / "codex_verified_cards.json"
OUT = ROOT / "data" / "ocr_dataset" / "references" / "codex_verified_cards_v2.json"

def suit_from_rank_crop(path: Path) -> str:
    image = Image.open(path).convert("RGB")
    # Exclure la bordure verte et les pixels de fond : seule la forme du rang
    # au centre du crop sert à déterminer sa couleur.
    w, h = image.size
    pixels = list(image.crop((int(w * .12), int(h * .08), int(w * .88), int(h * .82))).getdata())
    colored = [(r, g, b) for r, g, b in pixels if max(r, g, b) - min(r, g, b) > 45 and max(r, g, b) < 180]
    if not colored:
        return "s"
    red = sum(1 for r, g, b in colored if r > g * 1.25 and r > b * 1.25)
    blue = sum(1 for r, g, b in colored if b > r * 1.15 and b > g * 1.05)
    green = sum(1 for r, g, b in colored if g > r * 1.12 and g > b * 1.02)
    if red >= blue and red >= green and red > 2:
        return "h"
    if blue >= green and blue > 2:
        return "d"
    if green > 2:
        return "c"
    return "s"

def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    for name, item in data["captures"].items():
        cards = (item.get("hero_cards") or "").split()[:2]
        batch = "batch_01" if name < "snapshot_2026-04-12T11-50-36.png" else "batch_02" if name < "snapshot_2026-04-12T11-53-11.png" else "batch_03"
        corrected = []
        for index, card in enumerate(cards, start=1):
            rank = card[:-1]
            path = ROOT / "data" / "ocr_dataset" / "references" / "hero_value_crops" / f"card_{index}" / rank.upper().replace("T", "10") / f"{name[:-4]}_{card}.png"
            if path.exists():
                corrected.append(f"{rank}{suit_from_rank_crop(path)}")
            else:
                corrected.append(card)
        item["hero_cards"] = " ".join(corrected) or None
        item["hero_cards_visible"] = bool(corrected)
        item["source"] = "visual_check_plus_rank_color"
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(OUT)

if __name__ == "__main__":
    main()
