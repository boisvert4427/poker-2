from __future__ import annotations
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ocr_dataset" / "board_reference_audit.png"

def board(capture):
    if "fields" in capture:
        value = capture["fields"].get("board", "")
        return value.split() if isinstance(value, str) else list(value or [])
    return list(capture.get("board", []) or [])

def main():
    entries = []
    for ref in sorted((ROOT / "data" / "ocr_dataset" / "references").glob("codex_batch_*.json")):
        data = json.loads(ref.read_text(encoding="utf-8"))
        batch = ref.stem.replace("codex_", "")
        for name, capture in data.get("captures", {}).items():
            cards = board(capture)
            paths = []
            for i in range(1, 6):
                p = ROOT / "data" / "ocr_dataset" / "crops" / batch / f"board_card_{i}" / name
                paths.append(p if p.exists() else None)
            entries.append((name, cards, paths))
    tw, th = 700, 150
    sheet = Image.new("RGB", (tw, len(entries) * th), "white")
    draw = ImageDraw.Draw(sheet)
    for row, (name, cards, paths) in enumerate(entries):
        y = row * th
        draw.text((5, y + 4), name.replace("snapshot_2026-04-12T", ""), fill="black")
        draw.text((5, y + 22), "JSON: " + (" ".join(cards) or "vide"), fill="blue")
        for i, p in enumerate(paths):
            if p and p.exists():
                with Image.open(p).convert("RGB") as im:
                    im.thumbnail((125, 115))
                    sheet.paste(im, (130 + i * 112, y + 4))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT)
    print(OUT)

if __name__ == "__main__":
    main()
