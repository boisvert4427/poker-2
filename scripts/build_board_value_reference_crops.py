from __future__ import annotations
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "ocr_dataset" / "references" / "codex_verified_cards.json"
OUT = ROOT / "data" / "ocr_dataset" / "templates" / "board_values"
ZONE = (0.02, 0.05, 0.40, 0.27)

def main():
    refs = json.loads(REF.read_text(encoding="utf-8"))["captures"]
    count = 0
    for name, item in refs.items():
        board = item.get("board", [])
        batch = "batch_01" if name < "snapshot_2026-04-12T11-50-36.png" else "batch_02" if name < "snapshot_2026-04-12T11-53-11.png" else "batch_03"
        for index, card in enumerate(board, start=1):
            source = ROOT / "data" / "ocr_dataset" / "crops" / batch / f"board_card_{index}" / name
            if not source.exists():
                continue
            with Image.open(source).convert("RGB") as image:
                crop = image.crop(tuple(int(v * size) for v, size in zip(ZONE, (image.width, image.height, image.width, image.height))))
                rank = card[:-1].upper().replace("T", "10")
                target = OUT / rank / f"{name[:-4]}_card{index}_{card}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                crop.save(target)
                count += 1
    print(f"TEMPLATES={count}")
    print(OUT)

if __name__ == "__main__":
    main()
