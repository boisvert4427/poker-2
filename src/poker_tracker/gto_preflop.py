from __future__ import annotations

from dataclasses import dataclass
import re

from .equity import RANGE_RE, RANK_VALUE, _expand


@dataclass(frozen=True, slots=True)
class PreflopBaseline:
    action: str
    sizing: str
    reason: str


# Aggressive 100 BB 5-max opening baseline.  The ranges deliberately widen
# with position: stealing late is profitable and preserves initiative.
RFI_RANGES = {
    "UTG": "22+, A2s+, K8s+, Q9s+, J9s+, T8s+, 98s-65s, A9o+, KTo+, QTo+, JTo",
    "CO": "22+, A2s+, K5s+, Q7s+, J7s+, T7s+, 97s+, 86s+, 75s+, 65s, A5o+, K9o+, Q9o+, J9o+, T9o",
    "BTN": "22+, A2s+, K2s+, Q3s+, J5s+, T6s+, 96s+, 86s+, 75s+, 65s, A2o+, K5o+, Q7o+, J7o+, T8o+, 98o",
    "SB": "22+, A2s+, K2s+, Q4s+, J6s+, T6s+, 96s+, 86s+, 75s+, 65s, A2o+, K6o+, Q8o+, J8o+, T8o+, 98o",
}

ISO_RAISE_RANGE = "22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 98s-65s, A8o+, KTo+, QTo+, JTo"
OVER_LIMP_RANGE = "22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 97s+, 86s+, 75s+, 65s, A2o+, K7o+, Q8o+, J8o+, T9o"
VS_RAISE_CALL_RANGE = "88+, AJs+, KQs, AQo+"
VS_RAISE_RERAISE_RANGE = "QQ+, AKs, AKo"
VS_EARLY_RAISE_CALL_RANGE = "88+, AJs+, KQs, AQo+"
VS_LATE_RAISE_CALL_RANGE = "66+, A9s+, KTs+, QTs+, JTs, ATo+, KQo"
BTN_VS_SMALL_OPEN_CALL_RANGE = "55+, A8s+, KTs+, QTs+, JTs, T9s, ATo+, KQo"


def recommend_preflop_baseline(
    hero_cards: str,
    position: str,
    spot: str,
    *,
    raiser_position: str = "",
    effective_stack_bb: float | None = None,
    limper_count: int = 1,
    raise_size_bb: float | None = None,
    caller_count: int = 0,
) -> PreflopBaseline | None:
    position = (position or "").upper()
    if position not in {"UTG", "CO", "BTN", "SB", "BB"}:
        return None

    if spot == "unopened":
        if position == "BB":
            return PreflopBaseline("CHECK", "", "BB : aucun supplément à payer")
        if _in_range(hero_cards, RFI_RANGES[position]):
            return PreflopBaseline("RAISE", "2,5 BB", f"base 5-max 100 BB : ouverture {position}")
        return PreflopBaseline("FOLD", "", f"hors range d'ouverture {position}")

    if spot == "limped":
        if _in_range(hero_cards, ISO_RAISE_RANGE):
            iso_size = 4.0 + max(0, limper_count - 1)
            return PreflopBaseline("RAISE", f"{iso_size:g} BB", f"isolation de {max(1, limper_count)} limp(s) en 5-max")
        if _in_range(hero_cards, OVER_LIMP_RANGE):
            return PreflopBaseline("CALL", "", "overlimp autorisé par la base 5-max")
        return PreflopBaseline("FOLD", "", "main trop faible même contre un limp")

    if spot == "raised":
        if effective_stack_bb is not None and effective_stack_bb <= 25 and _in_range(hero_cards, VS_RAISE_RERAISE_RANGE):
            return PreflopBaseline("RAISE", "ALL-IN", "stack effectif court : 3-bet all-in de value")
        if _in_range(hero_cards, VS_RAISE_RERAISE_RANGE):
            return PreflopBaseline("RAISE", "3x la relance", "range de 3-bet value 100 BB")
        defense_range = (
            VS_EARLY_RAISE_CALL_RANGE if raiser_position in {"UTG", "CO"}
            else VS_LATE_RAISE_CALL_RANGE if raiser_position in {"BTN", "SB"}
            else VS_RAISE_CALL_RANGE
        )
        oversized = raise_size_bb is not None and raise_size_bb >= 4.0
        small_open = raise_size_bb is None or raise_size_bb <= 2.5
        # A small pair on the button can profitably enter a *single-raised*
        # multiway pot when stacks are deep: position and implied odds make
        # set-mining worthwhile.  This deliberately does not apply to a
        # 3-bet pot (represented by a large raise_size) or shallow stacks.
        set_mine = (
            position == "BTN"
            and _is_small_pair(hero_cards)
            and caller_count >= 1
            and (raise_size_bb is None or raise_size_bb <= 3.0)
            and (effective_stack_bb is None or effective_stack_bb >= 60.0)
        )
        if set_mine:
            return PreflopBaseline("CALL", "", "petite paire au BTN : call multiway en position, cote implicite")
        # The live hand history can arrive one action late, leaving the
        # raiser's position temporarily unknown.  In the requested aggressive
        # BTN profile, defend position against a normal small open rather than
        # folding hands such as ATo to the generic early-position range.
        if position == "BTN" and small_open and raiser_position not in {"UTG", "CO"} and _in_range(hero_cards, BTN_VS_SMALL_OPEN_CALL_RANGE):
            return PreflopBaseline("CALL", "", "BTN agressif : defense en position contre petit open")
        if _in_range(hero_cards, defense_range) and not oversized:
            return PreflopBaseline("CALL", "", "range de défense contre une relance")
        if oversized and _in_range(hero_cards, VS_EARLY_RAISE_CALL_RANGE):
            return PreflopBaseline("CALL", "", "defense resserree contre une grosse relance")
        return PreflopBaseline("FOLD", "", "hors range de défense contre relance")
    return None


def _in_range(hero_cards: str, notation: str) -> bool:
    cards = re.findall(r"(10|[2-9TJQKA])([shdc])", (hero_cards or "").replace("10", "T"), re.IGNORECASE)
    if len(cards) != 2:
        return False
    (rank_a, suit_a), (rank_b, suit_b) = cards
    rank_a, rank_b = rank_a.upper(), rank_b.upper()
    if RANK_VALUE[rank_b] > RANK_VALUE[rank_a]:
        rank_a, rank_b = rank_b, rank_a
        suit_a, suit_b = suit_b, suit_a
    kind = "" if rank_a == rank_b else ("s" if suit_a.lower() == suit_b.lower() else "o")
    hand_class = (rank_a, rank_b, kind)
    classes = set()
    for token in RANGE_RE.findall(notation.replace(" ", "")):
        classes.update(_expand(token))
    return hand_class in classes


def _is_small_pair(hero_cards: str) -> bool:
    """Return true for pocket deuces through pocket sevens.

    The range parser intentionally supports the common ``22+`` syntax, but
    not the compact pair interval ``22-77``.  This rule needs that precise
    interval, so keep it explicit instead of silently widening it to 22+.
    """
    cards = re.findall(r"(10|[2-9TJQKA])([shdc])", (hero_cards or "").replace("10", "T"), re.IGNORECASE)
    if len(cards) != 2:
        return False
    first, second = cards[0][0].upper(), cards[1][0].upper()
    return first == second and first in {"2", "3", "4", "5", "6", "7"}
