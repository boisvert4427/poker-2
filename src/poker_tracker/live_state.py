from __future__ import annotations

import re
from dataclasses import replace
from dataclasses import dataclass

from .decision_support import (
    BluffAssessment,
    VillainRangeProfile,
    assess_bluff_risk,
    build_villain_profiles,
    format_bluff_assessments,
    format_villain_profiles,
    format_villain_ranges,
)
from .detection import WinamaxWindow
from .local_snapshot_analysis import extract_live_table_facts
from .ocr import OcrSnapshot, run_action_ocr_on_image, run_local_ocr_on_image
from .visual import analyze_action_buttons


AMOUNT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
ACTION_TOKEN_RE = re.compile(r"\b(FOLD|CALL|CHECK|BET|RAISE|RAISES TO|ALL-IN)\b", re.IGNORECASE)
POT_RE = re.compile(r"\bPot\s*:\s*([\d.,]+)", re.IGNORECASE)
SIDEPOT_RE = re.compile(r"\bSide pots?\s*:\s*([^\n]+)", re.IGNORECASE)
CARD_RE = re.compile(r"\b([2-9TJQKA](?:[shdc]))\b", re.IGNORECASE)
SAFE_HERO_NAME_RE = re.compile(r"^[A-Za-z0-9_/-]{4,}$")
HERO_NAME_NOISE = {
    "sera",
    "voir",
    "cartes",
    "poser",
    "blind",
    "attendre",
    "action",
    "tour",
    "hero",
}
TURN_NOISE_MARKERS = (
    "voir tes cartes",
    "poser la big blind",
    "poser la small blind",
    "preselection",
    "présélection",
)


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
    detected_fields: dict[str, str]
    players_in_hand: list[str]
    dealer_owner: str
    villain_profiles: list[VillainRangeProfile]
    villain_profile_summary: str
    villain_range_summary: str
    bluff_assessments: list[BluffAssessment]
    bluff_summary: str


def build_live_snapshot(
    history_file: object | None,
    window: WinamaxWindow | None,
    ocr_snapshot: OcrSnapshot | None,
    hero_name_hint: str = "",
    hero_cards_hint: str = "",
    visible_board_hint: str = "",
    cached_names: dict[str, str] | None = None,
) -> LiveHandSnapshot | None:
    if window is None and ocr_snapshot is None:
        return None

    zone_text = _zone_text_map(ocr_snapshot)
    detected_values = _extract_live_fields(ocr_snapshot, hero_name_hint, hero_cards_hint)
    for field, value in (cached_names or {}).items():
        if value:
            detected_values[field] = value
    if visible_board_hint:
        board_cards = visible_board_hint.split()
        for index in range(1, 6):
            detected_values[f"board_card_{index}"] = board_cards[index - 1] if index <= len(board_cards) else ""
    visual_states = analyze_action_buttons(ocr_snapshot.image_path) if ocr_snapshot and ocr_snapshot.image_path else []
    button_texts = [
        zone_text.get("action_left", ""),
        zone_text.get("action_center", ""),
        zone_text.get("action_right", ""),
    ]
    actions_text = _sanitize_action_texts(button_texts, zone_text.get("actions", ""))
    pot_zone_text = zone_text.get("pot", "")
    hero_zone_text = zone_text.get("hero", "")
    hero_cards_text = "\n".join(
        filter(
            None,
            [
                zone_text.get("hero_status", ""),
                zone_text.get("hero", ""),
                ocr_snapshot.text if ocr_snapshot else "",
            ],
        )
    )
    merged_text = "\n".join(filter(None, [actions_text, pot_zone_text, hero_zone_text, ocr_snapshot.text if ocr_snapshot else ""]))
    visible_board = _format_visible_board(detected_values)
    current_street = _infer_street_from_board(visible_board)
    hero_name = _sanitize_hero_name(detected_values.get("hero_name", ""), hero_name_hint or "RougeLion")
    table_name = _extract_table_name(window.title if window else "")
    is_complete = False
    villain_profiles = build_villain_profiles(detected_values)
    players_in_hand = _players_in_hand(detected_values)
    bluff_assessments = assess_bluff_risk(
        villain_profiles,
        street=current_street,
        available_actions=_extract_actions(actions_text or merged_text),
        players_in_hand=players_in_hand,
        pot_text=_first_non_empty(detected_values.get("pot_value", ""), _extract_pot_text(pot_zone_text or merged_text)),
    )
    pot_text = _first_non_empty(detected_values.get("pot_value", ""), _extract_pot_text(pot_zone_text or merged_text))

    return LiveHandSnapshot(
        source_file="",
        hand_id="",
        table_name=table_name,
        hero_name=hero_name,
        hero_cards=_first_non_empty(detected_values.get("hero_cards", ""), _extract_current_hero_cards(hero_cards_text)),
        current_street=current_street,
        is_complete=is_complete,
        visible_board=visible_board,
        recent_actions=[],
        ocr_status=ocr_snapshot.status if ocr_snapshot else "not_run",
        ocr_preview=_ocr_preview(merged_text),
        inferred_amounts=_extract_amounts(merged_text),
        window_title=window.title if window else "",
        available_actions=_extract_actions(actions_text or merged_text),
        pot_text=pot_text,
        hero_turn_confidence=_hero_turn_confidence(actions_text, hero_zone_text, merged_text, visual_states),
        is_hero_turn=_hero_turn_confidence(actions_text, hero_zone_text, merged_text, visual_states) >= 0.6,
        visual_buttons=[state.name for state in visual_states if state.active],
        detected_fields=detected_values,
        players_in_hand=players_in_hand,
        dealer_owner=detected_values.get("dealer_button", ""),
        villain_profiles=villain_profiles,
        villain_profile_summary=format_villain_profiles(villain_profiles),
        villain_range_summary=format_villain_ranges(villain_profiles),
        bluff_assessments=bluff_assessments,
        bluff_summary=format_bluff_assessments(bluff_assessments),
    )


def build_fast_live_snapshot(
    history_file: object | None,
    window: WinamaxWindow | None,
    image_path: str | None,
    action_texts: dict[str, str] | None = None,
    cached_context: dict[str, str] | None = None,
) -> LiveHandSnapshot | None:
    cached_context = cached_context or {}
    if window is None and not cached_context:
        return None
    visual_states = analyze_action_buttons(image_path) if image_path else []
    action_texts = action_texts or {}
    merged_action_text = _sanitize_action_texts(
        [action_texts.get("action_left", ""), action_texts.get("action_center", ""), action_texts.get("action_right", "")],
        "",
    )
    hero_hint_text = " ".join(
        part
        for part in [
            action_texts.get("hero_status", ""),
            action_texts.get("hero", ""),
            action_texts.get("actions_hint", ""),
        ]
        if part
    )
    available_actions = _extract_actions(merged_action_text)
    confidence = _hero_turn_confidence(
        merged_action_text,
        hero_hint_text,
        f"{hero_hint_text} {merged_action_text}".strip(),
        visual_states,
    )
    visual_buttons = [state.name for state in visual_states if state.active]
    table_name = _extract_table_name(window.title if window else "")
    return LiveHandSnapshot(
        source_file="",
        hand_id="",
        table_name=table_name or cached_context.get("table_name", ""),
        hero_name=_sanitize_hero_name(cached_context.get("hero_name", ""), "RougeLion"),
        hero_cards=cached_context.get("hero_cards", ""),
        current_street=cached_context.get("current_street", ""),
        is_complete=False,
        visible_board=cached_context.get("visible_board", ""),
        recent_actions=[],
        ocr_status="fast_scan",
        ocr_preview=(
            "Capture rapide sans OCR complet. "
            f"Boutons visuels: {', '.join(visual_buttons) if visual_buttons else '-'} | "
            f"Actions OCR leger: {merged_action_text or '-'}"
        ),
        inferred_amounts=[],
        window_title=window.title if window else "",
        available_actions=available_actions,
        pot_text="",
        hero_turn_confidence=confidence,
        is_hero_turn=confidence >= 0.6,
        visual_buttons=visual_buttons,
        detected_fields={},
        players_in_hand=[],
        dealer_owner="",
        villain_profiles=[],
        villain_profile_summary="-",
        villain_range_summary="-",
        bluff_assessments=[],
        bluff_summary="-",
    )


def detect_hero_turn_on_image(
    image_path: str,
    *,
    window: WinamaxWindow | None = None,
    cached_context: dict[str, str] | None = None,
) -> LiveHandSnapshot | None:
    action_texts = run_action_ocr_on_image(image_path)
    snapshot = build_fast_live_snapshot(
        history_file=None,
        window=window,
        image_path=image_path,
        action_texts=action_texts,
        cached_context=cached_context,
    )
    if snapshot is None or snapshot.is_hero_turn:
        return snapshot
    if not _needs_turn_fallback(snapshot):
        return snapshot

    full_snapshot = run_local_ocr_on_image(image_path)
    full_text = " ".join((full_snapshot.text or "").split())
    lowered = full_text.lower()
    if any(marker in lowered for marker in TURN_NOISE_MARKERS):
        full_text = re.sub("|".join(re.escape(marker) for marker in TURN_NOISE_MARKERS), " ", full_text, flags=re.IGNORECASE)
    full_actions = _extract_actions(full_text)
    if not full_actions or len(full_actions) > 2:
        return snapshot
    return replace(
        snapshot,
        ocr_preview=(
            snapshot.ocr_preview
            + " | Fallback OCR complet: "
            + ", ".join(full_actions)
        ),
        available_actions=full_actions,
        hero_turn_confidence=max(snapshot.hero_turn_confidence, 0.75),
        is_hero_turn=True,
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


def format_live_commentary(snapshot: LiveHandSnapshot | None) -> str:
    if snapshot is None:
        return "Aucune table live exploitable pour le moment."

    table_name = snapshot.table_name or snapshot.window_title or "table inconnue"
    hero_name = snapshot.hero_name or "hero inconnu"
    hero_cards = snapshot.hero_cards or "-"
    street = snapshot.current_street or "-"
    board = snapshot.visible_board or "pas encore de board visible"
    pot = snapshot.pot_text or "-"
    actions = ", ".join(snapshot.available_actions) if snapshot.available_actions else "aucune action lue proprement"
    recent_actions = " | ".join(snapshot.recent_actions[-4:]) if snapshot.recent_actions else "-"
    visual_buttons = ", ".join(snapshot.visual_buttons) if snapshot.visual_buttons else "-"
    stacks = _format_stacks(snapshot.detected_fields)
    in_hand = ", ".join(snapshot.players_in_hand) if snapshot.players_in_hand else "-"
    dealer = snapshot.dealer_owner or "-"
    villain_profiles = snapshot.villain_profile_summary or "-"
    villain_ranges = snapshot.villain_range_summary or "-"
    bluff_summary = snapshot.bluff_summary or "-"

    if snapshot.is_hero_turn:
        headline = (
            f"Decision probable pour {hero_name} sur {street} : c'est vraisemblablement ton tour "
            f"(confiance {snapshot.hero_turn_confidence:.2f})."
        )
    else:
        headline = (
            f"Observation en cours sur {table_name} : ce n'est probablement pas ton tour "
            f"(confiance {snapshot.hero_turn_confidence:.2f})."
        )

    lines = [
        headline,
        "",
        "Table",
        f"- nom : {table_name}",
        f"- etat : {'main terminee' if snapshot.is_complete else 'main en cours'}",
        "",
        "Hero",
        f"- joueur : {hero_name}",
        f"- cartes : {hero_cards}",
        f"- street : {street}",
        "",
        "Board et Pot",
        f"- board : {board}",
        f"- pot : {pot}",
        f"- dealer : {dealer}",
        "",
        "Joueurs",
        f"- stacks : {stacks}",
        f"- encore en course : {in_hand}",
        f"- profils : {villain_profiles}",
        f"- ranges supposees : {villain_ranges}",
        f"- risque de bluff : {bluff_summary}",
        "",
        "Action",
        f"- tour de parole : {'oui' if snapshot.is_hero_turn else 'non'}",
        f"- actions detectees : {actions}",
        f"- boutons visuels : {visual_buttons}",
        "",
        "Contexte recent",
        f"- dernieres actions : {recent_actions}",
        "",
        "Lecture OCR",
        f"- statut OCR : {snapshot.ocr_status}",
    ]

    if snapshot.ocr_preview:
        lines.append(f"- resume : {snapshot.ocr_preview}")
    else:
        lines.append("- resume : (vide)")

    return "\n".join(lines)


def _extract_table_name(window_title: str) -> str:
    title = (window_title or "").strip()
    if not title:
        return ""
    if title.lower().startswith("winamax "):
        return title[8:].strip()
    return title


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


def _sanitize_action_texts(texts: object, fallback_text: str) -> str:
    ordered: list[str] = []
    iterable = texts if isinstance(texts, (list, tuple, set)) else list(texts) if texts else []
    for raw in iterable:
        cleaned = " ".join(str(raw or "").strip().split())
        if not cleaned:
            continue
        tokens = _extract_actions(cleaned)
        if not tokens:
            continue
        joined = " ".join(tokens)
        if joined not in ordered:
            ordered.append(joined)
    if ordered:
        return "\n".join(ordered)
    cleaned_fallback = " ".join(str(fallback_text or "").strip().split())
    fallback_tokens = _extract_actions(cleaned_fallback)
    return " ".join(fallback_tokens)


def _extract_pot_text(text: str) -> str:
    match = POT_RE.search(text)
    if match:
        return match.group(1).replace(",", ".")
    sidepot_match = SIDEPOT_RE.search(text)
    if sidepot_match:
        return sidepot_match.group(1).strip()
    return ""


def _extract_current_hero_cards(text: str) -> str:
    seen: list[str] = []
    normalized = text.replace("10", "T")
    for match in CARD_RE.findall(normalized):
        card = match.upper()
        rank = card[0]
        suit = card[1].lower()
        normalized_card = f"{rank}{suit}"
        if normalized_card not in seen:
            seen.append(normalized_card)
        if len(seen) == 2:
            break
    return " ".join(seen)


def _extract_live_fields(ocr_snapshot: OcrSnapshot | None, hero_name: str, hero_cards_hint: str = "") -> dict[str, str]:
    if ocr_snapshot is None:
        return {}
    try:
        extracted = extract_live_table_facts(ocr_snapshot, hero_name, hero_cards_hint)
    except Exception:
        return {}
    return extracted


def _players_in_hand(fields: dict[str, str]) -> list[str]:
    labels = {
        "top_left_cards_visible": "top_left",
        "top_right_cards_visible": "top_right",
        "left_cards_visible": "left",
        "right_cards_visible": "right",
    }
    active = [seat for field, seat in labels.items() if fields.get(field, "") == "visible"]
    hero_cards = fields.get("hero_cards", "")
    if hero_cards and hero_cards not in {"-", "present", "active"}:
        active.append("hero")
    return active


def _format_stacks(fields: dict[str, str]) -> str:
    parts = []
    for seat, name_field, stack_field in (
        ("top_left", "top_left_name", "top_left_stack"),
        ("top_right", "top_right_name", "top_right_stack"),
        ("left", "left_name", "left_stack"),
        ("right", "right_name", "right_stack"),
        ("hero", "hero_name", "hero_stack"),
    ):
        name = fields.get(name_field, "") or seat
        stack = fields.get(stack_field, "")
        if stack:
            parts.append(f"{name} {stack}")
    return " | ".join(parts) if parts else "-"


def _first_non_empty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def _sanitize_hero_name(value: str, fallback: str = "") -> str:
    cleaned = " ".join(str(value or "").strip().split())
    lowered = cleaned.lower()
    if cleaned and SAFE_HERO_NAME_RE.fullmatch(cleaned) and lowered not in HERO_NAME_NOISE:
        return cleaned
    return fallback or ""


def _format_visible_board(fields: dict[str, str]) -> str:
    cards = []
    for key in ("board_card_1", "board_card_2", "board_card_3", "board_card_4", "board_card_5"):
        value = fields.get(key, "")
        if value:
            cards.append(value)
    return " ".join(cards)


def _infer_street_from_board(board: str) -> str:
    count = len([part for part in (board or "").split() if part.strip()])
    if count >= 5:
        return "river"
    if count == 4:
        return "turn"
    if count >= 3:
        return "flop"
    return "preflop"


def _hero_turn_confidence(actions_text: str, hero_text: str, fallback_text: str, visual_states: list[object]) -> float:
    upper_actions = actions_text.upper()
    upper_hero = hero_text.upper()
    upper_all = fallback_text.upper()
    score = 0.0

    if (
        "PRESELECTION" in upper_hero
        or ("PR" in upper_hero and "SELECTION" in upper_hero)
        or "PROCHAINE ACTION" in upper_hero
        or "SELECTION DE LA PROCHAINE ACTION" in upper_hero
        or "PRESELECTION" in upper_all
        or "PROCHAINE ACTION" in upper_all
        or "SELECTION DE LA PROCHAINE ACTION" in upper_all
    ):
        return 0.0
    if (
        "TU AS PASS" in upper_hero
        or "TU AS PASSE" in upper_hero
        or "TU AS PASS" in upper_all
        or "TU AS PASSE" in upper_all
    ):
        return 0.0
    if "VOIR TES CARTES" in upper_hero or "POSER LA BIG BLIND" in upper_hero or "POSER LA SMALL BLIND" in upper_hero:
        return 0.0

    has_clean_action = any(token in upper_actions for token in ("FOLD", "CALL", "CHECK", "BET", "RAISE", "ALL-IN"))

    if has_clean_action:
        score += 0.65

    if "FOLD" in upper_actions or "FOLD" in upper_all:
        score += 0.35
    if "CALL" in upper_actions or "CHECK" in upper_actions or "CALL" in upper_all or "CHECK" in upper_all:
        score += 0.25
    if "RAISE" in upper_actions or "BET" in upper_actions or "RAISE" in upper_all or "BET" in upper_all:
        score += 0.25
    if "AUTOREBUY" in upper_hero:
        score += 0.05
    if "ABSENT" in upper_hero and not upper_actions:
        score -= 0.05
    active_names = [getattr(state, "name", "") for state in visual_states if getattr(state, "active", False)]
    active_visual = len(active_names)
    if {"left", "center"}.issubset(set(active_names)):
        red_active = any(
            getattr(state, "active", False) and getattr(state, "red_ratio", 0.0) >= 0.04
            for state in visual_states
        )
        score += 0.35 if has_clean_action else (0.65 if red_active else 0.0)
    elif active_visual >= 2:
        # Les boutons de mise peuvent être lisibles visuellement alors que
        # leur texte OCR ne l'est pas. Plusieurs zones actives suffisent donc
        # à confirmer le tour hero, sauf si un marqueur d'attente a déjà
        # déclenché le retour anticipé ci-dessus.
        red_active = any(
            getattr(state, "active", False) and getattr(state, "red_ratio", 0.0) >= 0.04
            for state in visual_states
        )
        score += 0.35 if has_clean_action else (0.65 if red_active else 0.0)
    elif active_visual == 1:
        # A single broad active region may contain POT and ALL-IN together.
        red_active = any(
            getattr(state, "active", False) and getattr(state, "red_ratio", 0.0) >= 0.04
            for state in visual_states
        )
        score += 0.12 if has_clean_action else (0.65 if red_active else 0.0)

    return max(0.0, min(1.0, score))

def _needs_turn_fallback(snapshot: LiveHandSnapshot) -> bool:
    visual = tuple(snapshot.visual_buttons)
    if visual in {("center",), ()}:
        return True
    return False


def _zone_text_map(snapshot: OcrSnapshot | None) -> dict[str, str]:
    if snapshot is None:
        return {}
    return {name: zone.text for name, zone in snapshot.zones.items()}
