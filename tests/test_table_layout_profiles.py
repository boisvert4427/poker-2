import tempfile
import unittest
from pathlib import Path

from poker_tracker.config import (
    THREE_MAX_ZONE_OVERRIDES,
    calibration_profile,
    detect_calibration_profile,
    lock_calibration_profile,
    load_calibration,
)
from poker_tracker.history import HistoryFile, table_layout_from_history
from poker_tracker.live_state import _history_names_for_screen, _position_for_layout
from poker_tracker.ocr import _zone_definitions
from poker_tracker.parser import ParsedHand
from poker_tracker.gto_preflop import recommend_preflop_baseline


class TableLayoutProfileTests(unittest.TestCase):
    def tearDown(self):
        lock_calibration_profile(None)

    def test_history_layout_uses_the_latest_table_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.txt"
            path.write_text(
                "Table: 'Old' 5-max (real money) Seat #1 is the button\n"
                "Table: 'Current' 3-max (real money) Seat #2 is the button\n",
                encoding="utf-8",
            )
            history = HistoryFile(str(path), 0.0, path.stat().st_size)
            self.assertEqual(table_layout_from_history(history), "3max")

    def test_history_lock_overrides_visual_detection(self):
        lock_calibration_profile("3max")
        self.assertEqual(detect_calibration_profile("missing-image.png"), "3max")
    def test_five_max_calibration_is_unchanged_by_three_max_profile(self):
        before = load_calibration("5max")["zones"]
        with calibration_profile("3max"):
            three = load_calibration()["zones"]
        after = load_calibration("5max")["zones"]
        self.assertEqual(before, after)
        self.assertNotEqual(three["top_left_name"], before["top_left_name"])
        self.assertEqual(three["board_card_1"], before["board_card_1"])

    def test_three_max_ocr_omits_nonexistent_side_seats(self):
        with calibration_profile("3max"):
            names = {item[0] for item in _zone_definitions(1936, 1048)}
        self.assertNotIn("left_name", names)
        self.assertNotIn("right_name", names)
        self.assertIn("action_left", names)
        self.assertIn("top_left_name", names)

    def test_positions_are_layout_specific(self):
        self.assertEqual(_position_for_layout("hero", "hero", "3max"), "BTN")
        self.assertEqual(_position_for_layout("hero", "top_right", "3max"), "SB")
        self.assertEqual(_position_for_layout("hero", "top_left", "3max"), "BB")
        self.assertEqual(_position_for_layout("hero", "right", "5max"), "SB")

    def test_three_max_preflop_baseline_is_separate(self):
        three = recommend_preflop_baseline("Kh 4d", "BTN", "unopened", table_size=3)
        five = recommend_preflop_baseline("Kh 4d", "BTN", "unopened", table_size=5)
        self.assertEqual(three.action, "RAISE")
        self.assertEqual(five.action, "FOLD")
        self.assertIn("3-max", three.reason)

    def test_three_max_history_maps_only_two_opponents(self):
        hand = ParsedHand(hero_name="Hero", seats=[
            {"seat": "1", "player": "Hero"},
            {"seat": "2", "player": "Left"},
            {"seat": "3", "player": "Right"},
        ])
        names = _history_names_for_screen(hand)
        self.assertEqual(names["top_right_name"], "Right")
        self.assertEqual(names["top_left_name"], "Left")
        self.assertNotIn("left_name", names)

    def test_real_sessions_detect_without_changing_five_max(self):
        root = Path(__file__).resolve().parents[1] / "sessions"
        three = root / "20261005_172831" / "live_turn_2026-10-05T17-28-40-867.png"
        five = root / "20260929_203255" / "live_turn_2026-09-29T20-33-18-403.png"
        if three.exists() and five.exists():
            self.assertEqual(detect_calibration_profile(three), "3max")
            self.assertEqual(detect_calibration_profile(five), "5max")

