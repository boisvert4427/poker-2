from __future__ import annotations

import unittest

from poker_tracker.gto_postflop import classify_board_texture, recommend_postflop_baseline


class GtoPostflopTests(unittest.TestCase):
    def test_monotone_connected_board_is_wet(self):
        texture = classify_board_texture("Qh Jh 8h")
        self.assertGreaterEqual(texture.wetness, 2)
        self.assertTrue(texture.monotone)

    def test_nut_hand_raises_against_a_bet(self):
        result = recommend_postflop_baseline(
            board="Qh Jh 2h",
            street="flop",
            strength_score=5,
            draws=[],
            facing_aggression=True,
            opponent_count=1,
            in_position=True,
        )
        self.assertEqual(result.action, "RAISE")
        self.assertIn("CALL", result.mix)

    def test_multiway_air_checks(self):
        result = recommend_postflop_baseline(
            board="Ah 8d 3c",
            street="flop",
            strength_score=0,
            draws=[],
            facing_aggression=False,
            opponent_count=3,
            in_position=False,
        )
        self.assertEqual(result.action, "CHECK")
        self.assertIn("90%", result.mix)

    def test_preflop_aggressor_c_bets_dry_three_bet_pot(self):
        result = recommend_postflop_baseline(
            board="Ah 8d 3c",
            street="flop",
            strength_score=0,
            draws=[],
            facing_aggression=False,
            opponent_count=1,
            in_position=True,
            pot_type="3bet",
            hero_was_preflop_aggressor=True,
            spr=3.5,
        )
        self.assertEqual(result.action, "BET")
        self.assertIn("25-35%", result.sizing)


if __name__ == "__main__":
    unittest.main()
