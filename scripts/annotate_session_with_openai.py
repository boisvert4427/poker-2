from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from poker_tracker.openai_annotator import annotate_session_with_openai
from poker_tracker.session_recorder import SessionRecorder


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Envoie les screenshots d'une session a OpenAI, ecrit des annotations JSON et propose une calibration."
    )
    parser.add_argument("--session", type=Path, help="Chemin absolu ou relatif du dossier de session.")
    parser.add_argument("--model", default="gpt-5", help="Modele OpenAI a utiliser.")
    parser.add_argument("--limit", type=int, default=None, help="Nombre max de snapshots a traiter.")
    parser.add_argument(
        "--overwrite-annotation",
        action="store_true",
        help="Regenere les fichiers .openai.json meme s'ils existent deja.",
    )
    parser.add_argument(
        "--overwrite-review-expected",
        action="store_true",
        help="Ecrase aussi les valeurs attendues deja presentes dans les .review.json.",
    )
    parser.add_argument(
        "--apply-calibration",
        action="store_true",
        help="Applique la calibration suggeree directement dans config/calibration.json.",
    )
    args = parser.parse_args()

    root_dir = ROOT / "sessions"
    recorder = SessionRecorder(root_dir)

    if args.session:
        session_dir = args.session
    else:
        sessions = recorder.list_sessions()
        if not sessions:
            raise SystemExit("Aucune session disponible dans ./sessions")
        session_dir = sessions[0]

    results = annotate_session_with_openai(
        session_dir=session_dir,
        model=args.model,
        limit=args.limit,
        overwrite_annotation=args.overwrite_annotation,
        overwrite_review_expected=args.overwrite_review_expected,
        apply_calibration=args.apply_calibration,
    )

    print(f"Snapshots traites: {len(results)}")
    print(f"Session: {session_dir}")
    print(f"Suggestion calibration: {session_dir / 'openai_calibration.suggested.json'}")
    if args.apply_calibration:
        print("Calibration appliquee dans config/calibration.json")


if __name__ == "__main__":
    main()
