from __future__ import annotations
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "ocr_dataset" / "references" / "codex_verified_cards_v2.json"
ZONES = json.loads((ROOT / "data" / "ocr_dataset" / "hero_card_subzones.json").read_text(encoding="utf-8"))["zones"]
OUT = ROOT / "data" / "ocr_dataset" / "templates" / "hero_value_reference_bank"

def main():
    refs = json.loads(REF.read_text(encoding="utf-8"))["captures"]
    count = 0
    for name, item in refs.items():
        cards = (item.get("hero_cards") or "").split()[:2]
        batch = "batch_01" if name < "snapshot_2026-04-12T11-50-36.png" else "batch_02" if name < "snapshot_2026-04-12T11-53-11.png" else "batch_03"
        source = ROOT / "data" / "ocr_dataset" / "crops" / batch / "hero_cards" / name
        if not source.exists():
            continue
        with Image.open(source).convert("RGB") as image:
            for index, card in enumerate(cards, start=1):
                zone = ZONES[f"hero_card_{index}_value"]
                box = tuple(int(v * size) for v, size in zip(zone, (image.width, image.height, image.width, image.height)))
                rank = card[:-1].upper().replace("T", "10")
                target = OUT / f"card_{index}" / rank / f"{name[:-4]}_{card}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                image.crop(box).save(target)
                count += 1
    print(f"CROPS={count}")
    print(OUT)

if __name__ == "__main__":
    main()
