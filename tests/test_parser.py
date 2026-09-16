from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from poker_tracker.history import latest_hand_block_key
from poker_tracker.parser import parse_winamax_hand, split_winamax_hands
from poker_tracker.villain_db import get_player_profile, open_db, sync_completed_history_file
from poker_tracker.live_state import _decision_amounts
from poker_tracker.villain_db import import_parsed_hand


HISTORY = """Winamax Poker - CashGame - HandId: #1-1-1 - Holdem no limit (0.01/0.02) - date
Table: 'Test' 5-max (play money) Seat #1 is the button
Seat 1: Hero (2)
Seat 2: Vilain (2)
Dealt to Hero [Qc 5c]
*** SUMMARY ***
Total pot 0.03 | No rake

Winamax Poker - CashGame - HandId: #1-2-2 - Holdem no limit (0.01/0.02) - date
Table: 'Test' 5-max (play money) Seat #2 is the button
Seat 1: Hero (2.01)
Seat 2: Vilain (1.99)
Dealt to Hero [5c Ks]
*** PRE-FLOP ***
Hero checks
*** FLOP *** [6d 8c 9c]
Vilain checks
*** TURN *** [6d 8c 9c][4s]
Hero checks
"""


class ParserTests(unittest.TestCase):
    def test_history_key_stays_stable_when_actions_are_appended(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.txt"
            header = "Winamax Poker - CashGame - HandId: #123-456 - Holdem (0.01/0.02) - now\n"
            path.write_text(header + "Hero checks\n", encoding="utf-8")
            first = latest_hand_block_key(str(path))
            path.write_text(header + "Hero checks\nVilain bets 1\n", encoding="utf-8")
            self.assertEqual(first, latest_hand_block_key(str(path)))
            self.assertEqual(first, "123-456")

    def test_split_uses_hand_headers(self):
        self.assertEqual(len(split_winamax_hands(HISTORY)), 2)

    def test_complete_file_returns_latest_hand_only(self):
        hand = parse_winamax_hand(HISTORY)
        self.assertEqual(hand.hand_id, "1-2-2")
        self.assertEqual(hand.hero_cards, "5c Ks")
        self.assertEqual(hand.seats, [
            {"seat": "1", "player": "Hero", "stack": "2.01"},
            {"seat": "2", "player": "Vilain", "stack": "1.99"},
        ])

    def test_board_is_tracked_by_street(self):
        hand = parse_winamax_hand(HISTORY)
        self.assertEqual(hand.board_by_street["flop"], "6d 8c 9c")
        self.assertEqual(hand.board_by_street["turn"], "6d 8c 9c 4s")
        self.assertEqual(hand.current_street, "turn")
        self.assertFalse(hand.is_complete)

    def test_completed_history_is_imported_once_into_live_database(self):
        with tempfile.TemporaryDirectory() as folder:
            history_path = Path(folder) / "history.txt"
            db_path = Path(folder) / "villains.sqlite3"
            # Only the first block has SUMMARY, so it is the only completed
            # hand that may affect live opponent stats at this moment.
            history_path.write_text(HISTORY, encoding="utf-8")
            first = sync_completed_history_file(history_path, db_path=db_path)
            second = sync_completed_history_file(history_path, db_path=db_path)
            self.assertEqual(first.hands_inserted, 1)
            self.assertEqual(second.hands_inserted, 0)
            connection = open_db(db_path)
            try:
                profile = get_player_profile(connection, "Vilain")
            finally:
                connection.close()
            self.assertIsNotNone(profile)
            self.assertEqual(profile["hands_played"], 1)

    def test_history_all_in_amount_is_used_when_call_button_ocr_is_missing(self):
        pot, call = _decision_amounts(
            {"hero_bet": "2 BB"},
            ["right", "hero"],
            "Pot total : 18 BB",
            "FOLD",
            ["Villain raises 8.50 to 10.50 and is all-in"],
        )
        self.assertEqual(pot, 18.0)
        self.assertEqual(call, 8.5)

    def test_real_money_euro_history_keeps_hand_id_seats_and_actions(self):
        raw = """Winamax Poker - CashGame - HandId: #1-2-3 - Holdem no limit (0.01€ /0.02€) - now
Table: 'Aalen 02' 5-max (real money) Seat #2 is the button
Seat 1: DESTROYMEPLZ (2.47€)
Seat 2: RougeLion (2.01€)
Dealt to RougeLion [4c 3c]
*** PRE-FLOP ***
DESTROYMEPLZ raises 0.03€ to 0.05€
RougeLion folds
*** SUMMARY ***
Total pot 0.09€ | No rake
"""
        hand = parse_winamax_hand(raw)
        self.assertEqual(hand.hand_id, "1-2-3")
        self.assertEqual(hand.big_blind, 0.02)
        self.assertEqual(hand.seats[0]["player"], "DESTROYMEPLZ")
        with tempfile.TemporaryDirectory() as folder:
            connection = open_db(Path(folder) / "test.sqlite3")
            try:
                inserted, actions, _ = import_parsed_hand(connection, hand, "history.txt")
                connection.commit()
                amount = connection.execute("SELECT amount FROM actions WHERE player_name = ?", ("DESTROYMEPLZ",)).fetchone()["amount"]
            finally:
                connection.close()
        self.assertTrue(inserted)
        self.assertEqual(actions, 2)
        self.assertEqual(amount, 0.03)


if __name__ == "__main__":
    unittest.main()
