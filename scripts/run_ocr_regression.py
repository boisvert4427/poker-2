from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys
import time


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from poker_tracker.local_snapshot_analysis import extract_live_table_facts
from poker_tracker.ocr import run_local_ocr_on_image_with_profile


DEFAULT_REFERENCE = ROOT / "data" / "ocr_regression" / "live_expected.json"


def normalize(value: object) -> str:
    text = str(value or "").strip().lower().replace(".", ",")
    return re.sub(r"\s+", " ", text)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Teste automatiquement l'OCR live sur des captures vérifiées."
    )
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument(
        "--max-seconds",
        type=float,
        help="Temps maximal par image (remplace la valeur du JSON).",
    )
    args = parser.parse_args()

    reference_path = args.reference.resolve()
    payload = json.loads(reference_path.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    max_seconds = args.max_seconds or float(payload.get("max_seconds_per_image", 4.0))
    if not cases:
        print(f"ERREUR: aucun cas dans {reference_path}")
        return 2

    field_scores: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "total": 0})
    total_fields = 0
    correct_fields = 0
    failed_cases = 0
    durations: list[float] = []

    print(f"Référence : {reference_path}")
    print(f"Limite : {max_seconds:.2f} s/image\n")

    for index, case in enumerate(cases, start=1):
        image_path = Path(case["image"])
        if not image_path.is_absolute():
            image_path = ROOT / image_path
        expected = case.get("expected", {})

        if not image_path.exists():
            print(f"[{index}/{len(cases)}] ECHEC {image_path.name}: image absente")
            failed_cases += 1
            continue

        started = time.perf_counter()
        snapshot = run_local_ocr_on_image_with_profile(image_path, profile="live")
        actual = extract_live_table_facts(snapshot)
        duration = time.perf_counter() - started
        durations.append(duration)

        errors: list[str] = []
        for field, expected_value in expected.items():
            actual_value = actual.get(field, "")
            matched = normalize(actual_value) == normalize(expected_value)
            field_scores[field]["total"] += 1
            total_fields += 1
            if matched:
                field_scores[field]["ok"] += 1
                correct_fields += 1
            else:
                errors.append(f"{field}: attendu={expected_value!r}, obtenu={actual_value!r}")

        if duration > max_seconds:
            errors.append(f"temps: limite={max_seconds:.2f}s, obtenu={duration:.2f}s")

        status = "OK" if not errors else "ECHEC"
        print(f"[{index}/{len(cases)}] {status} {image_path.name} — {duration:.2f}s")
        for error in errors:
            print(f"  - {error}")
        if errors:
            failed_cases += 1

    accuracy = (correct_fields / total_fields * 100.0) if total_fields else 0.0
    average = (sum(durations) / len(durations)) if durations else 0.0
    maximum = max(durations, default=0.0)
    print(f"\nPrécision : {correct_fields}/{total_fields} = {accuracy:.1f}%")
    print(f"Temps moyen : {average:.2f}s — maximum : {maximum:.2f}s")
    print("Par champ :")
    for field in sorted(field_scores):
        score = field_scores[field]
        percent = score["ok"] / score["total"] * 100.0
        print(f"  {field}: {score['ok']}/{score['total']} ({percent:.0f}%)")

    if failed_cases:
        print(f"\nRESULTAT: ECHEC ({failed_cases} capture(s) en erreur)")
        return 1
    print("\nRESULTAT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
