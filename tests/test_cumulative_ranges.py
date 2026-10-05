import unittest

from poker_tracker.decision_support import VillainRangeProfile, _cumulative_villain_range, _effective_villain_range
from poker_tracker.equity import _combos, intersect_range_texts, filter_range_on_board


class CumulativeRangeTests(unittest.TestCase):
    def test_small_set_survives_generic_premium_filter(self):
        text = filter_range_on_board("22, AA", "AA", "2h 9d Kc", "Qs Jc")
        self.assertIn("22", text)

    def test_flush_draw_retained_before_river_not_after(self):
        before = filter_range_on_board("QJs, AA", "AA", "Kh 8h 2c", "Ts 9d")
        after = filter_range_on_board("QJs, AA", "AA", "Kh 8h 2c 3d 9s", "Ts 9d")
        self.assertIn("QJs", before)
        self.assertNotIn("QJs", after)

    def test_straight_draw_survives(self):
        self.assertIn("65s", filter_range_on_board("65s, AA", "AA", "7h 8d 2c", "Qs Jc"))

    def test_board_filter_cannot_add_outside_prior(self):
        text = filter_range_on_board("22, QJs", "AA, KK, QJs", "Kh 8h 2c", "Ts 9d")
        self.assertTrue(set(_combos(text, set())) <= set(_combos("22, QJs", set())))

    profile = VillainRangeProfile("right", "Player", True, 100, .25, .18,
                                  "standard", "22+, A2s+, KTs+, QTs+, ATo+", "", "")

    def event(self, phase, action, seat="right"):
        return {"street": phase, "seat": seat, "action": action,
                "raw": f"Player {action}s", "confidence": .98}

    def result(self, events, street="turn", actions=None):
        return _cumulative_villain_range(self.profile, street=street,
            recent_actions=actions or ["Player checks"], aggressive=False, action_events=events)

    def test_raise_then_check_retains_preflop_range(self):
        result, reason = self.result([self.event("preflop", "raise"), self.event("turn", "check")])
        expected, _ = _effective_villain_range(self.profile, street="preflop", recent_actions=["Player raises"], aggressive=False)
        self.assertEqual(set(_combos(result, set())), set(_combos(expected, set())))
        self.assertIn("preflop:raise", reason)

    def test_raise_then_call_never_reintroduces_excluded_hands(self):
        before, _ = self.result([self.event("preflop", "raise")])
        after, _ = self.result([self.event("preflop", "raise"), self.event("flop", "call")])
        self.assertTrue(set(_combos(after, set())) <= set(_combos(before, set())))
        self.assertTrue(_combos(after, set()))

    def test_no_future_events_or_other_players(self):
        events = [self.event("river", "raise"), self.event("preflop", "raise", "left")]
        self.assertEqual(self.result(events)[1], "range de participation")

    def test_new_hand_empty_journal_resets_range(self):
        self.assertEqual(self.result([])[0], self.profile.estimated_range)

    def test_low_confidence_events_not_applied(self):
        event = self.event("preflop", "raise")
        event["confidence"] = .3
        self.assertEqual(self.result([event])[1], "range de participation")

    def test_intersection_suited_unsuited_and_empty(self):
        self.assertEqual(intersect_range_texts("AK", "AKs"), "AKs")
        self.assertIsNone(intersect_range_texts("AA", "22"))
        self.assertIsNone(intersect_range_texts("illisible", "AA"))

    def test_duplicate_events_are_idempotent(self):
        event = self.event("preflop", "raise")
        a, _ = self.result([event])
        b, _ = self.result([event, event])
        self.assertEqual(set(_combos(a, set())), set(_combos(b, set())))
