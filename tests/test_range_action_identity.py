import unittest
from dataclasses import replace

from poker_tracker.decision_support import VillainRangeProfile, _effective_villain_range
from poker_tracker.live_state import _aggressive_villain_seats


class RangeActionIdentityTests(unittest.TestCase):
    profile = VillainRangeProfile("right", "Caller", True, 50, .25, .18,
                                 "standard", "22+, A2s+, KTs+", "", "")

    def effective(self, actions, street="preflop", profile=None):
        return _effective_villain_range(profile or self.profile, street=street,
                                        recent_actions=actions, aggressive=True)

    def test_recorded_call_wins_over_equal_bet_inference(self):
        value, reason = self.effective(["Open raises 3.5 BB", "Caller calls 3.5 BB"])
        self.assertEqual(reason, "call")
        self.assertEqual(value, self.profile.estimated_range)

    def test_calling_all_in_does_not_become_a_raise(self):
        _, reason = self.effective(["Open raises 100 BB", "Caller calls 20 BB and is all-in"])
        self.assertEqual(reason, "call")

    def test_postflop_call_after_raise_updates_range(self):
        _, reason = self.effective(["Caller raises 3 BB", "Other bets 8 BB", "Caller calls 8 BB"], "flop")
        self.assertTrue(reason.startswith("call postflop"))

    def test_player_name_is_not_a_substring_match(self):
        profile = replace(self.profile, name="Ann")
        _, reason = _effective_villain_range(profile, street="preflop",
                    recent_actions=["Anna raises 10 BB"], aggressive=False)
        self.assertEqual(reason, "range de participation")

    def test_equal_bets_do_not_identify_multiple_raisers(self):
        self.assertEqual(_aggressive_villain_seats(
            {"left_bet": "3.5 BB", "right_bet": "3.5 BB", "hero_bet": "1 BB"},
            ["left", "right", "hero"]), [])

    def test_big_blind_is_not_a_raise_but_postflop_bet_is(self):
        fields = {"right_bet": "1 BB", "hero_bet": ""}
        self.assertEqual(_aggressive_villain_seats(fields, ["right", "hero"], street="preflop"), [])
        self.assertEqual(_aggressive_villain_seats(fields, ["right", "hero"], street="flop"), ["right"])
