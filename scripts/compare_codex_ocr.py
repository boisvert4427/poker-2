from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SESSION = ROOT / "sessions" / "20260412_114742"


def norm(value: object) -> str:
    text = " ".join(str(value or "").strip().lower().replace(",", ".").split())
    text = text.replace("10", "t")
    return text


def compare(selected_files: list[Path] | None = None) -> dict:
    annotations = {"captures": {}}
    reference_files = selected_files or [SESSION / "codex_annotations.json", *sorted(SESSION.glob("codex_batch_*.json"))]
    for reference_file in reference_files:
        payload = json.loads(reference_file.read_text(encoding="utf-8"))
        annotations["captures"].update(payload.get("captures", {}))
    fields = [
        "top_left_cards_visible", "top_right_cards_visible", "left_cards_visible", "right_cards_visible",
        "top_left_name", "top_right_name", "left_name", "right_name", "hero_name",
        "top_left_stack", "top_right_stack", "left_stack", "right_stack", "hero_stack",
        "hero_cards", "pot_value", "dealer_button", "board_card_1", "board_card_2", "board_card_3",
        "board_card_4", "board_card_5",
    ]
    total = matches = 0
    disagreements: list[dict[str, str]] = []
    for filename, codex_payload in annotations["captures"].items():
        image_path = SESSION / filename
        local_path = image_path.with_suffix(".local.json")
        # Recalculer chaque image sans l'historique d'une passe précédente :
        # sinon les valeurs stabilisées peuvent provenir d'une autre capture.
        local = json.loads(local_path.read_text(encoding="utf-8"))
        local_fields = local.get("fields", {})
        codex_fields = codex_payload.get("fields", {})
        for field in fields:
            if field.startswith("board_card_"):
                index = int(field.rsplit("_", 1)[1]) - 1
                codex_board = codex_fields.get("board", "").split()
                codex_value = codex_board[index] if index < len(codex_board) else ""
            else:
                codex_value = codex_fields.get(field, "")
            local_value = (local_fields.get(field) or {}).get("value", "")
            if field == "dealer_button":
                local_value = _dealer_seat(local_value, codex_fields)
            if not codex_value or "?" in codex_value or not local_value:
                continue
            total += 1
            if norm(codex_value) == norm(local_value):
                matches += 1
            else:
                disagreements.append({
                    "capture": filename,
                    "field": field,
                    "codex": str(codex_value),
                    "ocr": str(local_value),
                })
    return {
        "captures_compared": len(annotations["captures"]),
        "fields_compared": total,
        "matches": matches,
        "accuracy": round(matches / total, 3) if total else 0.0,
        "disagreements": disagreements,
    }


def _dealer_seat(value: object, codex_fields: dict[str, str]) -> str:
    target = norm(value)
    for seat in ("top_left", "top_right", "left", "right", "hero"):
        if target == norm(codex_fields.get(f"{seat}_name", "")):
            return seat
    return str(value or "")


def main() -> None:
    selected = [SESSION / name for name in sys.argv[1:]] if len(sys.argv) > 1 else None
    result = compare(selected)
    output = SESSION / "codex_vs_ocr.summary.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
