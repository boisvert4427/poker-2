from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "sessions" / "20260412_114742"
OUT = ROOT / "data" / "ocr_dataset" / "reference_audit_overview.png"


def fields(capture: dict) -> tuple[str, str]:
    if "fields" in capture:
        f = capture["fields"]
        return str(f.get("hero_cards", "")), str(f.get("board", ""))
    hero = capture.get("players", {}).get("hero", {})
    board = capture.get("board", [])
    return str(hero.get("cards", "")), " ".join(str(x) for x in board)


def main() -> None:
    entries: list[tuple[str, str, str, Path]] = []
    for ref in sorted((ROOT / "data" / "ocr_dataset" / "references").glob("codex_batch_*.json")):
        payload = json.loads(ref.read_text(encoding="utf-8"))
        for name, capture in payload.get("captures", {}).items():
            hero, board = fields(capture)
            crop = ROOT / "data" / "ocr_dataset" / "crops" / ref.stem.replace("codex_", "") / "hero_cards" / name
            if not crop.exists():
                crop = SESSION / name
            entries.append((name, hero, board, crop))

    tile_w, tile_h = 300, 270
    cols = 3
    rows = (len(entries) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (name, hero, board, path) in enumerate(entries):
        x, y = (i % cols) * tile_w, (i // cols) * tile_h
        with Image.open(path).convert("RGB") as image:
            image.thumbnail((tile_w - 10, 220))
            sheet.paste(image, (x + 5, y + 5))
        draw.rectangle((x, y, x + tile_w - 1, y + tile_h - 1), outline="black")
        draw.text((x + 5, y + 228), name.replace("snapshot_2026-04-12T", ""), fill="black")
        draw.text((x + 5, y + 243), f"hero JSON: {hero or 'vide'}", fill="red")
        draw.text((x + 5, y + 258), f"board JSON: {board or 'vide'}", fill="blue")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
