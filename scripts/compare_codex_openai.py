from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "sessions" / "20260412_114742"


def norm(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace(",", ".").split())


def compare_field(field: str, codex_fields: dict[str, str], openai_fields: dict) -> tuple[str, str]:
    if field.startswith("board_card_"):
        index = int(field.rsplit("_", 1)[1]) - 1
        codex_cards = codex_fields.get("board", "").split()
        codex = codex_cards[index] if index < len(codex_cards) else ""
    else:
        codex = codex_fields.get(field, "")
    openai = (openai_fields.get(field) or {}).get("value", "")
    return norm(codex), norm(openai)


def main() -> None:
    annotations = json.loads((SESSION / "codex_annotations.json").read_text(encoding="utf-8"))
    fields_to_compare = [
        "top_left_cards_visible", "top_right_cards_visible", "left_cards_visible", "right_cards_visible",
        "top_left_name", "top_right_name", "left_name", "right_name", "hero_name",
        "top_left_stack", "top_right_stack", "left_stack", "right_stack", "hero_stack",
        "pot_value", "dealer_button", "board_card_1", "board_card_2", "board_card_3",
        "board_card_4", "board_card_5",
    ]
    total = matches = 0
    disagreements: list[dict[str, str]] = []
    for filename, payload in annotations["captures"].items():
        openai_path = SESSION / filename.replace(".png", ".openai.json")
        openai = json.loads(openai_path.read_text(encoding="utf-8"))
        codex_fields = payload["fields"]
        openai_fields = openai.get("fields", {})
        # OpenAI reports the player name for dealer_button; Codex reports the seat.
        dealer_name_to_seat = {
            norm(codex_fields.get("top_left_name")): "top_left",
            norm(codex_fields.get("top_right_name")): "top_right",
            norm(codex_fields.get("left_name")): "left",
            norm(codex_fields.get("right_name")): "right",
            norm(codex_fields.get("hero_name")): "hero",
        }
        for field in fields_to_compare:
            codex, openai_value = compare_field(field, codex_fields, openai_fields)
            if field == "dealer_button":
                openai_value = dealer_name_to_seat.get(openai_value, openai_value)
            # Empty/unknown values are not scored as disagreements.
            if not codex or codex in {"?", "q?"} or not openai_value:
                continue
            total += 1
            if codex == openai_value:
                matches += 1
            else:
                disagreements.append({"capture": filename, "field": field, "codex": codex, "openai": openai_value})

    result = {
        "captures_compared": len(annotations["captures"]),
        "fields_compared": total,
        "matches": matches,
        "agreement": round(matches / total, 3) if total else 0.0,
        "disagreements": disagreements,
    }
    output = SESSION / "codex_vs_openai.summary.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
