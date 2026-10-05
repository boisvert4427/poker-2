from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from poker_tracker.app import PokerTrackerApp
from poker_tracker.detection import HistoryLocation
from poker_tracker.history import (
    HistoryFile,
    extract_table_token,
    find_history_file_for_table,
    freeze_history_file,
    latest_hand_block_key,
)


class HistoryBindingTests(unittest.TestCase):
    def test_frozen_history_does_not_advance_after_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.txt"
            path.write_text(
                "Winamax Poker - CashGame - HandId: #111 - Holdem no limit (0.01/0.02) - now\n",
                encoding="utf-8",
            )
            stat = path.stat()
            frozen = freeze_history_file(HistoryFile(str(path), stat.st_mtime, stat.st_size))
            path.write_text(
                "Winamax Poker - CashGame - HandId: #111 - Holdem no limit (0.01/0.02) - now\n"
                "Hero raises\n"
                "Winamax Poker - CashGame - HandId: #222 - Holdem no limit (0.01/0.02) - later\n",
                encoding="utf-8",
            )
            self.assertEqual(latest_hand_block_key(frozen), "111")
            self.assertEqual(latest_hand_block_key(HistoryFile(str(path), 0.0, 0)), "222")

    def test_extracts_table_name_from_real_window_caption(self) -> None:
        self.assertEqual(
            extract_table_token("Aalen 07 - 0,01-0,02 - No Limit Holdem"),
            "Aalen 07",
        )
        self.assertEqual(extract_table_token("Winamax Aalen 07"), "Aalen 07")
        self.assertEqual(extract_table_token("Winamax"), "")

    def test_invalid_board_is_never_cached(self) -> None:
        self.assertEqual(PokerTrackerApp._valid_board_sequence("4c c 4h"), "")
        self.assertEqual(
            PokerTrackerApp._valid_board_sequence("4s 6c 5h Kc 2s"),
            "4s 6c 5h kc 2s",
        )

    def test_does_not_match_another_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "history"
            root.mkdir()
            (root / "20260917_Nice 21_real_holdem_no-limit.txt").write_text("old")
            self.assertIsNone(
                find_history_file_for_table(
                    [directory],
                    "Aalen 07 - 0,01-0,02 - No Limit Holdem",
                )
            )

    def test_matches_only_the_active_table_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "20260917_Aalen 07_real_holdem_no-limit.txt"
            expected.write_text("current")
            (root / "20260917_Nice 21_real_holdem_no-limit.txt").write_text("other")
            result = find_history_file_for_table(
                [directory],
                "Aalen 07 - 0,01-0,02 - No Limit Holdem",
            )
            self.assertIsNotNone(result)
            self.assertEqual(Path(result.path), expected)

    def test_live_session_waits_for_a_change_then_keeps_that_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "history"
            root.mkdir()
            old = root / "old.txt"
            old.write_text("old")
            detection = {
                "history_locations": [
                    HistoryLocation(str(root), True, "test", True, "ok")
                ],
                "latest_history_file": None,
            }
            app = PokerTrackerApp.__new__(PokerTrackerApp)
            app.live_debug_var = SimpleNamespace(get=lambda: True)
            app.live_history_baseline = app._snapshot_history_files(detection)
            app.live_bound_history_file = None

            self.assertIsNone(app._history_file_for_live_session(detection))
            current = root / "current.txt"
            current.write_text("first hand")
            bound = app._history_file_for_live_session(detection)
            self.assertIsNotNone(bound)
            self.assertEqual(Path(bound.path), current)

            other = root / "another.txt"
            other.write_text("newer table")
            rebound = app._history_file_for_live_session(detection)
            self.assertEqual(Path(rebound.path), current)


if __name__ == "__main__":
    unittest.main()
