from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
import re
from typing import Iterable

from .villain_db import DEFAULT_DB_PATH, get_player_profile, open_db
from .equity import estimate_multiway_equity
from .gto_preflop import recommend_preflop_baseline
from .gto_postflop import classify_board_texture, recommend_postflop_baseline


# Current calibration and live logic target a five-seat table only.
TABLE_MAX_PLAYERS = 5


@dataclass(slots=True)
class VillainRangeProfile:
    seat: str
    name: str
    known: bool
    hands_played: int
    vpip: float
    pfr: float
    profile: str
    estimated_range: str
    preflop_tendency: str
    note: str
    postflop_faced_bets: int = 0
    fold_to_bet: float | None = None
    call_vs_bet: float | None = None


@dataclass(slots=True)
class BluffAssessment:
    seat: str
    name: str
    score: float
    level: str
    reasons: list[str]


@dataclass(slots=True)
class BluffPlan:
    success_probability: float
    break_even_probability: float
    ev_bb: float | None
    summary: str
    viable: bool


@dataclass(slots=True)
class ValuePlan:
    call_probability: float
    equity_when_called: float | None
    ev_bb: float | None
    summary: str


@dataclass(slots=True)
class DecisionRecommendation:
    action: str
    sizing: str
    confidence: float
    hand_strength: str
    villain_range: str
    summary: str
    reasons: list[str]
    equity: float | None = None
    pot_odds: float | None = None
    call_amount: float | None = None
    opponent_count: int = 0
    villain_ranges: list[str] = field(default_factory=list)
    strategy_mix: str = ""
    effective_stack_bb: float | None = None
    spr: float | None = None
    pot_type: str = "unknown"
    preflop_aggressor: str = ""
    bluff_success_probability: float | None = None
    bluff_break_even_probability: float | None = None
    bluff_ev_bb: float | None = None
    bluff_summary: str = ""
    value_call_probability: float | None = None
    value_equity_when_called: float | None = None
    value_ev_bb: float | None = None
    value_summary: str = ""


DEFAULT_UNKNOWN_PROFILE = {
    "hands_played": 0,
    "vpip": 0.24,
    "pfr": 0.18,
    "profile": "standard",
    "estimated_range": "22+, A2s+, K8s+, Q9s+, J9s+, T9s, A8o+, KTo+, QTo+, JTo (~24-28%)",
    "preflop_tendency": "joueur inconnu : hypothese neutre, pas une calling station",
    "note": "pas assez de mains pour attribuer un profil ; rester proche d'une range standard",
}


def build_villain_profiles(
    detected_fields: dict[str, str],
    *,
    db_path: str | None = None,
) -> list[VillainRangeProfile]:
    seats = [
        ("top_left", detected_fields.get("top_left_name", "")),
        ("top_right", detected_fields.get("top_right_name", "")),
        ("left", detected_fields.get("left_name", "")),
        ("right", detected_fields.get("right_name", "")),
    ]

    connection = open_db(db_path or DEFAULT_DB_PATH)
    try:
        profiles: list[VillainRangeProfile] = []
        for seat, player_name in seats:
            if not player_name:
                continue
            stats = get_player_profile(connection, player_name)
            if stats is None:
                profiles.append(
                    VillainRangeProfile(
                        seat=seat,
                        name=player_name,
                        known=False,
                        hands_played=DEFAULT_UNKNOWN_PROFILE["hands_played"],
                        vpip=DEFAULT_UNKNOWN_PROFILE["vpip"],
                        pfr=DEFAULT_UNKNOWN_PROFILE["pfr"],
                        profile=DEFAULT_UNKNOWN_PROFILE["profile"],
                        estimated_range=DEFAULT_UNKNOWN_PROFILE["estimated_range"],
                        preflop_tendency=DEFAULT_UNKNOWN_PROFILE["preflop_tendency"],
                        note=DEFAULT_UNKNOWN_PROFILE["note"],
                    )
                )
                continue

            range_info = estimate_range_from_stats(stats["vpip"], stats["pfr"], stats["profile"], stats["hands_played"])
            profiles.append(
                VillainRangeProfile(
                    seat=seat,
                    name=player_name,
                    known=True,
                    hands_played=int(stats["hands_played"]),
                    vpip=float(stats["vpip"]),
                    pfr=float(stats["pfr"]),
                    profile=str(stats["profile"]),
                    estimated_range=range_info["estimated_range"],
                    preflop_tendency=range_info["preflop_tendency"],
                    note=range_info["note"],
                    postflop_faced_bets=int(stats.get("postflop_faced_bets", 0) or 0),
                    fold_to_bet=stats.get("fold_to_bet"),
                    call_vs_bet=stats.get("call_vs_bet"),
                )
            )
        return profiles
    finally:
        connection.close()


def estimate_range_from_stats(vpip: float, pfr: float, profile: str, hands_played: int) -> dict[str, str]:
    if hands_played < 10:
        return {
            "estimated_range": "22+, A2s+, K8s+, Q9s+, J9s+, T9s, A8o+, KTo+, QTo+, JTo (~22-28%)",
            "preflop_tendency": "echantillon faible, eviter les gros ajustements",
            "note": "peu de mains, partir sur un profil normal",
        }
    if profile == "nit":
        return {
            "estimated_range": "55+, A8s+, KTs+, QTs+, JTs, ATo+, KQo (~12-18%)",
            "preflop_tendency": "ouvre et continue plutot fort, peu de calls marginaux",
            "note": "respecter davantage les relances et 3-bets",
        }
    if profile == "tag":
        return {
            "estimated_range": "33+, A4s+, K9s+, QTs+, JTs, T9s, A9o+, KTo+, QJo (~18-24%)",
            "preflop_tendency": "joue proprement, aggression plutot legitime",
            "note": "profil reg standard, peu d'exces evidents",
        }
    if profile == "lag":
        return {
            "estimated_range": "22+, A2s+, K5s+, Q7s+, J8s+, T8s+, 98s-65s, A2o+, K8o+, Q9o+, J9o+ (~28-40%)",
            "preflop_tendency": "ouvre beaucoup, 3-bet/iso plus souvent",
            "note": "peut mettre de la pression avec des mains moyennes",
        }
    if profile == "loose_passive":
        return {
            "estimated_range": "22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 97s+, 87s-54s, A2o+, K7o+, Q8o+, J8o+, T9o (~35-50%)",
            "preflop_tendency": "calling station / loose-passive : entre beaucoup, call souvent, relance peu",
            "note": "range large : value bet plus, bluffe moins",
        }
    return {
        "estimated_range": "22+, A2s+, K8s+, Q9s+, J9s+, T9s, A8o+, KTo+, QTo+, JTo (~22-28%)",
        "preflop_tendency": "profil neutre sans lecture forte",
        "note": "joueur standard par defaut",
    }


def format_villain_profiles(profiles: Iterable[VillainRangeProfile]) -> str:
    items = list(profiles)
    if not items:
        return "-"
    lines = []
    for profile in items:
        source = "connu" if profile.known else "defaut"
        lines.append(
            f"{profile.seat} {profile.name} | {profile.profile} | "
            f"VPIP {profile.vpip:.3f} PFR {profile.pfr:.3f} | "
            f"{profile.estimated_range} | {source}"
        )
    return "\n".join(lines)


def format_villain_ranges(profiles: Iterable[VillainRangeProfile]) -> str:
    items = list(profiles)
    if not items:
        return "-"
    lines = []
    for profile in items:
        source = "BDD" if profile.known else "defaut"
        lines.append(
            f"{profile.seat} {profile.name} : {profile.estimated_range} | "
            f"tendance {profile.preflop_tendency} | {source}"
        )
    return "\n".join(lines)


def assess_bluff_risk(
    profiles: Iterable[VillainRangeProfile],
    *,
    street: str,
    available_actions: list[str],
    players_in_hand: list[str],
    pot_text: str,
) -> list[BluffAssessment]:
    items = list(profiles)
    results: list[BluffAssessment] = []
    street_key = (street or "").lower()
    action_set = {action.upper() for action in available_actions}

    for profile in items:
        score = 0.0
        reasons: list[str] = []

        if profile.profile == "lag":
            score += 0.35
            reasons.append("profil lag, aggression preflop elevee")
        elif profile.profile == "loose_passive":
            score -= 0.15
            reasons.append("profil loose passive, moins de bluffs agressifs naturels")
        elif profile.profile == "nit":
            score -= 0.30
            reasons.append("profil nit, bluffs moins frequents")
        elif profile.profile == "tag":
            score -= 0.05
            reasons.append("profil tag, line plutot value par defaut")
        else:
            score += 0.05
            reasons.append("profil standard ou inconnu")

        if profile.known and profile.hands_played >= 20 and profile.vpip >= 0.32 and profile.pfr >= 0.22:
            score += 0.15
            reasons.append("stats larges et agressives confirmees")
        elif profile.known and profile.hands_played >= 20 and profile.vpip <= 0.18 and profile.pfr <= 0.14:
            score -= 0.10
            reasons.append("stats serrees, range plus value heavy")

        if street_key == "river":
            score += 0.20
            reasons.append("river : spot plus polarise, bluff possible")
        elif street_key == "turn":
            score += 0.10
            reasons.append("turn : pression intermediaire possible")
        elif street_key == "flop":
            score += 0.05
            reasons.append("flop : c-bet ou stab possibles")

        if len(players_in_hand) <= 2 and street_key in {"turn", "river"}:
            score += 0.10
            reasons.append("peu de joueurs en course, line plus souvent polarisee")

        if {"BET", "RAISE", "ALL-IN"} & action_set:
            score += 0.10
            reasons.append("ligne agressive detectee")
        elif {"CHECK", "CALL"} & action_set:
            score -= 0.05
            reasons.append("ligne plus passive a cet instant")

        if pot_text:
            score += 0.02
            reasons.append("pot visible, spot actionnable")

        score = max(0.0, min(1.0, score))
        if score >= 0.65:
            level = "fort"
        elif score >= 0.4:
            level = "moyen"
        else:
            level = "faible"

        results.append(
            BluffAssessment(
                seat=profile.seat,
                name=profile.name,
                score=round(score, 2),
                level=level,
                reasons=reasons[:4],
            )
        )

    return results


def format_bluff_assessments(items: Iterable[BluffAssessment]) -> str:
    values = list(items)
    if not values:
        return "-"
    lines = []
    for item in values:
        reason_text = "; ".join(item.reasons) if item.reasons else "-"
        lines.append(f"{item.seat} {item.name} : bluff {item.level} ({item.score:.2f}) | {reason_text}")
    return "\n".join(lines)


CARD_TOKEN_RE = re.compile(r"\b(10|[2-9TJQKA])([shdc])\b", re.IGNORECASE)
RANK_VALUE = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
              "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}


def recommend_action(
    *,
    hero_cards: str,
    board: str,
    street: str,
    available_actions: list[str],
    recent_actions: list[str],
    villain_profiles: Iterable[VillainRangeProfile],
    players_in_hand: list[str],
    is_hero_turn: bool = True,
    pot_size: float | None = None,
    call_amount: float | None = None,
    aggressive_seats: list[str] | None = None,
    free_big_blind_names: list[str] | None = None,
    hero_position: str = "",
    hero_in_position: bool | None = None,
    effective_stack_bb: float | None = None,
    spr: float | None = None,
    pot_type: str = "unknown",
    preflop_aggressor: str = "",
    preflop_aggressor_position: str = "",
    hero_was_preflop_aggressor: bool = False,
    limper_count: int = 0,
    raise_size_bb: float | None = None,
) -> DecisionRecommendation:
    """Return a conservative, explainable rule-based poker recommendation."""
    active_seats = set(players_in_hand)
    profiles = [p for p in villain_profiles if p.seat in active_seats]
    primary = profiles[0] if profiles else None
    effective_ranges = [
        _effective_villain_range(
            item,
            street=street,
            recent_actions=recent_actions,
            aggressive=item.seat in set(aggressive_seats or []),
            free_big_blind=_name_key(item.name) in {_name_key(name) for name in (free_big_blind_names or [])},
        )
        for item in profiles
    ]
    range_text = effective_ranges[0][0] if effective_ranges else DEFAULT_UNKNOWN_PROFILE["estimated_range"]
    range_lines = [
        f"{profile.name} ({profile.seat}) : {range_value} [{line}]"
        for profile, (range_value, line) in zip(profiles, effective_ranges)
    ]
    known_sample = bool(primary and primary.known and primary.hands_played >= 20)
    confidence = 0.72 if known_sample else 0.52
    actions = {action.upper() for action in available_actions}
    preflop_raise_seen = any(
        token in action.lower()
        for action in recent_actions
        for token in (" raises ", " bets ", " all-in", " all in")
    )
    cheap_limp_call = (
        (street or "preflop").lower() == "preflop"
        and "CALL" in actions
        and call_amount is not None
        and call_amount <= 1.0
        and not preflop_raise_seen
    )
    # The first displayed villain is not necessarily the player who shoved.
    # Read the last action on the street globally, otherwise an all-in from a
    # player on the other side of the table can be mistaken for an unopened
    # pot and produce a nonsensical raise recommendation.
    facing_all_in = _facing_all_in(recent_actions)
    facing_aggression = _facing_aggression(recent_actions, "") or ("CALL" in actions and not cheap_limp_call)
    profile = primary.profile if primary else "standard"
    reasons: list[str] = []
    equity = estimate_multiway_equity(
        hero_cards,
        board,
        [item[0] for item in effective_ranges],
    ) if profiles and "CALL" in actions else None
    pot_odds = (
        call_amount / (pot_size + call_amount)
        if call_amount is not None and call_amount > 0 and pot_size is not None and pot_size >= 0
        else None
    )

    if not is_hero_turn:
        return DecisionRecommendation(
            action="ATTENDRE",
            sizing="",
            confidence=0.0,
            hand_strength="analyse en attente du tour hero",
            villain_range=range_text,
            summary="ATTENDRE — ce n'est pas le tour du hero.",
            reasons=["aucun bouton d'action hero actif"],
            villain_ranges=range_lines,
        )

    if not profiles:
        return DecisionRecommendation(
            action="ATTENDRE",
            sizing="",
            confidence=0.0,
            hand_strength="adversaires actifs incertains",
            villain_range="-",
            summary="ATTENDRE - aucun adversaire actif detecte avec certitude.",
            reasons=["calcul bloque pour eviter une equite contre les mauvais joueurs"],
            opponent_count=0,
        )

    if (street or "preflop").lower() == "preflop" or not board.strip():
        tier, strength, preflop_reasons = _preflop_strength(hero_cards)
        reasons.extend(preflop_reasons)
        if primary:
            reasons.append(f"{primary.name}: {range_text}")
        spot = (
            "limped" if cheap_limp_call or pot_type == "limped"
            else "raised" if facing_aggression or pot_type in {"single_raised", "3bet"}
            else "unopened"
        )
        baseline = recommend_preflop_baseline(
            hero_cards,
            hero_position,
            spot,
            raiser_position=preflop_aggressor_position,
            effective_stack_bb=effective_stack_bb,
            limper_count=limper_count,
            raise_size_bb=raise_size_bb,
        )
        if baseline is not None:
            action, sizing = baseline.action, baseline.sizing
            reasons.insert(0, baseline.reason)
        elif tier >= 4:
            action, sizing = "RAISE", "3 BB preflop"
        elif tier == 3:
            action, sizing = ("CALL", "") if facing_aggression and profile == "nit" else ("RAISE", "3 BB preflop")
        elif tier == 2:
            if cheap_limp_call:
                action, sizing = "CALL", ""
                reasons.append("KJ/broadway : compléter 1 BB dans un pot limpé 5-max")
            elif facing_aggression:
                action, sizing = ("FOLD", "") if profile in {"nit", "tag"} else ("CALL", "")
            else:
                action, sizing = "CHECK" if "CHECK" in actions else "RAISE", "" if "CHECK" in actions else "2,5-3 BB"
        else:
            action, sizing = ("FOLD", "") if facing_aggression else ("CHECK", "")
        if facing_all_in:
            if "CALL" in actions and call_amount is not None:
                action, sizing = "CALL", ""
                reasons.insert(0, "all-in adverse detecte : decision limitee a call ou fold")
            else:
                action, sizing = "ATTENDRE", ""
                reasons.insert(0, "all-in adverse detecte, mais montant/bouton CALL illisible")
        preferred_action = action
        action = _legal_action(action, actions, facing_aggression)
        if action != preferred_action:
            sizing = ""
        summary = f"{action}{' ' + sizing if sizing else ''} — {strength}."
        result = DecisionRecommendation(action, sizing, confidence, strength, range_text, summary, reasons[:5])
        result.strategy_mix = f"{action} 100%"
        _set_decision_context(result, effective_stack_bb, spr, pot_type, preflop_aggressor)
        return _apply_call_math(result, actions, equity, pot_odds, call_amount, len(profiles), range_lines)

    strength_score, strength, draws, postflop_reasons = _postflop_strength(hero_cards, board)
    reasons.extend(postflop_reasons)
    if primary:
        reasons.append(f"{primary.name}: {range_text}")
    texture = classify_board_texture(board)
    baseline = recommend_postflop_baseline(
        board=board,
        street=street,
        strength_score=strength_score,
        draws=draws,
        facing_aggression=facing_aggression,
        opponent_count=len(profiles),
        in_position=hero_in_position if hero_in_position is not None else hero_position in {"BTN", "CO"},
        pot_type=pot_type,
        hero_was_preflop_aggressor=hero_was_preflop_aggressor,
        spr=spr,
        bet_fraction=(call_amount / pot_size if call_amount is not None and pot_size else None),
    )
    action, sizing = baseline.action, baseline.sizing
    strategy_mix = baseline.mix
    # Explicit exploit: a confirmed calling station is paid by worse hands
    # often enough that made hands should value bet more boldly.  Conversely,
    # one thin pair has little reason to bet into a confirmed nit that mostly
    # continues with strong hands.
    confirmed_calling_station = any(
        profile.profile == "loose_passive" and profile.known and profile.hands_played >= 10
        for profile in profiles
    )
    confirmed_tight = any(
        profile.profile == "nit" and profile.known and profile.hands_played >= 20
        for profile in profiles
    )
    if not facing_aggression and action == "BET" and strength_score >= 2 and confirmed_calling_station:
        sizing = "70-85% du pot" if strength_score >= 3 else "60-75% du pot"
        strategy_mix = "BET 80% / CHECK 20% exploit : value contre calling station"
        reasons.insert(0, "calling station confirmée : value bet plus cher avec main faite")
    elif not facing_aggression and action == "BET" and strength_score == 1 and not draws and confirmed_tight:
        action, sizing = "CHECK", ""
        strategy_mix = "CHECK 70% / BET 30% exploit : range tight"
        reasons.insert(0, "nit confirmé : contrôler une paire moyenne plutôt que value thin")
    bluff_plan = _estimate_bluff_plan(
        profiles,
        pot_size=pot_size,
        sizing=sizing if action == "BET" else "35-45% du pot",
        texture_wetness=texture.wetness,
        multiway=len(profiles) >= 2,
        candidate=(not facing_aggression and "BET" in actions and (strength_score == 0 or bool(draws))),
    )
    # Against an opponent who demonstrably folds too much, turn a normally
    # checked air hand into a small, explicit exploitative bluff.
    if (
        bluff_plan is not None
        and bluff_plan.viable
        and strength_score == 0
        and not draws
        and action == "CHECK"
        and any(profile.postflop_faced_bets >= 8 for profile in profiles)
    ):
        action, sizing = "BET", "35-45% du pot"
        strategy_mix = "BET 100% exploit : fold equity profilee"
        reasons.insert(0, "bluff exploitant retenu : probabilite de fold au-dessus du seuil rentable")
    value_plan = _estimate_value_plan(
        profiles,
        hero_cards=hero_cards,
        board=board,
        pot_size=pot_size,
        sizing=sizing,
        texture_wetness=texture.wetness,
        candidate=(not facing_aggression and action == "BET" and "BET" in actions and strength_score >= 1),
    )
    if value_plan is not None:
        reasons.insert(0, value_plan.summary)
    reasons.insert(0, f"base postflop 5-max : board {texture.label}; {baseline.reason}")
    context_reason = f"pot {pot_type or 'unknown'}"
    if spr is not None:
        context_reason += f", SPR {spr:.2f}"
    if preflop_aggressor:
        context_reason += f", agresseur {preflop_aggressor}"
    reasons.insert(1, context_reason)

    if facing_all_in:
        if "CALL" in actions and call_amount is not None:
            action, sizing = "CALL", ""
            reasons.insert(0, "all-in adverse detecte : decision limitee a call ou fold")
        else:
            action, sizing = "ATTENDRE", ""
            reasons.insert(0, "all-in adverse detecte, mais montant/bouton CALL illisible")
    preferred_action = action
    action = _legal_action(action, actions, facing_aggression)
    if action != preferred_action:
        sizing = ""
    if not hero_cards.strip():
        confidence = 0.0
        action, sizing = "ATTENDRE", ""
        reasons.insert(0, "cartes hero absentes ou illisibles")
    summary = f"{action}{' ' + sizing if sizing else ''} — {strength}."
    result = DecisionRecommendation(action, sizing, confidence, strength, range_text, summary, reasons[:5])
    result.strategy_mix = strategy_mix
    _set_decision_context(result, effective_stack_bb, spr, pot_type, preflop_aggressor)
    if bluff_plan is not None:
        result.bluff_success_probability = bluff_plan.success_probability
        result.bluff_break_even_probability = bluff_plan.break_even_probability
        result.bluff_ev_bb = bluff_plan.ev_bb
        result.bluff_summary = bluff_plan.summary
    if value_plan is not None:
        result.value_call_probability = value_plan.call_probability
        result.value_equity_when_called = value_plan.equity_when_called
        result.value_ev_bb = value_plan.ev_bb
        result.value_summary = value_plan.summary
    return _apply_call_math(result, actions, equity, pot_odds, call_amount, len(profiles), range_lines)


def _set_decision_context(
    result: DecisionRecommendation,
    effective_stack_bb: float | None,
    spr: float | None,
    pot_type: str,
    preflop_aggressor: str,
) -> None:
    result.effective_stack_bb = effective_stack_bb
    result.spr = spr
    result.pot_type = pot_type or "unknown"
    result.preflop_aggressor = preflop_aggressor


def _estimate_bluff_plan(
    profiles: list[VillainRangeProfile],
    *,
    pot_size: float | None,
    sizing: str,
    texture_wetness: int,
    multiway: bool,
    candidate: bool,
) -> BluffPlan | None:
    if not candidate or not profiles:
        return None
    bet_fraction = _sizing_fraction(sizing) or 0.40
    fold_probabilities = [
        _villain_fold_probability(profile, bet_fraction, texture_wetness)
        for profile in profiles
    ]
    success = 1.0
    for probability in fold_probabilities:
        success *= probability
    required = bet_fraction / (1.0 + bet_fraction)
    ev_bb = None
    if pot_size is not None and pot_size >= 0:
        bet_size = pot_size * bet_fraction
        ev_bb = success * pot_size - (1.0 - success) * bet_size
    target = " + ".join(profile.name for profile in profiles)
    sample_text = ", ".join(
        f"{profile.name}: {profile.postflop_faced_bets} spots"
        for profile in profiles
        if profile.postflop_faced_bets
    ) or "profils par defaut"
    summary = (
        f"fold equity estimee {success:.0%} contre {target}; "
        f"seuil {required:.0%}; {sample_text}"
    )
    if multiway:
        summary += "; probabilites multipliees en multiway"
    return BluffPlan(
        success_probability=success,
        break_even_probability=required,
        ev_bb=ev_bb,
        summary=summary,
        viable=success >= required + 0.04,
    )


def _villain_fold_probability(
    profile: VillainRangeProfile,
    bet_fraction: float,
    texture_wetness: int,
) -> float:
    prior = {
        "nit": 0.60,
        "tag": 0.50,
        "standard": 0.45,
        "lag": 0.40,
        "loose_passive": 0.34,
        "insufficient_data": 0.45,
    }.get(profile.profile, 0.45)
    sample = max(0, profile.postflop_faced_bets)
    if sample and profile.fold_to_bet is not None:
        # Bayesian smoothing: eight observed folds are useful, but never
        # enough to erase the population prior completely.
        observed = float(profile.fold_to_bet)
        probability = (observed * sample + prior * 20.0) / (sample + 20.0)
    else:
        probability = prior
    # VPIP is only an adjustment; actual fold/call observations above remain
    # the dominant input when available.
    probability -= (profile.vpip - 0.24) * 0.30
    if profile.call_vs_bet is not None and sample >= 8:
        probability -= max(0.0, float(profile.call_vs_bet) - 0.45) * 0.10
    probability += (bet_fraction - 0.50) * 0.12
    probability -= 0.04 * max(0, texture_wetness)
    return max(0.08, min(0.88, probability))


def _sizing_fraction(sizing: str) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)(?:\s*-\s*(\d+(?:[.,]\d+)?))?\s*%", sizing or "")
    if not match:
        return None
    low = float(match.group(1).replace(",", "."))
    high = float((match.group(2) or match.group(1)).replace(",", "."))
    return max(0.05, min(2.0, (low + high) / 200.0))


def _estimate_value_plan(
    profiles: list[VillainRangeProfile],
    *,
    hero_cards: str,
    board: str,
    pot_size: float | None,
    sizing: str,
    texture_wetness: int,
    candidate: bool,
) -> ValuePlan | None:
    if not candidate or not profiles:
        return None
    bet_fraction = _sizing_fraction(sizing) or 0.55
    individual_calls = [
        _villain_call_probability(profile, bet_fraction, texture_wetness)
        for profile in profiles
    ]
    at_least_one_call = 1.0
    for probability in individual_calls:
        at_least_one_call *= 1.0 - probability
    at_least_one_call = 1.0 - at_least_one_call
    calling_ranges = [_postflop_action_range(profile, action="call") for profile in profiles]
    # This is an explanatory value-bet estimate, not the main call/fold
    # calculation. A smaller deterministic sample keeps the live loop within
    # its latency budget while still distinguishing a thin value bet from a
    # clearly strong one.
    equity = (
        estimate_multiway_equity(hero_cards, board, calling_ranges, simulations=180)
        if calling_ranges
        else None
    )
    ev_bb = None
    if pot_size is not None and pot_size >= 0 and equity is not None:
        bet_size = pot_size * bet_fraction
        called_ev = equity * (pot_size + bet_size) - (1.0 - equity) * bet_size
        ev_bb = (1.0 - at_least_one_call) * pot_size + at_least_one_call * called_ev
    names = " + ".join(profile.name for profile in profiles)
    summary = f"value : call estime {at_least_one_call:.0%} contre {names}"
    if equity is not None:
        summary += f", equite vs range de call {equity:.0%}"
    return ValuePlan(at_least_one_call, equity, ev_bb, summary)


def _villain_call_probability(
    profile: VillainRangeProfile,
    bet_fraction: float,
    texture_wetness: int,
) -> float:
    prior = {
        "nit": 0.34,
        "tag": 0.42,
        "standard": 0.47,
        "lag": 0.52,
        "loose_passive": 0.60,
        "insufficient_data": 0.47,
    }.get(profile.profile, 0.47)
    sample = max(0, profile.postflop_faced_bets)
    if sample and profile.call_vs_bet is not None:
        probability = (float(profile.call_vs_bet) * sample + prior * 20.0) / (sample + 20.0)
    else:
        probability = prior
    probability += (profile.vpip - 0.24) * 0.30
    probability -= (bet_fraction - 0.50) * 0.18
    probability += 0.025 * max(0, texture_wetness)
    return max(0.08, min(0.90, probability))


def _apply_call_math(
    result: DecisionRecommendation,
    available_actions: set[str],
    equity: float | None,
    pot_odds: float | None,
    call_amount: float | None,
    opponent_count: int,
    villain_ranges: list[str],
) -> DecisionRecommendation:
    result.equity = equity
    result.pot_odds = pot_odds
    result.call_amount = call_amount
    result.opponent_count = opponent_count
    result.villain_ranges = villain_ranges
    if "CALL" not in available_actions:
        return result
    # Pot odds decide between calling and folding. They must never erase a
    # value raise/isolation already selected by the strategic baseline.
    if result.action in {"RAISE", "BET"}:
        if equity is not None and pot_odds is not None:
            result.reasons.insert(0, f"équité {equity:.1%}, cote de call {pot_odds:.1%}")
            result.reasons = result.reasons[:5]
        return result
    if equity is None or pot_odds is None:
        result.reasons.insert(0, "montant du call, pot ou range illisible: calcul de cote indisponible")
        if result.action in {"CHECK", "BET"}:
            result.action = "FOLD"
            result.sizing = ""
            result.summary = "FOLD - un call est requis mais la cote n'est pas calculable avec certitude."
        return result
    edge = equity - pot_odds
    result.action = "CALL" if edge >= 0.02 else "FOLD"
    result.strategy_mix = f"{result.action} 100% (cote calculee)"
    result.sizing = ""
    result.summary = f"{result.action} - equite {equity:.1%}, cote requise {pot_odds:.1%}."
    result.reasons.insert(0, f"equite multiway {equity:.1%} vs cote {pot_odds:.1%} (marge {edge:+.1%})")
    result.reasons = result.reasons[:5]
    return result


def _effective_villain_range(
    profile: VillainRangeProfile,
    *,
    street: str,
    recent_actions: list[str],
    aggressive: bool,
    free_big_blind: bool = False,
) -> tuple[str, str]:
    if free_big_blind:
        return (
            "Toute main (BB a checké dans un pot limpé, ≈100%)",
            "grosse blind : check gratuit, range non filtrée",
        )
    player_key = _name_key(profile.name)
    player_actions = [
        action.lower()
        for action in recent_actions
        if player_key and player_key in _name_key(action)
    ]
    raised = aggressive or any(
        token in action
        for action in player_actions
        for token in (" raises ", " bets ", " all-in", " all in")
    )
    called = any(" calls " in action for action in player_actions)
    preflop = (street or "preflop").lower() == "preflop"
    any_preflop_raise = any(
        token in action.lower()
        for action in recent_actions
        for token in (" raises ", " bets ", " all-in", " all in")
    )
    if (street or "preflop").lower() == "preflop" and raised:
        return _preflop_raise_range(profile), "raise/3-bet estime"
    if preflop and called and not any_preflop_raise:
        return (
            "22+, A2s+, K2s+, Q3s+, J5s+, T6s+, 96s+, 85s+, 75s+, 65s, A2o+, K6o+, Q7o+, J8o+, T8o+, 98o (~45-65%)",
            f"limp/call sans relance : range large en {TABLE_MAX_PLAYERS}-max",
        )
    if raised:
        if not preflop:
            return _postflop_action_range(profile, action="bet"), "mise/relance postflop : range resserrée"
        return profile.estimated_range, "agresseur postflop; range initiale"
    if called:
        if not preflop:
            return _postflop_action_range(profile, action="call"), "call postflop : paires et draws conservés"
        return profile.estimated_range, "call"
    return profile.estimated_range, "range de participation"


def _postflop_action_range(profile: VillainRangeProfile, *, action: str) -> str:
    """Action-adjusted 5-max range used for equity, before board blockers."""
    if action == "bet":
        if profile.profile == "nit":
            return "88+, ATs+, KQs, AJo+, KQo (~10-16%)"
        if profile.profile == "tag":
            return "55+, A8s+, KTs+, QTs+, JTs, ATo+, KQo (~16-24%)"
        if profile.profile in {"lag", "loose_passive"}:
            return "22+, A2s+, K6s+, Q8s+, J8s+, T8s+, 98s-65s, A7o+, KTo+, QTo+, JTo (~25-38%)"
        return "44+, A7s+, KTs+, QTs+, JTs, T9s, A9o+, KQo (~18-28%)"

    # A call retains more medium-strength showdown hands and draws than a bet.
    if profile.profile == "nit":
        return "55+, A8s+, KTs+, QTs+, JTs, ATo+, KQo (~16-24%)"
    if profile.profile == "tag":
        return "33+, A4s+, K9s+, QTs+, JTs, T9s, A9o+, KTo+, QJo (~22-32%)"
    if profile.profile in {"lag", "loose_passive"}:
        return "22+, A2s+, K3s+, Q6s+, J7s+, T7s+, 97s+, 87s-54s, A4o+, K8o+, Q9o+, J9o+, T9o (~35-50%)"
    return "22+, A2s+, K6s+, Q8s+, J9s+, T9s, 98s-65s, A7o+, KTo+, QTo+, JTo (~28-40%)"


def _preflop_raise_range(profile: VillainRangeProfile) -> str:
    # Do not freeze an observed raiser into the generic 12-16% range just
    # because the sample is young.  We shrink PFR toward a 5-max population
    # prior, so eight raises in eight hands widen the range materially without
    # pretending that eight hands are a conclusive read.
    sample = max(0, profile.hands_played)
    smoothed_pfr = (profile.pfr * sample + 0.18 * 20.0) / (sample + 20.0)
    uncertainty = " (echantillon court)" if sample < 20 else ""
    if smoothed_pfr <= 0.10:
        return "JJ+, AQs+, AKo (~5-7%)"
    if smoothed_pfr <= 0.16:
        return "88+, ATs+, KQs, AQo+ (~9-12%)"
    if smoothed_pfr <= 0.24:
        return "66+, A7s+, KTs+, QTs+, JTs, ATo+, KQo (~14-20%)"
    if smoothed_pfr <= 0.32:
        return "44+, A2s+, K9s+, QTs+, JTs, T9s, A9o+, KTo+, QJo (~20-28%)" + uncertainty
    return "22+, A2s+, K5s+, Q7s+, J8s+, T8s+, 98s-65s, A2o+, K8o+, Q9o+, J9o+ (~28-40%)" + uncertainty


def _name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def _cards(text: str) -> list[tuple[str, str]]:
    cards: list[tuple[str, str]] = []
    for rank, suit in CARD_TOKEN_RE.findall((text or "").replace("10", "T")):
        cards.append((rank.upper().replace("10", "T"), suit.lower()))
    return cards


def _preflop_strength(hero_cards: str) -> tuple[int, str, list[str]]:
    cards = _cards(hero_cards)
    if len(cards) != 2:
        return 0, "cartes hero inconnues", ["deux cartes hero nécessaires"]
    (r1, s1), (r2, s2) = cards
    v1, v2 = RANK_VALUE[r1], RANK_VALUE[r2]
    high, low = max(v1, v2), min(v1, v2)
    pair, suited, gap = v1 == v2, s1 == s2, abs(v1 - v2)
    reasons = [f"main {'paire' if pair else 'suited' if suited else 'offsuit'}"]
    if pair and high >= 11:
        return 4, "paire premium", reasons
    if pair and high >= 8:
        return 3, "paire forte", reasons
    if pair:
        return 2, "petite paire", reasons
    if high == 14 and low >= 11:
        return 4 if suited or low >= 12 else 3, "deux grosses cartes", reasons
    if high >= 13 and low >= 10:
        return 3 if suited else 2, "broadway", reasons
    if suited and high >= 10 and gap <= 2:
        return 3, "connecteurs hauts assortis", reasons
    if suited and gap <= 2:
        return 2, "connecteurs assortis", reasons
    if high == 14 and suited:
        return 2, "as assorti", reasons
    return 1, "main marginale", reasons


def _postflop_strength(hero_cards: str, board: str) -> tuple[int, str, list[str], list[str]]:
    hero = _cards(hero_cards)
    board_cards = _cards(board)
    cards = hero + board_cards
    if len(hero) != 2 or len(board_cards) < 3:
        return 0, "informations de cartes incomplètes", [], ["cartes insuffisantes"]
    rank_counts = Counter(RANK_VALUE[rank] for rank, _ in cards)
    suit_counts = Counter(suit for _, suit in cards)
    counts = sorted(rank_counts.values(), reverse=True)
    flush = max(suit_counts.values(), default=0) >= 5
    straight = _has_straight(set(rank_counts))
    if counts and counts[0] == 4:
        return 7, "carré", [], ["main faite très forte"]
    if counts[:2] >= [3, 2]:
        return 6, "full", [], ["main faite très forte"]
    if flush:
        return 5, "couleur", [], ["cinq cartes de la même couleur"]
    if straight:
        return 4, "quinte", [], ["cinq rangs consécutifs"]
    if counts and counts[0] == 3:
        return 3, "brelan", [], ["trois cartes du même rang"]
    pairs = sum(1 for count in counts if count == 2)
    if pairs >= 2:
        return 2, "deux paires", [], ["deux paires ou mieux"]
    draws: list[str] = []
    if max(suit_counts.values(), default=0) == 4:
        draws.append("tirage couleur")
    if _has_straight_draw(set(rank_counts)):
        draws.append("tirage quinte")
    if pairs == 1:
        return 1, "une paire", draws, ["paire détectée"] + draws
    return 0, "hauteur", draws, (["; ".join(draws)] if draws else ["aucune main faite"])


def _has_straight(values: set[int]) -> bool:
    expanded = set(values)
    if 14 in expanded:
        expanded.add(1)
    return any(all(value in expanded for value in range(start, start + 5)) for start in range(1, 11))


def _has_straight_draw(values: set[int]) -> bool:
    expanded = set(values)
    if 14 in expanded:
        expanded.add(1)
    return any(sum(value in expanded for value in range(start, start + 5)) >= 4 for start in range(1, 11))


def _facing_aggression(recent_actions: list[str], villain_name: str) -> bool:
    for line in reversed(recent_actions[-5:]):
        lowered = line.lower()
        if villain_name and villain_name.lower() not in lowered:
            continue
        if any(token in lowered for token in (" bets ", " raises ", " all-in", " all in")):
            return True
        if any(token in lowered for token in (" checks", " calls", " folds")):
            return False
    return False


def _facing_all_in(recent_actions: list[str]) -> bool:
    """True when the latest current-street line is a villain shove.

    ``recent_actions`` is restricted to the current street and this function
    only runs while the hero action bar is active, so an all-in here belongs to
    the opponent facing the hero rather than to an earlier hero action.
    """
    for line in reversed(recent_actions[-5:]):
        normalized = " ".join((line or "").lower().replace("-", " ").split())
        if "all in" in normalized:
            return True
        if any(token in normalized for token in (" checks", " calls", " folds")):
            return False
    return False


def _legal_action(preferred: str, available: set[str], facing_aggression: bool) -> str:
    if not available or preferred in available:
        return preferred
    aliases = {"BET": "RAISE", "RAISE": "BET"}
    if aliases.get(preferred) in available:
        return aliases[preferred]
    for candidate in (("CALL", "FOLD") if facing_aggression else ("CHECK", "BET")):
        if candidate in available:
            return candidate
    # One OCR word (usually only FOLD) is not a complete action bar.  Never
    # turn it into an invented raise or bet.
    return "ATTENDRE"
