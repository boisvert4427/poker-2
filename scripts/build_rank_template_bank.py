from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "sessions" / "20260412_114742"
REFERENCE_DIR = ROOT / "data" / "ocr_dataset" / "references"
OUTPUT = ROOT / "data" / "ocr_dataset" / "templates" / "ranks"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, str]] = []
    subzones = json.loads((ROOT / "data" / "ocr_dataset" / "board_card_subzones.json").read_text(encoding="utf-8"))
    value_zone = tuple(subzones["zones"]["value"])

    for reference_path in sorted(REFERENCE_DIR.glob("codex_batch_*.json")):
        batch_number = reference_path.stem.rsplit("_", 1)[-1]
        batch = f"batch_{batch_number}"
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        for filename, capture in reference["captures"].items():
            board = capture.get("board")
            if board is None:
                board = capture.get("fields", {}).get("board", "")
            cards = board if isinstance(board, list) else (board.split() if board else [])
            for index, card in enumerate(cards, start=1):
                rank = card[:-1].upper()
                if rank == "T":
                    rank = "10"
                source = ROOT / "data" / "ocr_dataset" / "crops" / batch / f"board_card_{index}" / filename
                if not source.exists():
                    continue
                with Image.open(source).convert("RGB") as image:
                    left, top, right, bottom = (
                        int(value * size)
                        for value, size in zip(value_zone, (image.width, image.height, image.width, image.height))
                    )
                    crop = image.crop((left, top, right, bottom))
                    target_dir = OUTPUT / rank
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / f"{batch}_{filename}"
                    crop.save(target)
                manifest.append({"rank": rank, "card": card, "source": str(source.relative_to(ROOT)), "template": str(target.relative_to(ROOT))})

    manifest_path = OUTPUT.parent / "rank_template_manifest.json"
    manifest_path.write_text(json.dumps({"version": 1, "templates": manifest}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"TEMPLATES={len(manifest)}")
    print(f"RANKS={','.join(sorted({item['rank'] for item in manifest}, key=lambda value: '23456789TJQKA'.index('T' if value == '10' else value)))}")
    print(f"MANIFEST={manifest_path}")


if __name__ == "__main__":
    main()
