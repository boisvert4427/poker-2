import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
base = json.loads((ROOT / "data/ocr_dataset/references/codex_verified_cards_v2.json").read_text(encoding="utf-8"))
new = json.loads((ROOT / "data/ocr_dataset/references/codex_batch_04_verified.json").read_text(encoding="utf-8"))
base["captures"].update(new["captures"])
base["source"] = "manual_visual_verification_plus_batch_04"
out = ROOT / "data/ocr_dataset/references/codex_verified_cards_v3.json"
out.write_text(json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")
print(out)
