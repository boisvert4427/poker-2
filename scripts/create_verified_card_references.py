from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ocr_dataset" / "references" / "codex_verified_cards.json"

# Labels relus sur les crops correspondant aux snapshots.
CARDS = {
    "11-47-59": ("Jc 2s", ""),
    "11-48-15": ("4h 4s", ""),
    "11-48-31": ("4h 4s", "3c 2c 5d 7c"),
    "11-48-45": ("Kh 7c", ""),
    "11-49-00": ("", "10s 5c 5h"),
    "11-49-14": ("Kd 3s", ""),
    "11-49-34": ("Kd 3s", "2d 10s 10c"),
    "11-49-49": ("Js 7s", ""),
    "11-50-05": ("Js 7s", "4d As 2c 8d"),
    "11-50-20": ("Js 7s", "4d As 2c 8d"),
    "11-50-36": ("4s 9h", ""),
    "11-50-53": ("4s 9h", "Qc 5h 3h 7d"),
    "11-51-08": ("4h 2h", ""),
    "11-51-24": ("", "6s Ks 5h"),
    "11-51-39": ("", "6s Ks 5h Jd 10s"),
    "11-51-54": ("", ""),
    "11-52-10": ("", "6s 8h 6d Qs"),
    "11-52-24": ("As 4d", ""),
    "11-52-40": ("As 4d", ""),
    "11-52-55": ("As 4d", ""),
    "11-53-11": ("As 4d", "5s 3d Qc"),
    "11-53-26": ("8d 4s", ""),
    "11-53-41": ("", ""),
    "11-53-55": ("", "As 7d 7h"),
    "11-54-10": ("", "As 7d 7h"),
    "11-54-27": ("Ac Jc", ""),
    "11-54-44": ("Ac Jc", "6c Ah 4c Jd"),
    "11-54-59": ("", ""),
    "11-55-14": ("2c As", ""),
    "11-55-29": ("", "2d 7h Jd 5d Qs"),
}

captures = {}
for short, (hero, board) in CARDS.items():
    filename = f"snapshot_2026-04-12T{short}.png"
    captures[filename] = {
        "hero_cards": hero or None,
        "hero_cards_visible": bool(hero),
        "board": board.split() if board else [],
        "source": "visual_check_of_matching_snapshot_crop",
    }

OUT.write_text(json.dumps({"version": 1, "source": "manual_visual_verification", "captures": captures}, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"WROTE={OUT}")
print(f"CAPTURES={len(captures)}")
