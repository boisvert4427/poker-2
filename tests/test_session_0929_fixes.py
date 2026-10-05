import unittest
from types import SimpleNamespace
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
from dataclasses import dataclass

from PIL import Image
from poker_tracker.app import PokerTrackerApp
from poker_tracker.ocr import read_call_amount_retry
from poker_tracker.decision_support import DecisionRecommendation, _decision_explanation
from poker_tracker.local_snapshot_analysis import capture_has_card_animation


class SessionFixTests(unittest.TestCase):
    def test_animation_wait_is_bounded_and_resets(self):
        tracker = SimpleNamespace(card_animation_started_at=None)
        check = PokerTrackerApp._defer_card_animation
        self.assertTrue(check(tracker, True, 10.0))
        self.assertTrue(check(tracker, True, 10.5))
        self.assertFalse(check(tracker, True, 11.0))
        self.assertFalse(check(tracker, True, 12.0))
        self.assertFalse(check(tracker, False, 12.1))
        self.assertTrue(check(tracker, True, 13.0))

    def test_animation_gate_ignores_white_cards_and_empty_green_slots(self):
        with TemporaryDirectory() as td, patch(
            "poker_tracker.local_snapshot_analysis.load_calibration",
            return_value={"zones": {"hero_card_1_value": [0, 0, 1, 1]}},
        ):
            p = Path(td) / "frame.png"
            for color, expected in [((255, 255, 255), False), ((0, 85, 25), False), ((160, 195, 170), True)]:
                Image.new("RGB", (30, 40), color).save(p)
                self.assertEqual(capture_has_card_animation(str(p)), expected)

    def test_first_observation_remembers_fold(self):
        @dataclass
        class Snapshot:
            players_in_hand: list
            detected_fields: dict
            recent_actions: list
        tracker = SimpleNamespace(
            live_seen_active_seats=set(), live_folded_seats=set(),
            _explicit_folded_seats=PokerTrackerApp._explicit_folded_seats,
        )
        snap = Snapshot(["hero", "left"], {"right_action": "FOLD", "right_cards_visible": "not_visible"}, [])
        PokerTrackerApp._stabilize_players_in_hand(tracker, snap, same_hand=False)
        self.assertEqual(tracker.live_folded_seats, {"right"})
        noisy = Snapshot(["hero", "left", "right"], {}, [])
        with patch("poker_tracker.app.recompute_snapshot_recommendation", side_effect=lambda s: s):
            result = PokerTrackerApp._stabilize_players_in_hand(tracker, noisy, same_hand=True)
        self.assertNotIn("right", result.players_in_hand)

    def test_fold_label_without_readable_name(self):
        snap = SimpleNamespace(detected_fields={"right_action": "FOLD", "right_cards_visible": "not_visible"}, recent_actions=[])
        self.assertEqual(PokerTrackerApp._explicit_folded_seats(snap), {"right"})
        snap.detected_fields["right_cards_visible"] = "visible"
        self.assertEqual(PokerTrackerApp._explicit_folded_seats(snap), set())

    def test_fold_name_is_not_substring(self):
        snap = SimpleNamespace(detected_fields={"right_name": "Ann"}, recent_actions=["Anna folds"])
        self.assertEqual(PokerTrackerApp._explicit_folded_seats(snap), set())

    def test_numeric_retry_requires_unit(self):
        with TemporaryDirectory() as td:
            p = Path(td) / "frame.png"
            Image.new("RGB", (1936, 1048)).save(p)
            with patch("poker_tracker.ocr._find_tesseract", return_value="test"), patch(
                "poker_tracker.ocr._run_tesseract",
                side_effect=[SimpleNamespace(stdout="46", returncode=0), SimpleNamespace(stdout="4 BB CALL", returncode=0)]
            ) as run:
                self.assertEqual(read_call_amount_retry(p), "4 BB CALL")
                self.assertEqual(run.call_count, 2)

    def test_multiway_explanation_names_individual_and_joint(self):
        r = DecisionRecommendation("CHECK", "", .5, "paire", "", "", [])
        r.villain_hand_probabilities = ["Alice (left) [individuel] : top paire 8%", "Multiway [conjoint] : au moins un top paire 13%"]
        text = _decision_explanation(r)
        self.assertIn("Alice (left) [individuel]", text)
        self.assertIn("au moins un top paire 13%", text)
        self.assertNotIn("Vilain a", text)
