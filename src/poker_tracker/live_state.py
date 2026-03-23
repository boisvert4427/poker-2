from __future__ import annotations

import re
from dataclasses import dataclass

from .detection import WinamaxWindow
from .history import HistoryFile, read_history_text
from .ocr import OcrSnapshot
from .parser import ParsedHand, parse_winamax_hand
from .visual import analyze_action_buttons


AMOUNT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
ACTION_TOKEN_RE = re.compile(r"\b(FOLD|CALL|CHECK|BET|RAISE|RAISES TO|ALL-IN)\b", re.IGNORECASE)
POT_RE = re.compile(r"\bPot\s*:\s*([\d.,]+)", re.IGNORECASE)
SIDEPOT_RE = re.compile(r"\bSide pots?\s*:\s*([^\n]+)", re.IGNORECASE)


@dataclass(slots=True)
class LiveHandSnapshot:
    source_file: str
    hand_id: str
    table_name: str
    hero_name: str
    hero_cards: str
    current_street: str
    is_complete: bool
    visible_board: str
    recent_actions: list[str]
    ocr_status: str
    ocr_preview: str
    inferred_amounts: list[str]
    window_title: str
    available_actions: list[str]
    pot_text: str
    hero_turn_confidence: float
    is_hero_turn: bool
    visual_buttons: list[str]


def build_live_snapshot(
    history_file: HistoryFile | None,
    window: WinamaxWindow | None,
    ocr_snapshot: OcrSnapshot | None,
) -> LiveHandSnapshot | None:
    if history_file is None:
        return None

    parsed = parse_winamax_hand(read_history_text(history_file.path))
    zone_text = _zone_text_map(ocr_snapshot)
    visual_states = analyze_action_buttons(ocr_snapshot.image_path) if ocr_snapshot and ocr_snapshot.image_path else []
    button_texts = [
        zone_text.get("action_left", ""),
        zone_text.get("action_center", ""),
        zone_text.get("action_right", ""),
    ]
    actions_text = "\n".join(part for part in button_texts if part.strip()) or zone_text.get("actions", "")
    pot_zone_text = zone_text.get("pot", "")
    hero_zone_text = zone_text.get("hero", "")
    merged_text = "\n".join(filter(None, [actions_text, pot_zone_text, hero_zone_text, ocr_snapshot.text if ocr_snapshot else ""]))

    return LiveHandSnapshot(
        source_file=history_file.path,
        hand_id=parsed.hand_id,
        table_name=parsed.table_name,
        hero_name=parsed.hero_name,
        hero_cards=parsed.hero_cards,
        current_street=_normalize_street(parsed),
        is_complete=parsed.is_complete,
        visible_board=_visible_board(parsed),
        recent_actions=_recent_actions(parsed),
        ocr_status=ocr_snapshot.status if ocr_snapshot else "not_run",
        ocr_preview=_ocr_preview(merged_text),
        inferred_amounts=_extract_amounts(merged_text),
        window_title=window.title if window else "",
        available_actions=_extract_actions(actions_text or merged_text),
        pot_text=_extract_pot_text(pot_zone_text or merged_text),
        hero_turn_confidence=_hero_turn_confidence(actions_text, hero_zone_text, merged_text, visual_states),
        is_hero_turn=_hero_turn_confidence(actions_text, hero_zone_text, merged_text, visual_states) >= 0.6,
        visual_buttons=[state.name for state in visual_states if state.active],
    )


def format_live_snapshot(snapshot: LiveHandSnapshot | None) -> str:
    if snapshot is None:
        return "Aucune main live disponible."

    lines = [
        f"Fenetre: {snapshot.window_title or '-'}",
        f"Source fichier: {snapshot.source_file}",
        f"Hand ID: {snapshot.hand_id or '-'}",
        f"Table: {snapshot.table_name or '-'}",
        f"Hero: {snapshot.hero_name or '-'} [{snapshot.hero_cards or '-'}]",
        f"Etat: {'terminee' if snapshot.is_complete else 'en cours'}",
        f"Street courante: {snapshot.current_street or '-'}",
        f"Board visible: {snapshot.visible_board or '-'}",
        f"Ton tour: {'oui' if snapshot.is_hero_turn else 'non'}",
        f"Confiance tour: {snapshot.hero_turn_confidence:.2f}",
        f"Pot OCR: {snapshot.pot_text or '-'}",
        f"OCR status: {snapshot.ocr_status}",
        f"Boutons visuels: {', '.join(snapshot.visual_buttons) if snapshot.visual_buttons else '-'}",
        "",
        "Actions recentes:",
    ]

    if snapshot.recent_actions:
        for action in snapshot.recent_actions:
            lines.append(f"  {action}")
    else:
        lines.append("  -")

    lines.extend(["", "Montants reperes via OCR:"])
    if snapshot.inferred_amounts:
        lines.append("  " + ", ".join(snapshot.inferred_amounts[:12]))
    else:
        lines.append("  -")

    lines.extend(["", "Actions OCR detectees:"])
    if snapshot.available_actions:
        lines.append("  " + ", ".join(snapshot.available_actions))
    else:
        lines.append("  -")

    lines.extend(["", "Apercu OCR:", snapshot.ocr_preview or "(vide)"])
    return "\n".join(lines)


def _normalize_street(hand: ParsedHand) -> str:
    if hand.current_street:
        return hand.current_street
    for street in ("river", "turn", "flop", "pre_flop", "ante_blinds"):
        if hand.streets.get(street):
            return street
    return ""


def _visible_board(hand: ParsedHand) -> str:
    for street in ("river", "turn", "flop"):
        value = hand.board_by_street.get(street)
        if value:
            return value
    return ""


def _recent_actions(hand: ParsedHand) -> list[str]:
    street = _normalize_street(hand)
    if not street:
        return []
    return hand.streets.get(street, [])[-6:]


def _ocr_preview(text: str) -> str:
    text = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return text[:400]


def _extract_amounts(text: str) -> list[str]:
    seen: list[str] = []
    for amount in AMOUNT_RE.findall(text):
        normalized = amount.replace(",", ".")
        if normalized not in seen:
            seen.append(normalized)
    return seen


def _extract_actions(text: str) -> list[str]:
    seen: list[str] = []
    normalized_text = text.replace("\n", " ")
    for token in ACTION_TOKEN_RE.findall(normalized_text):
        value = token.upper()
        if value not in seen:
            seen.append(value)
    return seen


def _extract_pot_text(text: str) -> str:
    match = POT_RE.search(text)
    if match:
        return match.group(1).replace(",", ".")
    sidepot_match = SIDEPOT_RE.search(text)
    if sidepot_match:
        return sidepot_match.group(1).strip()
    return ""


def _hero_turn_confidence(actions_text: str, hero_text: str, fallback_text: str, visual_states: list[object]) -> float:
    upper_actions = actions_text.upper()
    upper_hero = hero_text.upper()
    upper_all = fallback_text.upper()
    score = 0.0

    if "FOLD" in upper_actions or "FOLD" in upper_all:
        score += 0.35
    if "CALL" in upper_actions or "CHECK" in upper_actions or "CALL" in upper_all or "CHECK" in upper_all:
        score += 0.25
    if "RAISE" in upper_actions or "BET" in upper_actions or "RAISE" in upper_all or "BET" in upper_all:
        score += 0.25
    if "PRÉSÉLECTION" in upper_hero or "PRESELECTION" in upper_hero or "PRÉSÉLECTION" in upper_all:
        score += 0.15
    if "AUTOREBUY" in upper_hero:
        score += 0.05
    if "TU AS PASS" in upper_hero or "TU AS PASS" in upper_all:
        score -= 0.25
    if "ABSENT" in upper_hero and not upper_actions:
        score -= 0.05
    active_visual = sum(1 for state in visual_states if getattr(state, "active", False))
    if active_visual >= 2:
        score += 0.30
    elif active_visual == 1:
        score += 0.12

    return max(0.0, min(1.0, score))


def _zone_text_map(snapshot: OcrSnapshot | None) -> dict[str, str]:
    if snapshot is None:
        return {}
    return {name: zone.text for name, zone in snapshot.zones.items()}
