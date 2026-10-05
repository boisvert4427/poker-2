from __future__ import annotations

from dataclasses import dataclass
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from PIL import Image

from poker_tracker.app import PokerTrackerApp
from poker_tracker.ocr import _bet_marker_visible
from poker_tracker.local_snapshot_analysis import _extract_single_card_rank, _extract_stack
from poker_tracker.live_state import _repair_or_flag_preflop_amounts


@dataclass
class MiniSnapshot:
    detected_fields: dict[str, str]
    visible_board: str
    current_street: str
    hero_cards: str = ""


class LiveBoardStabilityTests(unittest.TestCase):
    def test_live_tick_actually_queues_retry_on_unchanged_hero_turn(self):
        tracker = MagicMock()
        tracker.full_ocr_display_until = 0
        tracker.full_ocr_in_progress = False
        tracker.live_tick_counter = 1
        tracker.background_refresh_every = 20
        tracker.current_detection = {"active_table_window": object()}
        tracker.cached_history_block_key = ""
        tracker.hero_turn_release_streak = 0
        tracker.current_live_snapshot = SimpleNamespace(is_hero_turn=True)
        tracker._snapshot_needs_retry.return_value = True
        tracker.last_fast_live_signature = (True,)
        tracker._fast_live_signature.return_value = (True,)
        tracker._should_run_full_ocr.return_value = True
        tracker._defer_card_animation.return_value = False
        fast = SimpleNamespace(is_hero_turn=True)
        with patch("poker_tracker.app.capture_window", return_value="frame.png"), \
             patch("poker_tracker.app.latest_hand_block_key", return_value=""), \
             patch("poker_tracker.app.has_active_action_bar", return_value=False), \
             patch("poker_tracker.app.build_fast_live_snapshot", return_value=fast):
            PokerTrackerApp._live_tick(tracker)
        tracker._queue_full_ocr_request.assert_called_once()
        tracker._queue_full_ocr_request.reset_mock()
        tracker._defer_card_animation.return_value = True
        with patch("poker_tracker.app.capture_window", return_value="frame.png"), \
             patch("poker_tracker.app.latest_hand_block_key", return_value=""), \
             patch("poker_tracker.app.has_active_action_bar", return_value=False), \
             patch("poker_tracker.app.build_fast_live_snapshot", return_value=fast):
            PokerTrackerApp._live_tick(tracker)
        tracker._queue_full_ocr_request.assert_not_called()
        tracker._hide_table_decision_overlay.assert_called()

    def test_incomplete_cached_rank_does_not_replace_complete_new_card(self):
        tracker = object.__new__(PokerTrackerApp)
        tracker.current_live_snapshot = MiniSnapshot({"board_card_4": "4"}, "4", "turn")
        tracker.cached_board_card_fingerprints = {"board_card_4": b"same"}
        current = MiniSnapshot({"board_card_4": "4s"}, "4s", "turn")
        result = tracker._stabilize_board_cards(current, {"board_card_4": b"same"}, True)
        self.assertEqual(result.detected_fields["board_card_4"], "4s")

    def test_waiting_snapshot_requires_another_detailed_read(self):
        waiting = type(
            "Snapshot", (),
            {"recommendation": type("Recommendation", (), {"action": "ATTENDRE", "decision_ready": False})()},
        )()
        ready = type(
            "Snapshot", (),
            {"recommendation": type("Recommendation", (), {"action": "CHECK", "decision_ready": True})()},
        )()
        self.assertTrue(PokerTrackerApp._snapshot_needs_retry(waiting))
        self.assertFalse(PokerTrackerApp._snapshot_needs_retry(ready))

    def test_single_board_rank_ignores_one_trailing_glyph_fragment(self):
        self.assertEqual(_extract_single_card_rank("9g"), "9")

    def test_missing_leading_one_in_preflop_bet_is_repaired_from_pot(self):
        fields = {
            "top_left_bet": "3 BB",
            "right_bet": "2,5 BB",
            "hero_bet": "1 BB",
        }
        result = _repair_or_flag_preflop_amounts(
            fields,
            current_street="preflop",
            pot_size=16.5,
            available_actions=["FOLD", "CALL", "RAISE"],
        )
        self.assertEqual(result, "repaired")
        self.assertEqual(fields["right_bet"], "12.5 BB")

    def test_incoherent_preflop_pot_without_unique_repair_is_blocked(self):
        fields = {"top_left_bet": "3 BB", "hero_bet": "1 BB"}
        result = _repair_or_flag_preflop_amounts(
            fields,
            current_street="preflop",
            pot_size=20.0,
            available_actions=["FOLD", "CALL", "RAISE"],
        )
        self.assertEqual(result, "pot incompatible avec les mises visibles")

    def test_bet_parser_accepts_tesseract_beb_suffix(self):
        self.assertEqual(_extract_stack("2,5 BEB"), "2,5 BB")

    def test_yellow_bet_text_triggers_ocr_without_orange_chip(self):
        crop = Image.new("RGB", (40, 20), (0, 85, 30))
        for x in range(8, 24):
            for y in range(6, 12):
                crop.putpixel((x, y), (245, 190, 25))
        self.assertTrue(_bet_marker_visible(crop))

    def test_empty_green_bet_crop_stays_skipped(self):
        self.assertFalse(_bet_marker_visible(Image.new("RGB", (40, 20), (0, 85, 30))))

    def test_remembered_action_is_returned_for_immediate_recommendation(self):
        tracker = object.__new__(PokerTrackerApp)
        tracker.live_action_memory = []
        tracker.live_action_events = []
        tracker.live_action_memory_hand = "Ah Kh"
        tracker.live_action_memory_seen = set()
        tracker.live_contributions_by_street = {}
        tracker.live_observed_streets = set()
        tracker.live_pot_by_street = {}
        snapshot = type(
            "Snapshot",
            (),
            {
                "hero_cards": "Ah Kh",
                "current_street": "preflop",
                "dealer_owner": "top_right",
                "is_hero_turn": True,
                "detected_fields": {
                    "right_name": "Open",
                    "right_bet": "2,5 BB",
                    "right_stack": "97,5 BB",
                    "hero_bet": "1 BB",
                },
            },
        )()
        remembered = tracker._remember_live_actions(snapshot)
        self.assertEqual(remembered, ["Open raises 2.5 BB"])
        self.assertEqual(tracker.live_action_memory, remembered)

    def test_pot_growth_without_visible_action_is_reported(self):
        tracker = object.__new__(PokerTrackerApp)
        tracker.live_action_memory = []
        tracker.live_action_events = []
        tracker.live_action_memory_hand = "Ah Kh"
        tracker.live_action_memory_seen = set()
        tracker.live_contributions_by_street = {"flop": {}}
        tracker.live_observed_streets = {"flop"}
        tracker.live_pot_by_street = {"flop": 6.0}
        snapshot = type(
            "Snapshot",
            (),
            {
                "hero_cards": "Ah Kh",
                "current_street": "flop",
                "dealer_owner": "top_right",
                "is_hero_turn": True,
                "pot_text": "Pot total : 10 BB",
                "detected_fields": {},
            },
        )()
        remembered = tracker._remember_live_actions(snapshot)
        self.assertEqual(len(remembered), 1)
        self.assertTrue(remembered[0].startswith("ACTION INCERTAINE:"))

    def test_visible_bets_are_reconstructed_as_raise_then_call(self):
        fields = {
            "top_left_name": "Open",
            "top_left_bet": "2,5 BB",
            "top_right_name": "Caller",
            "top_right_bet": "2,5 BB",
            "hero_bet": "1 BB",
        }
        events, state = PokerTrackerApp._reconstruct_visible_bet_actions(
            fields,
            street="preflop",
            dealer_owner="right",
            previous={},
        )
        self.assertEqual([event[2] for event in events], ["Open raises 2.5 BB", "Caller calls 2.5 BB"])
        self.assertEqual(state["top_right"], 2.5)

    def test_visible_bet_increase_is_a_raise_and_is_not_repeated(self):
        fields = {
            "right_name": "Aggro",
            "right_bet": "8 BB",
            "left_name": "Opener",
            "left_bet": "3 BB",
        }
        events, state = PokerTrackerApp._reconstruct_visible_bet_actions(
            fields,
            street="preflop",
            dealer_owner="top_left",
            previous={"left": 3.0},
        )
        self.assertEqual([event[2] for event in events], ["Aggro raises 8 BB"])
        repeated, _state = PokerTrackerApp._reconstruct_visible_bet_actions(
            fields,
            street="preflop",
            dealer_owner="top_left",
            previous=state,
        )
        self.assertEqual(repeated, [])

    def test_postflop_first_contribution_is_a_bet_and_all_in_is_kept(self):
        fields = {
            "left_name": "Shove",
            "left_bet": "12 BB",
            "left_status": "all-in",
        }
        events, _state = PokerTrackerApp._reconstruct_visible_bet_actions(
            fields,
            street="flop",
            dealer_owner="hero",
            previous={},
        )
        self.assertEqual(events[0][2], "Shove bets 12 BB and is all-in")

    def test_large_contribution_with_disappeared_stack_is_inferred_all_in(self):
        fields = {
            "right_name": "Shove",
            "right_bet": "94 BB",
            "right_stack": "",
            "hero_bet": "1 BB",
        }
        events, _state = PokerTrackerApp._reconstruct_visible_bet_actions(
            fields,
            street="preflop",
            dealer_owner="top_right",
            previous={},
        )
        self.assertEqual(events[0][2], "Shove raises 94 BB and is all-in")

    def test_explicit_seat_fold_and_check_are_reconstructed(self):
        fields = {
            "top_left_name": "Folder",
            "top_left_action": "FOLD",
            "right_name": "Checker",
            "right_action": "CHECK",
        }
        events, _state = PokerTrackerApp._reconstruct_visible_bet_actions(
            fields,
            street="flop",
            dealer_owner="top_right",
            previous={},
        )
        self.assertEqual({event[2] for event in events}, {"Folder folds", "Checker checks"})

    def test_fuzzy_fold_requires_hidden_cards_as_second_signal(self):
        hidden = {
            "right_name": "Folder",
            "right_action": "Fron",
            "right_cards_visible": "not_visible",
        }
        visible = {**hidden, "right_cards_visible": "visible"}
        folded, _state = PokerTrackerApp._reconstruct_visible_bet_actions(
            hidden, street="flop", dealer_owner="hero", previous={}
        )
        active, _state = PokerTrackerApp._reconstruct_visible_bet_actions(
            visible, street="flop", dealer_owner="hero", previous={}
        )
        self.assertEqual(folded[0][2], "Folder folds")
        self.assertEqual(active, [])

    def test_raise_amount_can_come_from_seat_action_text(self):
        fields = {
            "left_name": "Raiser",
            "left_action": "RAISES TO 12,5 BB",
            "hero_bet": "2,5 BB",
        }
        events, _state = PokerTrackerApp._reconstruct_visible_bet_actions(
            fields,
            street="preflop",
            dealer_owner="right",
            previous={},
        )
        self.assertEqual(events[0][2], "Raiser raises 12.5 BB")

    def test_first_postflop_observation_only_infers_checks_before_hero(self):
        fields = {
            "top_left_name": "AfterHero",
            "top_left_cards_visible": "visible",
            "right_name": "BeforeHero",
            "right_cards_visible": "visible",
        }
        events, _state = PokerTrackerApp._reconstruct_visible_bet_actions(
            fields,
            street="flop",
            dealer_owner="top_right",
            previous={},
            infer_checks=True,
            first_observation=True,
        )
        self.assertEqual([event[2] for event in events], ["BeforeHero checks"])

    def test_later_postflop_observation_infers_all_unchanged_visible_checks(self):
        fields = {
            "top_left_name": "First",
            "top_left_cards_visible": "visible",
            "right_name": "Second",
            "right_cards_visible": "visible",
        }
        events, _state = PokerTrackerApp._reconstruct_visible_bet_actions(
            fields,
            street="turn",
            dealer_owner="top_right",
            previous={"top_left": 0.0, "right": 0.0},
            infer_checks=True,
            first_observation=False,
        )
        self.assertEqual({event[2] for event in events}, {"First checks", "Second checks"})

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

    def test_physical_board_count_survives_stabilization_with_unreadable_card(self):
        previous = MiniSnapshot({}, "", "preflop")
        current = MiniSnapshot(
            {"board_card_1": "7s", "board_card_2": "", "board_card_3": "5s", "board_visible_count": "3"},
            "7s 5s",
            "flop",
        )
        result = PokerTrackerApp._preserve_live_details(previous, current, same_hand=True)
        self.assertEqual(result.current_street, "flop")


if __name__ == "__main__":
    unittest.main()
