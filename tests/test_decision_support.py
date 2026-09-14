from __future__ import annotations

from dataclasses import replace
import unittest

from poker_tracker.decision_support import VillainRangeProfile, recommend_action
from poker_tracker.live_state import (
    _decision_amounts,
    _effective_stack_bb,
    _hero_is_in_position,
    _position_for_seat,
    _preflop_decision_context,
)
from poker_tracker.parser import ParsedHand


PROFILE = VillainRangeProfile(
    seat="right",
    name="VilainTest",
    known=True,
    hands_played=50,
    vpip=0.22,
    pfr=0.16,
    profile="tag",
    estimated_range="33+, A4s+, K9s+, QTs+, JTs, T9s, A9o+, KTo+, QJo (~18-24%)",
    preflop_tendency="standard",
    note="",
)


class DecisionSupportTests(unittest.TestCase):
    def recommend(self, **overrides):
        values = {
            "hero_cards": "Ah As",
            "board": "",
            "street": "preflop",
            "available_actions": ["FOLD", "CALL", "RAISE"],
            "recent_actions": ["VilainTest raises 0.06"],
            "villain_profiles": [PROFILE],
            "players_in_hand": ["right", "hero"],
            "is_hero_turn": True,
        }
        values.update(overrides)
        return recommend_action(**values)

    def test_premium_pair_raises_preflop(self):
        result = self.recommend()
        self.assertEqual(result.action, "RAISE")
        self.assertEqual(result.sizing, "3 BB preflop")

    def test_made_flush_raises_against_bet(self):
        result = self.recommend(
            hero_cards="Ah Kh",
            board="Qh Jh 2h",
            street="flop",
            available_actions=["FOLD", "CALL", "RAISE"],
            recent_actions=["VilainTest bets 0.10"],
        )
        self.assertEqual(result.hand_strength, "couleur")
        self.assertEqual(result.action, "RAISE")

    def test_no_recommendation_outside_hero_turn(self):
        result = self.recommend(is_hero_turn=False)
        self.assertEqual(result.action, "ATTENDRE")
        self.assertEqual(result.confidence, 0.0)

    def test_equity_metrics_do_not_erase_a_value_raise(self):
        second = VillainRangeProfile(
            seat="left", name="VilainDeux", known=False, hands_played=0,
            vpip=0.24, pfr=0.18, profile="standard",
            estimated_range="22+, A2s+, K8s+, Q9s+, J9s+, T9s, A8o+, KTo+, QTo+, JTo (~25%)",
            preflop_tendency="standard", note="",
        )
        result = self.recommend(
            hero_cards="8c 8d",
            villain_profiles=[PROFILE, second],
            players_in_hand=["right", "left", "hero"],
            pot_size=10.0,
            call_amount=2.0,
        )
        self.assertEqual(result.action, "RAISE")
        self.assertEqual(result.opponent_count, 2)
        self.assertAlmostEqual(result.pot_odds or 0.0, 1 / 6)
        self.assertIsNotNone(result.equity)

    def test_call_button_can_never_produce_check(self):
        result = self.recommend(
            hero_cards="7c 2d",
            board="Ah Kd Qs",
            street="flop",
            available_actions=["FOLD", "CALL", "RAISE"],
            pot_size=None,
            call_amount=None,
        )
        self.assertNotEqual(result.action, "CHECK")

    def test_villain_all_in_cannot_produce_a_raise_recommendation(self):
        result = self.recommend(
            hero_cards="Ah As",
            available_actions=["FOLD", "CALL", "RAISE"],
            recent_actions=["VilainTest raises 20 to 20 and is all-in"],
            pot_size=30.0,
            call_amount=20.0,
        )
        self.assertIn(result.action, {"CALL", "FOLD"})
        self.assertNotEqual(result.action, "RAISE")

    def test_incomplete_action_bar_never_invents_raise(self):
        result = self.recommend(available_actions=["FOLD"], recent_actions=[])
        self.assertEqual(result.action, "ATTENDRE")

    def test_all_in_with_a_readable_call_uses_call_fold_math(self):
        result = self.recommend(
            hero_cards="Kh Qh",
            available_actions=["FOLD", "CALL"],
            recent_actions=["VilainTest raises 8.50 to 8.52 and is all-in"],
            pot_size=12.0,
            call_amount=8.5,
        )
        self.assertIn(result.action, {"CALL", "FOLD"})
        self.assertNotEqual(result.action, "ATTENDRE")

    def test_no_active_villain_blocks_recommendation(self):
        result = self.recommend(players_in_hand=["hero"])
        self.assertEqual(result.action, "ATTENDRE")
        self.assertEqual(result.opponent_count, 0)

    def test_call_button_amount_has_priority_over_bet_difference(self):
        pot, call = _decision_amounts(
            {"hero_bet": "1 BB", "right_bet": "20 BB"},
            ["right", "hero"],
            "Pot total : 15 BB",
            "6 BB CALL",
        )
        self.assertEqual(pot, 15.0)
        self.assertEqual(call, 6.0)

    def test_preflop_aggressor_uses_pfr_range(self):
        result = self.recommend(aggressive_seats=["right"])
        self.assertTrue(result.villain_ranges)
        self.assertIn("88+", result.villain_ranges[0])
        self.assertIn("raise/3-bet", result.villain_ranges[0])

    def test_kj_calls_one_big_blind_in_a_limped_five_max_pot(self):
        result = self.recommend(
            hero_cards="Kh Js",
            recent_actions=["VilainTest calls 1 BB"],
            pot_size=2.5,
            call_amount=1.0,
        )
        self.assertEqual(result.action, "CALL")

    def test_gto_baseline_isolates_kj_from_button(self):
        result = self.recommend(
            hero_cards="Kh Js",
            recent_actions=["VilainTest calls 1 BB"],
            pot_size=2.5,
            call_amount=1.0,
            hero_position="BTN",
        )
        self.assertEqual(result.action, "RAISE")
        self.assertIn("isolation", " ".join(result.reasons))

    def test_gto_baseline_folds_weak_utg_hand(self):
        result = self.recommend(
            hero_cards="7h 2s",
            recent_actions=[],
            available_actions=["FOLD", "RAISE"],
            hero_position="UTG",
        )
        self.assertEqual(result.action, "FOLD")

    def test_hero_position_is_derived_from_dealer(self):
        self.assertEqual(_position_for_seat("hero", "hero"), "BTN")
        self.assertEqual(_position_for_seat("hero", "right"), "SB")
        self.assertEqual(_position_for_seat("hero", "left"), "CO")

    def test_postflop_position_accounts_for_active_button(self):
        self.assertFalse(_hero_is_in_position(["hero", "left"], "left"))
        self.assertTrue(_hero_is_in_position(["hero", "right"], "left"))

    def test_preflop_context_detects_three_bet_and_aggressor(self):
        hand = ParsedHand(
            big_blind=0.02,
            streets={
                "pre_flop": [
                    "Caller calls 0.02",
                    "Raiser raises 0.04 to 0.06",
                    "RougeLion raises 0.12 to 0.18",
                ]
            },
        )
        context = _preflop_decision_context(
            hand,
            {"right_name": "Raiser"},
            "left",
            "RougeLion",
        )
        self.assertEqual(context["pot_type"], "3bet")
        self.assertEqual(context["aggressor"], "RougeLion")
        self.assertTrue(context["hero_is_aggressor"])
        self.assertAlmostEqual(float(context["raise_size_bb"]), 9.0)
        self.assertEqual(context["limper_count"], 1)

    def test_effective_stack_targets_current_aggressor(self):
        value = _effective_stack_bb(
            {"hero_stack": "99 BB", "right_stack": "35 BB", "left_stack": "80 BB"},
            ["hero", "right", "left"],
            ["right"],
        )
        self.assertEqual(value, 35.0)

    def test_profiled_fold_rate_can_enable_a_profitable_bluff(self):
        folding_villain = replace(
            PROFILE,
            profile="nit",
            vpip=0.20,
            postflop_faced_bets=24,
            fold_to_bet=0.75,
            call_vs_bet=0.25,
        )
        result = self.recommend(
            hero_cards="7c 2d",
            board="Ah 8d 3c",
            street="flop",
            available_actions=["CHECK", "BET"],
            recent_actions=["VilainTest checks"],
            villain_profiles=[folding_villain],
            players_in_hand=["right", "hero"],
            hero_position="BTN",
            hero_in_position=True,
            pot_size=10.0,
        )
        self.assertEqual(result.action, "BET")
        self.assertIsNotNone(result.bluff_success_probability)
        self.assertGreater(
            result.bluff_success_probability or 0.0,
            result.bluff_break_even_probability or 1.0,
        )
        self.assertGreater(result.bluff_ev_bb or 0.0, 0.0)

    def test_calling_station_profile_increases_value_bet_call_estimate(self):
        calling_station = replace(
            PROFILE,
            profile="loose_passive",
            vpip=0.48,
            pfr=0.10,
            postflop_faced_bets=30,
            fold_to_bet=0.20,
            call_vs_bet=0.70,
        )
        result = self.recommend(
            hero_cards="Ah 8h",
            board="As 8d 3c",
            street="flop",
            available_actions=["CHECK", "BET"],
            recent_actions=["VilainTest checks"],
            villain_profiles=[calling_station],
            players_in_hand=["right", "hero"],
            hero_position="BTN",
            hero_in_position=True,
            pot_size=10.0,
        )
        self.assertEqual(result.action, "BET")
        self.assertGreater(result.value_call_probability or 0.0, 0.60)
        self.assertIsNotNone(result.value_equity_when_called)
        self.assertIsNotNone(result.value_ev_bb)


if __name__ == "__main__":
    unittest.main()
