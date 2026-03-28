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

from poker_tracker.local_snapshot_analysis import compare_local_to_openai, save_local_analysis
from poker_tracker.session_recorder import SessionRecorder


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare le detecteur local aux annotations OpenAI sur une session.")
    parser.add_argument("--session", type=Path, help="Chemin du dossier de session.")
    parser.add_argument("--limit", type=int, default=None, help="Nombre max de snapshots a analyser.")
    args = parser.parse_args()

    recorder = SessionRecorder(ROOT / "sessions")
    session_dir = args.session if args.session else _latest_session(recorder)
    snapshots = recorder.list_snapshots(session_dir)
    if args.limit is not None:
        snapshots = snapshots[:args.limit]

    overall_matches = 0
    overall_total = 0
    compared_count = 0
    per_field = defaultdict(lambda: {"matches": 0, "total": 0})

    for snapshot in snapshots:
        image_path = Path(snapshot["image_path"])
        if not snapshot.get("image_path") or str(image_path) in {"", "."} or not image_path.exists():
            continue
        openai_path = image_path.with_suffix(".openai.json")
        if not openai_path.exists():
            continue

        local_path = save_local_analysis(image_path, metadata=snapshot.get("payload", {}))
        local_payload = json.loads(local_path.read_text(encoding="utf-8"))
        openai_payload = json.loads(openai_path.read_text(encoding="utf-8"))
        comparison = compare_local_to_openai(local_payload, openai_payload)

        comparison_path = image_path.with_suffix(".compare.json")
        comparison_path.write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")

        compared_count += 1
        overall_matches += comparison["matches"]
        overall_total += comparison["total"]
        for field, field_result in comparison["fields"].items():
            per_field[field]["total"] += 1
            if field_result["match"]:
                per_field[field]["matches"] += 1

    summary = {
        "session": str(session_dir),
        "snapshots_compared": compared_count,
        "overall_accuracy": round(overall_matches / overall_total, 3) if overall_total else 0.0,
        "per_field_accuracy": {
            field: round(stats["matches"] / stats["total"], 3) if stats["total"] else 0.0
            for field, stats in sorted(per_field.items())
        },
    }

    summary_path = session_dir / "local_vs_openai.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def _latest_session(recorder: SessionRecorder) -> Path:
    sessions = recorder.list_sessions()
    if not sessions:
        raise SystemExit("Aucune session disponible.")
    return sessions[0]


if __name__ == "__main__":
    main()
