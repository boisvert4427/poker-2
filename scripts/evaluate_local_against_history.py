from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from poker_tracker.history_truth import truth_from_snapshot_metadata
from poker_tracker.local_snapshot_analysis import save_local_analysis
from poker_tracker.session_recorder import SessionRecorder


FIELDS = [
    "top_left_name",
    "top_left_stack",
    "top_right_name",
    "top_right_stack",
    "right_name",
    "right_stack",
    "hero_name",
    "hero_stack",
    "pot_value",
    "dealer_button",
    "board_card_1",
    "board_card_2",
    "board_card_3",
    "board_card_4",
    "board_card_5",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare le detecteur local au hand history sur une session.")
    parser.add_argument("--session", type=Path, help="Chemin du dossier de session.")
    args = parser.parse_args()

    recorder = SessionRecorder(ROOT / "sessions")
    session_dir = args.session if args.session else _latest_session(recorder)
    snapshots = recorder.list_snapshots(session_dir)

    overall_matches = 0
    overall_total = 0
    comparable_snapshots = 0
    per_field = defaultdict(lambda: {"matches": 0, "total": 0})

    for snapshot in snapshots:
        payload = snapshot.get("payload", {})
        truth = truth_from_snapshot_metadata(payload)
        if truth is None:
            continue
        comparable_snapshots += 1

        image_path = Path(snapshot["image_path"])
        local_path = save_local_analysis(image_path, metadata=payload)
        local_payload = json.loads(local_path.read_text(encoding="utf-8"))

        truth_map = {
            "top_left_name": truth.positions.get("top_left", {}).get("player", ""),
            "top_left_stack": _stack_to_bb(truth.positions.get("top_left", {}).get("stack", ""), truth.big_blind),
            "top_right_name": truth.positions.get("top_right", {}).get("player", ""),
            "top_right_stack": _stack_to_bb(truth.positions.get("top_right", {}).get("stack", ""), truth.big_blind),
            "right_name": truth.positions.get("right", {}).get("player", ""),
            "right_stack": _stack_to_bb(truth.positions.get("right", {}).get("stack", ""), truth.big_blind),
            "hero_name": truth.hero_name,
            "hero_stack": truth.hero_stack_bb,
            "pot_value": truth.pot_value_bb,
            "dealer_button": truth.dealer_owner,
            "board_card_1": truth.board_cards[0],
            "board_card_2": truth.board_cards[1],
            "board_card_3": truth.board_cards[2],
            "board_card_4": truth.board_cards[3],
            "board_card_5": truth.board_cards[4],
        }
        comparison = {"fields": {}, "matches": 0, "total": 0}
        for field in FIELDS:
            local_value = _norm(local_payload["fields"][field]["value"])
            truth_value = _norm(truth_map[field])
            matched = local_value == truth_value
            comparison["fields"][field] = {"local": local_value, "history": truth_value, "match": matched}
            comparison["total"] += 1
            if matched:
                comparison["matches"] += 1
                per_field[field]["matches"] += 1
            per_field[field]["total"] += 1

        comparison["accuracy"] = round(comparison["matches"] / comparison["total"], 3) if comparison["total"] else 0.0
        comparison_path = image_path.with_suffix(".history_compare.json")
        comparison_path.write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")

        overall_matches += comparison["matches"]
        overall_total += comparison["total"]

    summary = {
        "session": str(session_dir),
        "snapshots_total": len(snapshots),
        "snapshots_compared": comparable_snapshots,
        "overall_accuracy": round(overall_matches / overall_total, 3) if overall_total else 0.0,
        "per_field_accuracy": {
            field: round(stats["matches"] / stats["total"], 3) if stats["total"] else 0.0
            for field, stats in sorted(per_field.items())
        },
    }
    summary_path = session_dir / "local_vs_history.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def _latest_session(recorder: SessionRecorder) -> Path:
    sessions = recorder.list_sessions()
    if not sessions:
        raise SystemExit("Aucune session disponible.")
    return sessions[0]


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _stack_to_bb(stack: str, big_blind: float) -> str:
    if not stack or big_blind <= 0:
        return ""
    try:
        value = float(stack) / big_blind
    except ValueError:
        return ""
    rounded = round(value, 1)
    if rounded.is_integer():
        text = str(int(rounded))
    else:
        text = f"{rounded:.1f}".replace(".", ",")
    return f"{text} bb"


if __name__ == "__main__":
    main()
