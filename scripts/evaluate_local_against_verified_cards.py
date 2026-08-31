from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from poker_tracker.local_snapshot_analysis import save_local_analysis

REF = ROOT / "data" / "ocr_dataset" / "references" / "codex_verified_cards.json"
SESSION = ROOT / "sessions" / "20260412_114742"

def norm(value: object) -> str:
    return " ".join(str(value or "").lower().replace("10", "t").split())

def main() -> None:
    refs = json.loads(REF.read_text(encoding="utf-8"))["captures"]
    total = matches = 0
    by_field = {"hero_cards": [0, 0], **{f"board_card_{i}": [0, 0] for i in range(1, 6)}}
    errors = []
    for filename, truth in refs.items():
        image = SESSION / filename
        local_path = image.with_suffix(".local.json")
        if not local_path.exists():
            local_path = save_local_analysis(image)
        local = json.loads(local_path.read_text(encoding="utf-8"))["fields"]
        expected = {"hero_cards": truth["hero_cards"] or ""}
        expected.update({f"board_card_{i}": (truth["board"][i-1] if i <= len(truth["board"]) else "") for i in range(1, 6)})
        for field, exp in expected.items():
            got = local.get(field, {}).get("value", "")
            total += 1
            by_field[field][1] += 1
            if norm(got) == norm(exp):
                matches += 1
                by_field[field][0] += 1
            else:
                errors.append({"snapshot": filename, "field": field, "expected": exp, "local": got})
    result = {"snapshots": len(refs), "fields": total, "matches": matches, "accuracy": round(matches / total, 3), "by_field": {k: {"matches": v[0], "total": v[1], "accuracy": round(v[0]/v[1], 3)} for k,v in by_field.items()}, "errors": errors}
    out = ROOT / "data" / "ocr_dataset" / "local_vs_verified_cards.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
