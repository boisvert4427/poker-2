"""Independent frame replay; historical truth is used only for scoring."""
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from poker_tracker.live_state import build_live_snapshot
from poker_tracker.ocr import run_local_ocr_on_image_with_profile


def main():
    root = Path(sys.argv[1]).resolve()
    output = Path("data/session_audits") / (root.name + "_retry_replay")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    files = sorted(root.glob("*.live.json"))
    for index, path in enumerate(files, 1):
        saved = output / path.name
        if saved.exists():
            rows.append(json.loads(saved.read_text(encoding="utf-8")))
            print(f"{index}/{len(files)} resumed", flush=True)
            continue
        old = json.loads(path.read_text(encoding="utf-8"))
        image = path.with_name(path.name.replace(".live.json", ".png"))
        started = time.perf_counter()
        ocr = run_local_ocr_on_image_with_profile(image, profile="live")
        # No future history, cached cards, or stored OCR supplied to recognition.
        snapshot = build_live_snapshot(None, None, ocr)
        row = {"file": path.name, "seconds": time.perf_counter() - started,
               "old": old["live_snapshot"], "new": asdict(snapshot),
               "truth": old.get("hand_link", {})}
        rows.append(row)
        (output / path.name).write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        before = row["old"]["recommendation"]["action"]
        after = snapshot.recommendation.action
        print(f"{index}/{len(files)} {before}->{after} {row['seconds']:.2f}s", flush=True)
    summary = {"mode": "independent frames, no live memory; timings are full OCR",
               "count": len(rows),
               "before": dict(Counter(r["old"]["recommendation"]["action"] for r in rows)),
               "after": dict(Counter(r["new"]["recommendation"]["action"] for r in rows)),
               "wait_resolved": sum(r["old"]["recommendation"]["action"] == "ATTENDRE" and r["new"]["recommendation"]["action"] != "ATTENDRE" for r in rows),
               "new_waits": sum(r["old"]["recommendation"]["action"] != "ATTENDRE" and r["new"]["recommendation"]["action"] == "ATTENDRE" for r in rows),
               "issues": dict(Counter(x for r in rows for x in r["new"]["recommendation"].get("data_quality_issues", []))),
               "average_seconds": sum(r["seconds"] for r in rows)/len(rows)}
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
