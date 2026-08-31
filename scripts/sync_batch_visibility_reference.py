from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from poker_tracker.local_snapshot_analysis import _detect_cards_visible


REFERENCE = ROOT / "data" / "ocr_dataset" / "references" / "codex_batch_01.json"
CROPS = ROOT / "data" / "ocr_dataset" / "crops" / "batch_01"


def main() -> None:
    payload = json.loads(REFERENCE.read_text(encoding="utf-8"))
    for filename, capture in payload["captures"].items():
        for seat, player in capture["players"].items():
            crop = CROPS / f"{seat}_cards" / filename
            detected = _detect_cards_visible(str(crop))
            player["cards_visible"] = detected == "visible"
    REFERENCE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"UPDATED={len(payload['captures'])} captures")


if __name__ == "__main__":
    main()
