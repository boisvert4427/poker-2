"""Independent slow reference for the board filter's original semantics."""
import random
import unittest
from collections import Counter
from poker_tracker.equity import (
    RANKS, SUITS, RANK_VALUE, _cards, _combos, _score,
    filter_range_on_board,
)


def reference_filter(prior, candidate, board, hero):
    cards, hole = _cards(board), _cards(hero)
    dead = set(cards + hole)
    accepted = set(_combos(candidate, dead))
    classes = set()
    for hand in _combos(prior, dead):
        all_cards = list(hand) + cards
        made = hand[0][0] == hand[1][0] or any(c[0] in {b[0] for b in cards} for c in hand)
        made = made or _score(all_cards)[0] >= 4
        draw = False
        if len(cards) < 5:
            suits = Counter(c[1] for c in all_cards)
            draw = any(count == 4 and any(c[1] == suit for c in hand) for suit, count in suits.items())
            values = {RANK_VALUE[c[0]] for c in all_cards}
            holes = {RANK_VALUE[c[0]] for c in hand}
            if 14 in values:
                values.add(1)
            if 14 in holes:
                holes.add(1)
            draw = draw or any(len(values & set(range(low, low + 5))) == 4
                and bool((holes - {RANK_VALUE[c[0]] for c in cards}) & set(range(low, low + 5)))
                for low in range(1, 11))
        if hand in accepted or made or draw:
            a, b = sorted((hand[0][0], hand[1][0]), key=RANK_VALUE.get, reverse=True)
            classes.add(a + b + ("" if a == b else "s" if hand[0][1] == hand[1][1] else "o"))
    return ", ".join(sorted(classes)) if classes else None


def scenarios():
    rng = random.Random(20260930)
    deck = [r + s for r in RANKS for s in SUITS]
    for count in (3, 4, 5):
        for _ in range(12):
            cards = rng.sample(deck, count + 2)
            yield "22+, A2s+, K2s+, Q2s+, J2s+, A2o+, K2o+, 98s-54s", "88+, ATs+, KQs, AJo+", " ".join(cards[:count]), " ".join(cards[count:])


class RangeFilterOptimizationTests(unittest.TestCase):
    def test_identical_to_original_filter_without_cache(self):
        for args in scenarios():
            with self.subTest(board=args[2], hero=args[3]):
                self.assertEqual(filter_range_on_board.__wrapped__(*args), reference_filter(*args))

    def test_cache_does_not_change_results(self):
        args = next(scenarios())
        filter_range_on_board.cache_clear()
        self.assertEqual(filter_range_on_board(*args), filter_range_on_board(*args))
        self.assertEqual(filter_range_on_board.cache_info().hits, 1)
