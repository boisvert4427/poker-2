from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from poker_tracker.history_matcher import match_session_to_history
from poker_tracker.session_recorder import SessionRecorder


def main() -> None:
    parser = argparse.ArgumentParser(description="Lie les snapshots d'une session a des mains d'historique.")
    parser.add_argument("--session", type=Path, help="Chemin du dossier de session.")
    args = parser.parse_args()

    recorder = SessionRecorder(ROOT / "sessions")
    session_dir = args.session if args.session else _latest_session(recorder)
    summary = match_session_to_history(session_dir)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def _latest_session(recorder: SessionRecorder) -> Path:
    sessions = recorder.list_sessions()
    if not sessions:
        raise SystemExit("Aucune session disponible.")
    return sessions[0]


if __name__ == "__main__":
    main()
