from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .detection import guess_history_locations
from .history import read_history_text
from .parser import ParsedHand, parse_winamax_hand


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "villains.sqlite3"
ACTION_LINE_RE = __import__("re").compile(
    r"^(?P<player>.+?)\s+"
    r"(?P<action>posts small blind|posts big blind|checks|calls|raises|bets|folds|shows|collected)\b"
    r"(?P<rest>.*)$",
    __import__("re").IGNORECASE,
)


@dataclass(slots=True)
class ImportStats:
    files_seen: int = 0
    hands_seen: int = 0
    hands_inserted: int = 0
    actions_inserted: int = 0
    players_upserted: int = 0


def open_db(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    _init_schema(connection)
    return connection


def import_all_histories(connection: sqlite3.Connection, history_dirs: list[str] | None = None) -> ImportStats:
    stats = ImportStats()
    _clear_import_tables(connection)
    for history_file in _iter_history_files(history_dirs):
        stats.files_seen += 1
        try:
            raw = read_history_text(str(history_file))
        except OSError:
            continue
        for chunk in _split_history_chunks(raw):
            hand = parse_winamax_hand(chunk)
            if not hand.hand_id:
                continue
            stats.hands_seen += 1
            inserted, action_count, player_count = import_parsed_hand(connection, hand, str(history_file))
            if inserted:
                stats.hands_inserted += 1
                stats.actions_inserted += action_count
                stats.players_upserted += player_count
    connection.commit()
    return stats


def import_parsed_hand(
    connection: sqlite3.Connection,
    hand: ParsedHand,
    source_file: str,
) -> tuple[bool, int, int]:
    cursor = connection.cursor()
    existing = cursor.execute("SELECT hand_id FROM hands WHERE hand_id = ?", (hand.hand_id,)).fetchone()
    if existing:
        return False, 0, 0

    cursor.execute(
        """
        INSERT INTO hands (
            hand_id, source_file, played_at, table_name, table_format, game_type, variant,
            small_blind, big_blind, hero_name, hero_cards, button_seat, total_pot
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            hand.hand_id,
            source_file,
            hand.played_at,
            hand.table_name,
            hand.table_format,
            hand.game_type,
            hand.variant,
            hand.small_blind,
            hand.big_blind,
            hand.hero_name,
            hand.hero_cards,
            hand.button_seat,
            hand.total_pot,
        ),
    )

    player_count = 0
    for seat in hand.seats:
        player_name = seat.get("player", "")
        stack_value = _to_float(seat.get("stack", ""))
        cursor.execute(
            """
            INSERT INTO players (name)
            VALUES (?)
            ON CONFLICT(name) DO NOTHING
            """,
            (player_name,),
        )
        cursor.execute(
            """
            INSERT INTO hand_players (hand_id, player_name, seat_no, stack, is_hero)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                hand.hand_id,
                player_name,
                _to_int(seat.get("seat", "")),
                stack_value,
                1 if player_name == hand.hero_name else 0,
            ),
        )
        player_count += 1

    action_count = 0
    for street, actions in hand.streets.items():
        if street == "meta":
            continue
        for sequence_no, action_text in enumerate(actions, start=1):
            player_name, action_type, amount = _parse_action_line(action_text)
            cursor.execute(
                """
                INSERT INTO actions (hand_id, street, sequence_no, raw_text, player_name, action_type, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hand.hand_id,
                    street,
                    sequence_no,
                    action_text,
                    player_name,
                    action_type,
                    amount,
                ),
            )
            action_count += 1

    return True, action_count, player_count


def compute_player_profiles(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        WITH action_base AS (
            SELECT
                player_name,
                LOWER(action_type) AS action_type,
                hand_id,
                street
            FROM actions
            WHERE player_name IS NOT NULL
              AND player_name != ''
              AND street = 'pre_flop'
        ),
        vpip_hands AS (
            SELECT DISTINCT player_name, hand_id
            FROM action_base
            WHERE action_type IN ('calls', 'raises', 'bets', 'all-in', 'all_in')
        ),
        pfr_hands AS (
            SELECT DISTINCT player_name, hand_id
            FROM action_base
            WHERE action_type IN ('raises', 'bets', 'all-in', 'all_in')
        ),
        player_hand_counts AS (
            SELECT player_name, COUNT(DISTINCT hand_id) AS hands_played
            FROM hand_players
            GROUP BY player_name
        )
        SELECT
            phc.player_name AS name,
            phc.hands_played,
            COALESCE(vpip.cnt, 0) AS vpip_hands,
            COALESCE(pfr.cnt, 0) AS pfr_hands
        FROM player_hand_counts phc
        LEFT JOIN (
            SELECT player_name, COUNT(DISTINCT hand_id) AS cnt
            FROM vpip_hands
            GROUP BY player_name
        ) vpip ON vpip.player_name = phc.player_name
        LEFT JOIN (
            SELECT player_name, COUNT(DISTINCT hand_id) AS cnt
            FROM pfr_hands
            GROUP BY player_name
        ) pfr ON pfr.player_name = phc.player_name
        ORDER BY phc.hands_played DESC, phc.player_name ASC
        """
    ).fetchall()

    profiles: list[dict[str, object]] = []
    for row in rows:
        hands_played = int(row["hands_played"] or 0)
        vpip_hands = int(row["vpip_hands"] or 0)
        pfr_hands = int(row["pfr_hands"] or 0)
        vpip = round(vpip_hands / hands_played, 3) if hands_played else 0.0
        pfr = round(pfr_hands / hands_played, 3) if hands_played else 0.0
        profiles.append(
            {
                "name": row["name"],
                "hands_played": hands_played,
                "vpip": vpip,
                "pfr": pfr,
                "profile": _classify_profile(vpip, pfr, hands_played),
            }
        )
    return profiles


def get_player_profile(connection: sqlite3.Connection, player_name: str) -> dict[str, object] | None:
    row = connection.execute(
        """
        WITH action_base AS (
            SELECT
                player_name,
                LOWER(action_type) AS action_type,
                hand_id,
                street
            FROM actions
            WHERE player_name = ?
              AND player_name IS NOT NULL
              AND player_name != ''
              AND street = 'pre_flop'
        ),
        vpip_hands AS (
            SELECT COUNT(DISTINCT hand_id) AS cnt
            FROM action_base
            WHERE action_type IN ('calls', 'raises', 'bets', 'all-in', 'all_in')
        ),
        pfr_hands AS (
            SELECT COUNT(DISTINCT hand_id) AS cnt
            FROM action_base
            WHERE action_type IN ('raises', 'bets', 'all-in', 'all_in')
        ),
        player_hand_counts AS (
            SELECT COUNT(DISTINCT hand_id) AS hands_played
            FROM hand_players
            WHERE player_name = ?
        )
        SELECT
            ? AS name,
            COALESCE((SELECT hands_played FROM player_hand_counts), 0) AS hands_played,
            COALESCE((SELECT cnt FROM vpip_hands), 0) AS vpip_hands,
            COALESCE((SELECT cnt FROM pfr_hands), 0) AS pfr_hands
        """,
        (player_name, player_name, player_name),
    ).fetchone()

    if row is None:
        return None

    hands_played = int(row["hands_played"] or 0)
    if hands_played <= 0:
        return None

    vpip_hands = int(row["vpip_hands"] or 0)
    pfr_hands = int(row["pfr_hands"] or 0)
    vpip = round(vpip_hands / hands_played, 3) if hands_played else 0.0
    pfr = round(pfr_hands / hands_played, 3) if hands_played else 0.0
    return {
        "name": row["name"],
        "hands_played": hands_played,
        "vpip": vpip,
        "pfr": pfr,
        "profile": _classify_profile(vpip, pfr, hands_played),
    }


def _init_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS players (
            name TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS hands (
            hand_id TEXT PRIMARY KEY,
            source_file TEXT NOT NULL,
            played_at TEXT,
            table_name TEXT,
            table_format TEXT,
            game_type TEXT,
            variant TEXT,
            small_blind REAL,
            big_blind REAL,
            hero_name TEXT,
            hero_cards TEXT,
            button_seat INTEGER,
            total_pot REAL
        );

        CREATE TABLE IF NOT EXISTS hand_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id TEXT NOT NULL,
            player_name TEXT NOT NULL,
            seat_no INTEGER,
            stack REAL,
            is_hero INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(hand_id) REFERENCES hands(hand_id) ON DELETE CASCADE,
            FOREIGN KEY(player_name) REFERENCES players(name)
        );

        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id TEXT NOT NULL,
            street TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            raw_text TEXT NOT NULL,
            player_name TEXT,
            action_type TEXT,
            amount REAL,
            FOREIGN KEY(hand_id) REFERENCES hands(hand_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_hand_players_player_name ON hand_players(player_name);
        CREATE INDEX IF NOT EXISTS idx_actions_player_name ON actions(player_name);
        CREATE INDEX IF NOT EXISTS idx_actions_hand_street ON actions(hand_id, street);
        """
    )


def _iter_history_files(history_dirs: list[str] | None) -> list[Path]:
    if history_dirs is None:
        history_dirs = [
            item.path
            for item in guess_history_locations()
            if item.exists and item.accessible and item.path.lower().endswith("history")
        ]

    files: list[Path] = []
    for history_dir in history_dirs:
        root = Path(history_dir)
        if not root.exists() or not root.is_dir():
            continue
        files.extend(sorted(child for child in root.iterdir() if child.is_file() and child.suffix.lower() == ".txt"))
    return files


def _split_history_chunks(raw: str) -> list[str]:
    return [chunk.strip() for chunk in raw.split("\n\n\n") if chunk.strip()]


def _parse_action_line(action_text: str) -> tuple[str, str, float | None]:
    normalized = action_text.strip()
    match = ACTION_LINE_RE.match(normalized)
    if not match:
        return "", normalized.lower(), None
    player_name = match.group("player").strip()
    action_type = match.group("action").strip().lower().replace(" ", "_")
    amount = _extract_amount(match.group("rest") or "")
    return player_name, action_type, amount


def _extract_amount(text: str) -> float | None:
    for token in text.replace(",", ".").split():
        try:
            return float(token)
        except ValueError:
            continue
    return None


def _to_float(value: str) -> float | None:
    try:
        return float((value or "").replace(",", "."))
    except ValueError:
        return None


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _classify_profile(vpip: float, pfr: float, hands_played: int) -> str:
    if hands_played < 10:
        return "insufficient_data"
    if vpip < 0.18 and pfr < 0.14:
        return "nit"
    if vpip < 0.26 and pfr >= 0.16:
        return "tag"
    if vpip >= 0.30 and pfr >= 0.20:
        return "lag"
    if vpip >= 0.35 and pfr < 0.18:
        return "loose_passive"
    return "standard"


def _clear_import_tables(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM actions")
    connection.execute("DELETE FROM hand_players")
    connection.execute("DELETE FROM hands")
    connection.execute("DELETE FROM players")
