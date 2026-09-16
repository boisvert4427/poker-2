from __future__ import annotations

from collections import Counter
from itertools import combinations
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
        score = _score(list(combo) + board_cards)
        kind = score[0]
        if kind >= 5:
            label = "couleur+"
        elif kind == 4:
            label = "quinte"
        elif kind == 3:
            label = "brelan"
        elif kind == 2:
            label = "deux paires"
        elif kind == 1:
            pair_rank = score[1]
            if paired_board:
                label = "paire"
            elif pair_rank == board_values[0]:
                label = "top paire"
            elif len(board_values) > 1 and pair_rank == board_values[1]:
                label = "middle paire"
            else:
                label = "petite paire"
        else:
            label = "air / tirage"
        counts[label] += 1
    total = sum(counts.values())
    return {label: count / total for label, count in counts.items()} if total else {}


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
