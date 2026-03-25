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
from poker_tracker.pure_live_detector import LiveSeatMemory, analyze_live_image
from poker_tracker.session_recorder import SessionRecorder


FIELDS = [
    "top_left_name",
    "top_right_name",
    "right_name",
    "hero_name",
    "pot_value",
    "dealer_button",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare le detecteur live pur au hand history sur une session.")
    parser.add_argument("--session", type=Path, help="Chemin du dossier de session.")
    args = parser.parse_args()

    recorder = SessionRecorder(ROOT / "sessions")
    session_dir = args.session if args.session else _latest_session(recorder)
    snapshots = recorder.list_snapshots(session_dir)

    overall_matches = 0
    overall_total = 0
    comparable_snapshots = 0
    per_field = defaultdict(lambda: {"matches": 0, "total": 0})
    memories: dict[str, LiveSeatMemory] = {}

    for snapshot in snapshots:
        payload = snapshot.get("payload", {})
        truth = truth_from_snapshot_metadata(payload)
        if truth is None:
            continue
        comparable_snapshots += 1
        table_name = truth.table_name or ""
        memory = memories.setdefault(table_name, LiveSeatMemory())

        image_path = Path(snapshot["image_path"])
        live_payload = analyze_live_image(image_path, metadata=payload)
        hand_id = ((payload.get("live_snapshot") or {}).get("hand_id") or "")
        live_payload["fields"] = memory.refine(live_payload["fields"], hand_id=hand_id)
        live_path = image_path.with_suffix(".live.json")
        live_path.write_text(json.dumps(live_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        truth_map = {
            "top_left_name": truth.positions.get("top_left", {}).get("player", ""),
            "top_right_name": truth.positions.get("top_right", {}).get("player", ""),
            "right_name": truth.positions.get("right", {}).get("player", ""),
            "hero_name": truth.hero_name,
            "pot_value": truth.pot_value_bb,
            "dealer_button": truth.dealer_owner,
        }
        comparison = {"fields": {}, "matches": 0, "total": 0}
        for field in FIELDS:
            local_value = _norm(live_payload["fields"][field]["value"])
            truth_value = _norm(truth_map[field])
            matched = local_value == truth_value
            comparison["fields"][field] = {"local": local_value, "history": truth_value, "match": matched}
            comparison["total"] += 1
            if matched:
                comparison["matches"] += 1
                per_field[field]["matches"] += 1
            per_field[field]["total"] += 1

        comparison["accuracy"] = round(comparison["matches"] / comparison["total"], 3) if comparison["total"] else 0.0
        comparison_path = image_path.with_suffix(".pure_live_compare.json")
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
    summary_path = session_dir / "pure_live_vs_history.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def _latest_session(recorder: SessionRecorder) -> Path:
    sessions = recorder.list_sessions()
    if not sessions:
        raise SystemExit("Aucune session disponible.")
    return sessions[0]


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


if __name__ == "__main__":
    main()
