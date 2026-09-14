from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re


CARD_RE = re.compile(r"\b(10|[2-9TJQKA])([shdc])\b", re.IGNORECASE)
RANK_VALUE = {rank: index + 2 for index, rank in enumerate("23456789TJQKA")}


@dataclass(frozen=True, slots=True)
class PostflopBaseline:
    action: str
    sizing: str
    mix: str
    reason: str


@dataclass(frozen=True, slots=True)
class BoardTexture:
    wetness: int
    label: str
    paired: bool
    monotone: bool


def recommend_postflop_baseline(
    *,
    board: str,
    street: str,
    strength_score: int,
    draws: list[str],
    facing_aggression: bool,
    opponent_count: int,
    in_position: bool,
    pot_type: str = "unknown",
    hero_was_preflop_aggressor: bool = False,
    spr: float | None = None,
    bet_fraction: float | None = None,
) -> PostflopBaseline:
    """Return a fast deterministic approximation of a 100 BB 5-max strategy."""
    texture = classify_board_texture(board)
    multiway = opponent_count >= 2
    street = (street or "flop").lower()
    has_draw = bool(draws) and street != "river"
    strong_draw = len(draws) >= 2
    shallow = spr is not None and spr <= 1.5
    deep = spr is not None and spr >= 6.0
    large_bet = bet_fraction is not None and bet_fraction >= 0.75

    if facing_aggression:
        if strength_score >= 5:
            return PostflopBaseline("RAISE", "2,5-3x la mise", "RAISE 75% / CALL 25%", "range de value tres forte")
        if strength_score >= 4:
            return PostflopBaseline("RAISE", "2,3-2,7x la mise", "RAISE 60% / CALL 40%", "main forte, protection et value")
        if strength_score >= 2:
            if shallow:
                return PostflopBaseline("CALL", "", "CALL 80% / RAISE 20%", "SPR faible : main faite proche de l'engagement")
            if multiway or texture.wetness >= 2:
                return PostflopBaseline("CALL", "", "CALL 65% / RAISE 35%", "main faite moyenne sur spot charge")
            return PostflopBaseline("CALL", "", "CALL 75% / RAISE 25%", "garder les bluffs adverses dans la range")
        if strong_draw:
            return PostflopBaseline("CALL", "", "CALL 65% / RAISE 35%", "tirage combine avec bonne equite")
        if has_draw:
            return PostflopBaseline("CALL", "", "CALL 60% / FOLD 30% / RAISE 10%", "tirage a defendre selon la cote")
        if strength_score == 1 and not multiway:
            if shallow and not large_bet:
                return PostflopBaseline("CALL", "", "CALL 70% / FOLD 30%", "SPR faible et mise non polarisante")
            mix = "CALL 55% / FOLD 45%" if in_position else "FOLD 55% / CALL 45%"
            if deep or large_bet:
                mix = "FOLD 70% / CALL 30%"
                return PostflopBaseline("FOLD", "", mix, "gros sizing ou SPR profond : defense resserree")
            return PostflopBaseline("CALL" if in_position else "FOLD", "", mix, "paire marginale : defense selon la cote")
        return PostflopBaseline("FOLD", "", "FOLD 95% / RAISE 5%", "bas de range sans equite suffisante")

    if strength_score >= 5:
        sizing = "70-90% du pot" if texture.wetness >= 2 else "55-70% du pot"
        return PostflopBaseline("BET", sizing, "BET 80% / CHECK 20%", "value tres forte")
    if strength_score >= 3:
        sizing = "65-80% du pot" if texture.wetness >= 2 else "50-65% du pot"
        return PostflopBaseline("BET", sizing, "BET 70% / CHECK 30%", "value et protection")
    if strength_score == 2:
        if multiway:
            return PostflopBaseline("CHECK", "", "CHECK 55% / BET 45%", "frequence de mise reduite en multiway")
        return PostflopBaseline("BET", "50-65% du pot", "BET 60% / CHECK 40%", "value moyenne")
    if strength_score == 1:
        if multiway or texture.wetness >= 2:
            return PostflopBaseline("CHECK", "", "CHECK 70% / BET 30%", "showdown value fragile")
        return PostflopBaseline("BET", "30-40% du pot", "BET 55% / CHECK 45%", "petite mise sur texture seche")
    if strong_draw:
        return PostflopBaseline("BET", "50-65% du pot", "BET 60% / CHECK 40%", "semi-bluff a forte equite")
    if has_draw:
        action = "BET" if in_position and not multiway else "CHECK"
        mix = "BET 50% / CHECK 50%" if action == "BET" else "CHECK 65% / BET 35%"
        return PostflopBaseline(action, "50-65% du pot" if action == "BET" else "", mix, "semi-bluff controle")
    if in_position and not multiway and texture.wetness <= 1:
        if hero_was_preflop_aggressor and pot_type in {"single_raised", "3bet"}:
            sizing = "25-35% du pot" if pot_type == "3bet" else "30-40% du pot"
            return PostflopBaseline("BET", sizing, "BET 60% / CHECK 40%", "c-bet de l'agresseur sur board sec")
        return PostflopBaseline("CHECK", "", "CHECK 65% / BET 35%", "air : bluff occasionnel sur board sec")
    return PostflopBaseline("CHECK", "", "CHECK 90% / BET 10%", "air ou spot multiway : abandon frequent")


def classify_board_texture(board: str) -> BoardTexture:
    cards = [(rank.upper().replace("10", "T"), suit.lower()) for rank, suit in CARD_RE.findall(board or "")]
    if not cards:
        return BoardTexture(0, "inconnue", False, False)
    values = sorted({RANK_VALUE[rank] for rank, _ in cards})
    suits = Counter(suit for _, suit in cards)
    ranks = Counter(rank for rank, _ in cards)
    paired = any(count >= 2 for count in ranks.values())
    monotone = max(suits.values(), default=0) >= 3
    two_tone = max(suits.values(), default=0) == 2
    connected = any(values[index + 1] - values[index] <= 2 for index in range(len(values) - 1))
    wetness = max(0, min(3, int(two_tone) + 2 * int(monotone) + int(connected) - int(paired)))
    label = "charge" if wetness >= 2 else "semi-connecte" if wetness == 1 else "sec"
    if paired:
        label += ", paire"
    if monotone:
        label += ", monotone"
    return BoardTexture(wetness, label, paired, monotone)
