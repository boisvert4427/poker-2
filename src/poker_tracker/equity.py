from __future__ import annotations

from collections import Counter
from itertools import combinations
from functools import lru_cache
import random
import re

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VALUE = {rank: index + 2 for index, rank in enumerate(RANKS)}
CARD_RE = re.compile(r"\b(10|[2-9TJQKA])([shdc])\b", re.IGNORECASE)
RANGE_RE = re.compile(
    r"(?<![A-Za-z0-9])[2-9TJQKA]{2}[so]?(?:\+|-[2-9TJQKA]{2}[so]?)?(?![A-Za-z0-9%])"
)


def estimate_multiway_equity(hero_cards: str, board: str, ranges: list[str], simulations: int = 700) -> float | None:
    hero, board_cards = _cards(hero_cards), _cards(board)
    dead = set(hero + board_cards)
    if len(hero) != 2 or len(board_cards) > 5 or len(dead) != len(hero) + len(board_cards) or not ranges:
        return None
    pools = [_combos(text, dead) for text in ranges]
    if any(not pool for pool in pools):
        return None
    rng = random.Random("|".join(sorted(dead) + ranges))
    deck = [r + s for r in RANKS for s in SUITS if r + s not in dead]
    won, completed = 0.0, 0
    for _ in range(simulations):
        used, hands = set(dead), []
        for pool in pools:
            available = [hand for hand in pool if not set(hand) & used]
            if not available:
                break
            hand = rng.choice(available)
            hands.append(hand)
            used.update(hand)
        if len(hands) != len(pools):
            continue
        runout = rng.sample([card for card in deck if card not in used], 5 - len(board_cards))
        final_board = board_cards + runout
        scores = [_score(hero + final_board)] + [_score(list(hand) + final_board) for hand in hands]
        best = max(scores)
        if scores[0] == best:
            won += 1 / scores.count(best)
        completed += 1
    return won / completed if completed else None


def range_hand_distribution(range_text: str, board: str, hero_cards: str = "") -> dict[str, float]:
    """Break a compatible opponent range into current postflop hand classes."""
    board_cards = _cards(board)
    dead = set(board_cards + _cards(hero_cards))
    if len(board_cards) < 3 or len(dead) != len(board_cards) + len(_cards(hero_cards)):
        return {}
    combos = _combos(range_text, dead)
    if not combos:
        return {}
    board_values = sorted((RANK_VALUE[card[0]] for card in board_cards), reverse=True)
    paired_board = len(set(board_values)) != len(board_values)
    counts: Counter[str] = Counter()
    for combo in combos:
        counts[_hand_category(combo, board_cards, board_values, paired_board)] += 1
    total = sum(counts.values())
    return {label: count / total for label, count in counts.items()} if total else {}


def multiway_hand_distributions(
    ranges: list[str], board: str, hero_cards: str = "", simulations: int = 2500,
) -> tuple[list[dict[str, float]], dict[str, float]]:
    """Sample all villain hands jointly, including card removal."""
    board_cards = _cards(board)
    hero = _cards(hero_cards)
    dead = set(board_cards + hero)
    if len(board_cards) < 3 or len(dead) != len(board_cards) + len(hero) or not ranges:
        return [], {}
    if len(ranges) == 1:
        one = range_hand_distribution(ranges[0], board, hero_cards)
        top = one.get("top paire", 0.0)
        return [one], {"at_least_one_top_pair": top, "all_top_pair": top}
    pools = [_combos(text, dead) for text in ranges]
    if any(not pool for pool in pools):
        return [], {}
    board_values = sorted((RANK_VALUE[card[0]] for card in board_cards), reverse=True)
    paired_board = len(set(board_values)) != len(board_values)
    counts = [Counter() for _ in ranges]
    at_least_one = all_top = completed = attempts = 0
    rng = random.Random("joint|" + "|".join(sorted(dead) + ranges))
    while completed < simulations and attempts < simulations * 8:
        attempts += 1
        hands = [rng.choice(pool) for pool in pools]
        flat = [card for hand in hands for card in hand]
        if len(set(flat)) != len(flat):
            continue
        labels = [_hand_category(hand, board_cards, board_values, paired_board) for hand in hands]
        for counter, label in zip(counts, labels):
            counter[label] += 1
        top_count = labels.count("top paire")
        at_least_one += int(top_count >= 1)
        all_top += int(top_count == len(labels))
        completed += 1
    if not completed:
        return [], {}
    return (
        [{label: count / completed for label, count in counter.items()} for counter in counts],
        {"at_least_one_top_pair": at_least_one / completed, "all_top_pair": all_top / completed},
    )


def _hand_category(
    combo: tuple[str, str], board_cards: list[str], board_values: list[int], paired_board: bool,
) -> str:
    score = _score(list(combo) + board_cards)
    kind = score[0]
    if kind >= 5: return "couleur+"
    if kind == 4: return "quinte"
    if kind == 3: return "brelan"
    if kind == 2: return "deux paires"
    if kind == 1:
        pair_rank = score[1]
        if paired_board: return "paire"
        if pair_rank == board_values[0]: return "top paire"
        if len(board_values) > 1 and pair_rank == board_values[1]: return "middle paire"
        return "petite paire"
    return "air / tirage"


def _cards(text: str) -> list[str]:
    return [rank.upper().replace("10", "T") + suit.lower() for rank, suit in CARD_RE.findall(text or "")]


def _combos(text: str, dead: set[str]) -> list[tuple[str, str]]:
    classes = set()
    for token in RANGE_RE.findall((text or "").split("(", 1)[0].replace(" ", "")):
        classes.update(_expand(token))
    result = []
    for high, low, kind in classes:
        if high == low:
            suit_pairs = combinations(SUITS, 2)
        else:
            suit_pairs = ((a, b) for a in SUITS for b in SUITS if not (kind == "s" and a != b) and not (kind == "o" and a == b))
        for a, b in suit_pairs:
            hand = (high + a, low + b)
            if not set(hand) & dead:
                result.append(hand)
    return result


@lru_cache(maxsize=256)
def filter_range_on_board(prior: str, candidate: str, board: str, hero_cards: str = "") -> str | None:
    """Keep prior classes supported by made hands/draws, not only profile ranks.

    Class-level approximation: retaining one suited combo retains its class.
    Never adds classes outside prior and never treats a river draw as live.
    """
    cards, hero = _cards(board), _cards(hero_cards)
    if len(cards) not in {3, 4, 5} or len(set(cards + hero)) != len(cards + hero):
        return intersect_range_texts(prior, candidate)
    dead = set(cards + hero)
    accepted = set(_combos(candidate, dead))
    classes = set()
    board_ranks = {c[0] for c in cards}
    board_values = {RANK_VALUE[c[0]] for c in cards}
    straight_windows = tuple(frozenset(range(low, low + 5)) for low in range(1, 11))
    for hand in _combos(prior, dead):
        a, b = sorted((hand[0][0], hand[1][0]), key=RANK_VALUE.get, reverse=True)
        kind = "" if a == b else "s" if hand[0][1] == hand[1][1] else "o"
        hand_class = a + b + kind
        # Output is class-level: once one compatible combo retains a class,
        # evaluating its other suit combinations cannot change the result.
        if hand_class in classes:
            continue
        if hand in accepted or a == b or a in board_ranks or b in board_ranks:
            classes.add(hand_class)
            continue
        all_cards = list(hand) + cards
        # Made straights and flushes, including non-pair holdings.
        if _score(all_cards)[0] >= 4:
            classes.add(hand_class)
            continue
        draw = False
        if len(cards) < 5:
            suits = Counter(c[1] for c in all_cards)
            draw = any(count == 4 and any(c[1] == suit for c in hand)
                       for suit, count in suits.items())
            values = {RANK_VALUE[c[0]] for c in all_cards}
            hole_values = {RANK_VALUE[c[0]] for c in hand}
            if 14 in values:
                values.add(1)
            if 14 in hole_values:
                hole_values.add(1)
            draw = draw or any(len(values & window) == 4
                               and bool((hole_values - board_values) & window)
                               for window in straight_windows)
        if draw:
            classes.add(hand_class)
    return ", ".join(sorted(classes)) if classes else None


def intersect_range_texts(left: str, right: str) -> str | None:
    """Intersect supported hand classes, without percentages or dead cards.

    None means empty/unparseable: callers must retain their last hypothesis
    rather than silently replace it with a random or unrestricted range.
    """
    def classes(text: str) -> set[tuple[str, str, str]]:
        result = set()
        for token in RANGE_RE.findall(text.split("(", 1)[0].replace(" ", "")):
            for high, low, kind in _expand(token):
                kinds = (kind,) if kind or high == low else ("s", "o")
                result.update((high, low, k) for k in kinds)
        return result
    common = classes(left) & classes(right)
    if not common:
        return None
    ordered = sorted(common, key=lambda c: (RANK_VALUE[c[0]], RANK_VALUE[c[1]], c[2]), reverse=True)
    return ", ".join("".join(item) for item in ordered)


def _expand(token: str) -> set[tuple[str, str, str]]:
    if "-" in token:
        start, end = token.split("-", 1)
        kind = start[-1] if start[-1] in "so" else ""
        high, low, end_high, end_low = start[0], start[1], end[0], end[1]
        result = set()
        # A connector ladder can contain at most twelve entries.  The bound
        # also makes malformed notation such as ``86s-54s`` harmless instead
        # of letting an OCR/profile typo lock the live assistant forever.
        for _ in range(len(RANKS)):
            result.add((high, low, kind))
            if (high, low) == (end_high, end_low):
                return result
            if high == "2" or low == "2":
                break
            high = RANKS[RANKS.index(high) - 1]
            low = RANKS[RANKS.index(low) - 1]
        return result
    plus = token.endswith("+")
    token = token.rstrip("+")
    kind = token[-1] if token[-1] in "so" else ""
    high, low = token[0], token[1]
    if not plus:
        return {(high, low, kind)}
    if high == low:
        return {(rank, rank, "") for rank in RANKS[RANKS.index(high):]}
    # Standard range notation keeps the first rank fixed: K8s+ means
    # K8s, K9s, KTs, KJs and KQs. Connector ladders use an explicit range
    # such as 98s-65s and are handled above.
    return {(high, rank, kind) for rank in RANKS[RANKS.index(low):RANKS.index(high)]}


def _score(cards: list[str]) -> tuple[int, ...]:
    return max(_five(combo) for combo in combinations(cards, 5))


def _five(cards: tuple[str, ...]) -> tuple[int, ...]:
    values = sorted((RANK_VALUE[c[0]] for c in cards), reverse=True)
    counts = Counter(values)
    groups = sorted(((count, value) for value, count in counts.items()), reverse=True)
    unique = sorted(set(values), reverse=True)
    straight = 5 if unique == [14, 5, 4, 3, 2] else (unique[0] if len(unique) == 5 and unique[0] - unique[-1] == 4 else 0)
    flush = len({c[1] for c in cards}) == 1
    if flush and straight: return (8, straight)
    if groups[0][0] == 4: return (7, groups[0][1], groups[1][1])
    if groups[0][0] == 3 and groups[1][0] == 2: return (6, groups[0][1], groups[1][1])
    if flush: return (5, *values)
    if straight: return (4, straight)
    if groups[0][0] == 3: return (3, groups[0][1], *sorted((v for v in values if v != groups[0][1]), reverse=True))
    pairs = sorted((value for count, value in groups if count == 2), reverse=True)
    if len(pairs) == 2: return (2, *pairs, max(v for v in values if v not in pairs))
    if len(pairs) == 1: return (1, pairs[0], *sorted((v for v in values if v != pairs[0]), reverse=True))
    return (0, *values)
