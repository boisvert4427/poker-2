from __future__ import annotations

import argparse
import json
from pathlib import Path

from poker_tracker.villain_db import DEFAULT_DB_PATH, compute_player_profiles, import_all_histories, open_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Importe les historiques Winamax dans une base SQLite de profils vilains.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Chemin vers la base SQLite.")
    args = parser.parse_args()

    connection = open_db(args.db)
    try:
        stats = import_all_histories(connection)
        profiles = compute_player_profiles(connection)
    finally:
        connection.close()

    summary = {
        "db_path": str(args.db),
        "files_seen": stats.files_seen,
        "hands_seen": stats.hands_seen,
        "hands_inserted": stats.hands_inserted,
        "actions_inserted": stats.actions_inserted,
        "players_upserted": stats.players_upserted,
        "players_profiled": len(profiles),
        "top_profiles": profiles[:20],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
