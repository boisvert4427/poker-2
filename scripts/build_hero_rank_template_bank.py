from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "sessions" / "20260412_114742"
REFERENCE_DIR = ROOT / "data" / "ocr_dataset" / "references"
OUTPUT = ROOT / "data" / "ocr_dataset" / "templates" / "hero_ranks"


def main() -> None:
    zones = json.loads((ROOT / "data" / "ocr_dataset" / "hero_card_subzones.json").read_text(encoding="utf-8"))["zones"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    for ref_path in sorted(REFERENCE_DIR.glob("codex_batch_0[12].json")):
        batch = f"batch_{ref_path.stem.rsplit('_', 1)[-1]}"
        reference = json.loads(ref_path.read_text(encoding="utf-8"))
        for filename, capture in reference["captures"].items():
            cards = capture.get("players", {}).get("hero", {}).get("cards", "") if "players" in capture else capture.get("fields", {}).get("hero_cards", "")
            for index, card in enumerate(cards.split()[:2], start=1):
                source = ROOT / "data" / "ocr_dataset" / "crops" / batch / "hero_cards" / filename
                if not source.exists():
                    continue
                with Image.open(source).convert("RGB") as image:
                    zone = zones[f"hero_card_{index}_value"]
                    left, top, right, bottom = (int(value * size) for value, size in zip(zone, (image.width, image.height, image.width, image.height)))
                    crop = image.crop((left, top, right, bottom))
                    rank = card[:-1].upper()
                    if rank == "T":
                        rank = "10"
                    target_dir = OUTPUT / rank
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / f"{batch}_{filename}"
                    crop.save(target)
                rows.append({"rank": rank, "card": card, "source": str(source.relative_to(ROOT)), "template": str(target.relative_to(ROOT))})
    manifest = OUTPUT.parent / "hero_rank_template_manifest.json"
    manifest.write_text(json.dumps({"version": 1, "templates": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"TEMPLATES={len(rows)}")
    print(f"RANKS={','.join(sorted({row['rank'] for row in rows}))}")
    print(f"MANIFEST={manifest}")


if __name__ == "__main__":
    main()
