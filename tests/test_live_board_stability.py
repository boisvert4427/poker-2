from __future__ import annotations

from dataclasses import dataclass
import unittest

from poker_tracker.app import PokerTrackerApp


@dataclass
class MiniSnapshot:
    detected_fields: dict[str, str]
    visible_board: str
    current_street: str
    hero_cards: str = ""


class LiveBoardStabilityTests(unittest.TestCase):
    def test_new_board_signature_forces_a_fresh_full_analysis(self):
        snapshot = type("Fast", (), {"is_hero_turn": True, "available_actions": ["FOLD", "CHECK", "RAISE"], "visual_buttons": ["left", "center", "right"]})()
        preflop = PokerTrackerApp._fast_live_signature(snapshot, board_signature="pre", hero_signature="hero")
        flop = PokerTrackerApp._fast_live_signature(snapshot, board_signature="flop", hero_signature="hero")
        self.assertNotEqual(preflop, flop)

    def test_same_board_glyph_keeps_previous_rank(self):
        tracker = object.__new__(PokerTrackerApp)
        tracker.current_live_snapshot = MiniSnapshot(
            {"board_card_1": "3s", "board_card_2": "qh", "board_card_3": "7c"},
            "3s qh 7c",
            "flop",
        )
        tracker.cached_board_card_fingerprints = {"board_card_2": bytes([0, 1]) * 384}
        current = MiniSnapshot(
            {"board_card_1": "3s", "board_card_2": "9h", "board_card_3": "7c"},
            "3s 9h 7c",
            "flop",
        )
        stabilized = tracker._stabilize_board_cards(
            current,
            {"board_card_2": bytes([0, 1]) * 384},
            same_hand=True,
        )
        self.assertEqual(stabilized.detected_fields["board_card_2"], "qh")
        self.assertEqual(stabilized.visible_board, "3s qh 7c")

    def test_new_hand_does_not_reuse_previous_board(self):
        tracker = object.__new__(PokerTrackerApp)
        tracker.current_live_snapshot = MiniSnapshot({"board_card_1": "qh"}, "qh", "preflop")
        tracker.cached_board_card_fingerprints = {"board_card_1": b"x" * 10}
        current = MiniSnapshot({"board_card_1": ""}, "", "preflop")
        self.assertIs(current, tracker._stabilize_board_cards(current, {"board_card_1": b"x" * 10}, False))

    def test_preserved_board_recomputes_its_street(self):
        previous = MiniSnapshot(
            {"board_card_1": "3s", "board_card_2": "qh", "board_card_3": "7c"},
            "3s qh 7c",
            "flop",
        )
        current = MiniSnapshot(
            {"board_card_1": "", "board_card_2": "", "board_card_3": ""},
            "",
            "preflop",
        )
        result = PokerTrackerApp._preserve_live_details(previous, current, same_hand=True)
        self.assertEqual(result.visible_board, "3s qh 7c")
        self.assertEqual(result.current_street, "flop")


if __name__ == "__main__":
    unittest.main()
