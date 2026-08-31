from __future__ import annotations

import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "sessions" / "20260412_114742"
OUTPUT = ROOT / "data" / "ocr_dataset"


def load_captures() -> dict[str, dict]:
    captures: dict[str, dict] = {}
    files = [SESSION / "codex_annotations.json", *sorted(SESSION.glob("codex_batch_*.json"))]
    for file in files:
        payload = json.loads(file.read_text(encoding="utf-8"))
        for filename, record in payload.get("captures", {}).items():
            captures.setdefault(filename, record.get("fields", {}))
    return captures


def main() -> None:
    captures = load_captures()
    if len(captures) != 63:
        raise SystemExit(f"Expected 63 unique captures, found {len(captures)}")

    names = sorted(captures)
    shuffled = names[:]
    random.Random(42).shuffle(shuffled)
    splits = {
        "train": shuffled[:45],
        "validation": shuffled[45:54],
        "test": shuffled[54:],
    }

    for split in splits:
        (OUTPUT / split).mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 1,
        "source": str(SESSION.relative_to(ROOT)),
        "seed": 42,
        "counts": {name: len(values) for name, values in splits.items()},
        "records": [
            {
                "split": split,
                "image": str((SESSION / filename).relative_to(ROOT)),
                "filename": filename,
                "fields": captures[filename],
            }
            for split, values in splits.items()
            for filename in values
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({"output": str(OUTPUT / "manifest.json"), **manifest["counts"]}, indent=2))


if __name__ == "__main__":
    main()
