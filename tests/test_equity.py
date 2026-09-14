from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from poker_tracker.equity import _combos
from poker_tracker.villain_db import get_player_profile, open_db


class EquityRangeTests(unittest.TestCase):
    def test_qq_plus_contains_only_qq_kk_aa(self):
        combos = _combos("QQ+", set())
        self.assertEqual(len(combos), 18)
        self.assertEqual({hand[0][0] + hand[1][0] for hand in combos}, {"QQ", "KK", "AA"})

    def test_k8s_plus_keeps_king_fixed(self):
        combos = _combos("K8s+", set())
        classes = {hand[0][0] + hand[1][0] for hand in combos}
        self.assertEqual(classes, {"K8", "K9", "KT", "KJ", "KQ"})
        self.assertEqual(len(combos), 20)

    def test_percentage_is_not_parsed_as_a_hand(self):
        self.assertEqual(_combos("range solide ~18-24%", set()), [])

    def test_malformed_connector_ladder_cannot_loop_forever(self):
        # The end point is unreachable when both ranks are decremented.  It
        # must still return promptly rather than blocking the live assistant.
        self.assertTrue(_combos("86s-54s", set()))

    def test_database_name_ignores_dot_and_space(self):
        with tempfile.TemporaryDirectory() as folder:
            connection = open_db(Path(folder) / "test.sqlite3")
            connection.execute("INSERT INTO players(name) VALUES (?)", ("Mule.7060863",))
            connection.execute(
                "INSERT INTO hands(hand_id, source_file) VALUES (?, ?)",
                ("hand-1", "test"),
            )
            connection.execute(
                "INSERT INTO hand_players(hand_id, player_name, seat_no, stack, is_hero) VALUES (?, ?, ?, ?, ?)",
                ("hand-1", "Mule.7060863", 1, 100, 0),
            )
            connection.commit()
            profile = get_player_profile(connection, "Mule 7060863")
            connection.close()
            self.assertIsNotNone(profile)
            self.assertEqual(profile["name"], "Mule.7060863")


if __name__ == "__main__":
    unittest.main()
