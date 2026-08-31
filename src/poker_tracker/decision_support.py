from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .villain_db import DEFAULT_DB_PATH, get_player_profile, open_db


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


@dataclass(slots=True)
class BluffAssessment:
    seat: str
    name: str
    score: float
    level: str
    reasons: list[str]


DEFAULT_UNKNOWN_PROFILE = {
    "hands_played": 0,
    "vpip": 0.24,
    "pfr": 0.18,
    "profile": "standard",
    "estimated_range": "range standard inconnue ~24-28%",
    "preflop_tendency": "profil normal par defaut, pas d'ecart exploitant fort",
    "note": "joueur inconnu, rester proche d'une range standard",
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
                )
            )
        return profiles
    finally:
        connection.close()


def estimate_range_from_stats(vpip: float, pfr: float, profile: str, hands_played: int) -> dict[str, str]:
    if hands_played < 10:
        return {
            "estimated_range": "range standard prudente ~22-28%",
            "preflop_tendency": "echantillon faible, eviter les gros ajustements",
            "note": "peu de mains, partir sur un profil normal",
        }
    if profile == "nit":
        return {
            "estimated_range": "range tres tight ~12-18%",
            "preflop_tendency": "ouvre et continue plutot fort, peu de calls marginaux",
            "note": "respecter davantage les relances et 3-bets",
        }
    if profile == "tag":
        return {
            "estimated_range": "range solide ~18-24%",
            "preflop_tendency": "joue proprement, aggression plutot legitime",
            "note": "profil reg standard, peu d'exces evidents",
        }
    if profile == "lag":
        return {
            "estimated_range": "range large et agressive ~28-40%",
            "preflop_tendency": "ouvre beaucoup, 3-bet/iso plus souvent",
            "note": "peut mettre de la pression avec des mains moyennes",
        }
    if profile == "loose_passive":
        return {
            "estimated_range": "range large passive ~35-50%",
            "preflop_tendency": "entre beaucoup dans les coups mais relance peu",
            "note": "value bet plus et bluffe moins",
        }
    return {
        "estimated_range": "range standard ~22-28%",
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
