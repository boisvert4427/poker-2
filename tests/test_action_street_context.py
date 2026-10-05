import unittest

from poker_tracker.app import PokerTrackerApp
from poker_tracker.live_state import _actions_for_street
from poker_tracker.decision_support import _effective_villain_range, VillainRangeProfile


class ActionStreetContextTests(unittest.TestCase):
    def test_old_aggression_not_current_street_pressure(self):
        events = [
            {"street": "preflop", "raw": "Player raises 10 BB"},
            {"street": "flop", "raw": "Player bets 8 BB"},
            {"street": "turn", "raw": "Player checks"},
        ]
        actions = _actions_for_street(events, "turn")
        self.assertEqual(actions, ["Player checks"])
        self.assertEqual(len(events), 3)
        profile = VillainRangeProfile("right", "Player", True, 50, .25, .18,
                                      "standard", "22+, A2s+, KTs+", "", "")
        _, reason = _effective_villain_range(profile, street="turn", recent_actions=actions, aggressive=False)
        self.assertEqual(reason, "range de participation")

    def test_new_street_has_no_invented_action(self):
        self.assertEqual(_actions_for_street([{"street": "flop", "raw": "Player bets 8 BB"}], "turn"), [])

    def test_fold_with_remaining_chips_is_not_a_new_bet(self):
        fields = {"right_name": "Player", "right_bet": "3 BB", "right_action": "FOLD",
                  "right_cards_visible": "not_visible"}
        events, state = PokerTrackerApp._reconstruct_visible_bet_actions(
            fields, street="flop", dealer_owner="left", previous={})
        self.assertEqual([e[2] for e in events], ["Player folds"])
        self.assertEqual(state["right"], 3)

    def test_fold_label_contradicted_by_card_backs_is_not_confirmed(self):
        fields = {"right_name": "Player", "right_action": "FOLD", "right_cards_visible": "visible"}
        events, _ = PokerTrackerApp._reconstruct_visible_bet_actions(
            fields, street="flop", dealer_owner="left", previous={})
        self.assertEqual(events, [])
