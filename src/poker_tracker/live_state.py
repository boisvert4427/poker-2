from __future__ import annotations

import re
from dataclasses import replace
from dataclasses import dataclass

from .decision_support import (
    BluffAssessment,
    DecisionRecommendation,
    TABLE_MAX_PLAYERS,
    VillainRangeProfile,
    assess_bluff_risk,
    build_villain_profiles,
    format_bluff_assessments,
    format_villain_profiles,
    format_villain_ranges,
    recommend_action,
)
from .detection import WinamaxWindow
from .history import read_history_text
from .local_snapshot_analysis import (
    detect_visible_opponent_seats,
    extract_live_table_facts,
    hero_cards_visible_on_table,
)
from .ocr import OcrSnapshot, run_action_ocr_on_image, run_local_ocr_on_image
from .parser import ParsedHand, parse_winamax_hand
from .villain_db import sync_completed_history_file
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
    recommendation: DecisionRecommendation | None


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
    detected_values = _extract_live_fields(
        ocr_snapshot,
        hero_name_hint,
        hero_cards_hint,
        visible_board_hint,
        cached_names,
    )
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
    raw_action_text = "\n".join(filter(None, [*button_texts, zone_text.get("actions", "")]))
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
    hero_cards = _first_non_empty(detected_values.get("hero_cards", ""), _extract_current_hero_cards(hero_cards_text))
    table_name = _extract_table_name(window.title if window else "")
    history_hand = _read_current_history_hand(history_file)
    if history_hand and not _history_matches_screen(history_hand, hero_cards, visible_board):
        history_hand = None
    if history_hand:
        # Pseudos in the hand history are exact; OCR is only useful to locate
        # the visual seat.  Once the hand is confirmed for this table, never
        # let a typo such as "stroymeplz" replace "destroumpelz" in the
        # profiles, ranges or action matching.
        detected_values.update(_history_names_for_screen(history_hand))
    if history_hand and history_hand.hero_cards and (not hero_cards or not history_hand.is_complete):
        hero_cards = history_hand.hero_cards
        detected_values["hero_cards"] = hero_cards
    recent_actions = _history_actions_for_street(history_hand, current_street)
    is_complete = bool(history_hand and history_hand.is_complete)
    history_path = str(getattr(history_file, "path", "") or "")
    if history_path:
        sync_completed_history_file(history_path)
    villain_profiles = build_villain_profiles(detected_values)
    players_in_hand = _players_in_hand(detected_values)
    active_villain_profiles = _active_villain_profiles(villain_profiles, players_in_hand)
    bluff_assessments = assess_bluff_risk(
        villain_profiles,
        street=current_street,
        available_actions=_extract_actions(actions_text or merged_text),
        players_in_hand=players_in_hand,
        pot_text=_first_non_empty(detected_values.get("pot_value", ""), _extract_pot_text(pot_zone_text or merged_text)),
    )
    pot_text = _first_non_empty(detected_values.get("pot_value", ""), _extract_pot_text(pot_zone_text or merged_text))
    available_actions = _enrich_available_actions(
        _extract_actions(actions_text or merged_text),
        visual_states,
    )
    # With a villain shove, the centre red button is necessarily CALL (not
    # CHECK).  This repairs the frequent OCR case where only FOLD is read.
    if _history_all_in_total(recent_actions) is not None and "FOLD" in available_actions:
        active_button_names = {str(getattr(state, "name", "")) for state in visual_states if getattr(state, "active", False)}
        # Depending on stack depth / side pots, Winamax may show two controls
        # (FOLD + CALL) or three (FOLD + CALL + raise/all-in).  We only need a
        # second active action region: faced with a recorded shove it is CALL.
        if any(name != "left" for name in active_button_names) and "CALL" not in available_actions:
            available_actions.append("CALL")
    turn_confidence = _hero_turn_confidence(actions_text, hero_zone_text, merged_text, visual_states)
    is_hero_turn = turn_confidence >= 0.6
    pot_size, call_amount = _decision_amounts(
        detected_values,
        players_in_hand,
        pot_text,
        raw_action_text,
        recent_actions,
    )
    aggressive_seats = _aggressive_villain_seats(detected_values, players_in_hand)
    hero_position = _position_for_seat("hero", detected_values.get("dealer_button", ""))
    preflop_context = _preflop_decision_context(
        history_hand,
        detected_values,
        detected_values.get("dealer_button", ""),
        hero_name,
    )
    effective_stack_bb = _effective_stack_bb(detected_values, players_in_hand, aggressive_seats)
    spr = effective_stack_bb / pot_size if effective_stack_bb is not None and pot_size and pot_size > 0 else None
    detected_values["hero_position"] = hero_position
    detected_values["pot_type"] = str(preflop_context["pot_type"])
    detected_values["preflop_aggressor"] = str(preflop_context["aggressor"])
    detected_values["effective_stack_bb"] = "" if effective_stack_bb is None else f"{effective_stack_bb:g}"
    detected_values["spr"] = "" if spr is None else f"{spr:.2f}"
    recommendation = recommend_action(
        hero_cards=hero_cards,
        board=visible_board,
        street=current_street,
        available_actions=available_actions,
        recent_actions=recent_actions,
        villain_profiles=villain_profiles,
        players_in_hand=players_in_hand,
        is_hero_turn=is_hero_turn,
        pot_size=pot_size,
        call_amount=call_amount,
        aggressive_seats=aggressive_seats,
        free_big_blind_names=_free_big_blind_names(history_hand),
        hero_position=hero_position,
        hero_in_position=_hero_is_in_position(players_in_hand, detected_values.get("dealer_button", "")),
        effective_stack_bb=effective_stack_bb,
        spr=spr,
        pot_type=str(preflop_context["pot_type"]),
        preflop_aggressor=str(preflop_context["aggressor"]),
        preflop_aggressor_position=str(preflop_context["aggressor_position"]),
        hero_was_preflop_aggressor=bool(preflop_context["hero_is_aggressor"]),
        limper_count=int(preflop_context["limper_count"]),
        raise_size_bb=preflop_context["raise_size_bb"],
    )

    return LiveHandSnapshot(
        source_file=str(getattr(history_file, "path", "") or ""),
        hand_id=history_hand.hand_id if history_hand else "",
        table_name=table_name,
        hero_name=hero_name,
        hero_cards=hero_cards,
        current_street=current_street,
        is_complete=is_complete,
        visible_board=visible_board,
        recent_actions=recent_actions,
        ocr_status=ocr_snapshot.status if ocr_snapshot else "not_run",
        ocr_preview=_ocr_preview(merged_text),
        inferred_amounts=_extract_amounts(merged_text),
        window_title=window.title if window else "",
        available_actions=available_actions,
        pot_text=pot_text,
        hero_turn_confidence=turn_confidence,
        is_hero_turn=is_hero_turn,
        visual_buttons=[state.name for state in visual_states if state.active],
        detected_fields=detected_values,
        players_in_hand=players_in_hand,
        dealer_owner=detected_values.get("dealer_button", ""),
        villain_profiles=villain_profiles,
        villain_profile_summary=format_villain_profiles(active_villain_profiles),
        villain_range_summary=format_villain_ranges(active_villain_profiles),
        bluff_assessments=bluff_assessments,
        bluff_summary=format_bluff_assessments(bluff_assessments),
        recommendation=recommendation,
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
    visible_opponents = detect_visible_opponent_seats(image_path or "")
    fast_players_in_hand = list(visible_opponents)
    if hero_cards_visible_on_table(image_path or ""):
        fast_players_in_hand.append("hero")
    fast_detected_fields = {
        f"{seat}_cards_visible": "visible" if seat in visible_opponents else "not_visible"
        for seat in ("top_left", "top_right", "left", "right")
    }
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
        detected_fields=fast_detected_fields,
        players_in_hand=fast_players_in_hand,
        dealer_owner="",
        villain_profiles=[],
        villain_profile_summary="-",
        villain_range_summary="-",
        bluff_assessments=[],
        bluff_summary="-",
        recommendation=None,
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
        f"Recommandation: {snapshot.recommendation.summary if snapshot.recommendation else '-'}",
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


def _read_current_history_hand(history_file: object | None) -> ParsedHand | None:
    path = str(getattr(history_file, "path", "") or "")
    if not path:
        return None
    try:
        hand = parse_winamax_hand(read_history_text(path))
    except (OSError, UnicodeError, ValueError):
        return None
    return hand if hand.hand_id else None


def _history_matches_screen(hand: ParsedHand, hero_cards: str, visible_board: str) -> bool:
    history_hero = _normalize_card_sequence(hand.hero_cards)
    screen_hero = _normalize_card_sequence(hero_cards)
    history_board = _normalize_card_sequence(_latest_history_board(hand))
    screen_board = _normalize_card_sequence(visible_board)

    if screen_board and history_board:
        common = min(len(screen_board), len(history_board))
        if screen_board[:common] != history_board[:common]:
            return False
    # A completed hand with different hole cards is almost certainly the
    # previous hand still present in the file. Never let it overwrite OCR.
    if hand.is_complete and screen_hero and history_hero and screen_hero != history_hero:
        return False
    return bool(history_hero or history_board)


def _latest_history_board(hand: ParsedHand) -> str:
    for street in ("summary", "river", "turn", "flop"):
        board = hand.board_by_street.get(street, "")
        if board:
            return board
    return ""


def _normalize_card_sequence(cards: str) -> list[str]:
    return [f"{rank.upper().replace('10', 'T')}{suit.lower()}" for rank, suit in CARD_RE.findall((cards or "").replace("10", "T"))]


def _history_actions_for_street(hand: ParsedHand | None, street: str) -> list[str]:
    if hand is None:
        return []
    key = "pre_flop" if (street or "").lower() == "preflop" else (street or "").lower()
    return list(hand.streets.get(key, []))[-8:]


def _enrich_available_actions(actions: list[str], visual_states: list[object]) -> list[str]:
    """Fill predictable Winamax action pairs when one button OCR is missed."""
    values = list(dict.fromkeys(action.upper() for action in actions))
    active_count = sum(1 for state in visual_states if getattr(state, "active", False))
    if active_count < 2:
        return values
    action_set = set(values)
    if "CHECK" in action_set and "BET" not in action_set:
        values.append("BET")
    if "BET" in action_set and "CHECK" not in action_set:
        values.append("CHECK")
    if "CALL" in action_set:
        for action in ("FOLD", "RAISE"):
            if action not in action_set:
                values.append(action)
    return values


def _extract_live_fields(
    ocr_snapshot: OcrSnapshot | None,
    hero_name: str,
    hero_cards_hint: str = "",
    visible_board_hint: str = "",
    cached_names: dict[str, str] | None = None,
) -> dict[str, str]:
    if ocr_snapshot is None:
        return {}
    try:
        extracted = extract_live_table_facts(
            ocr_snapshot,
            hero_name,
            hero_cards_hint,
            visible_board_hint,
            cached_names,
        )
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


def _position_for_seat(seat: str, dealer_owner: str) -> str:
    """Map a calibrated screen seat to its 5-max poker position."""
    clockwise = ("top_left", "top_right", "right", "hero", "left")
    if seat not in clockwise or dealer_owner not in clockwise:
        return ""
    offset = (clockwise.index(seat) - clockwise.index(dealer_owner)) % len(clockwise)
    return {0: "BTN", 1: "SB", 2: "BB", 3: "UTG", 4: "CO"}[offset]


def _history_names_for_screen(hand: ParsedHand) -> dict[str, str]:
    """Map exact Winamax seat names to the fixed five-max screen positions."""
    try:
        hero_seat = next(
            int(item["seat"])
            for item in hand.seats
            if item.get("player") == hand.hero_name and item.get("seat")
        )
    except (KeyError, StopIteration, TypeError, ValueError):
        return {}
    seats_by_number = {
        int(item["seat"]): str(item.get("player", "") or "")
        for item in hand.seats
        if item.get("seat")
    }

    def relative(offset: int) -> int:
        return ((hero_seat - 1 - offset) % TABLE_MAX_PLAYERS) + 1

    result = {"hero_name": hand.hero_name}
    for screen_seat, offset in (("right", 1), ("top_right", 2), ("top_left", 3), ("left", 4)):
        name = seats_by_number.get(relative(offset), "")
        if name:
            result[f"{screen_seat}_name"] = name
    return result


def _hero_is_in_position(players_in_hand: list[str], dealer_owner: str) -> bool:
    """True when hero acts last postflop among all detected active players."""
    action_rank = {"SB": 0, "BB": 1, "UTG": 2, "CO": 3, "BTN": 4}
    hero_position = _position_for_seat("hero", dealer_owner)
    villain_positions = [
        _position_for_seat(seat, dealer_owner)
        for seat in players_in_hand
        if seat != "hero"
    ]
    if hero_position not in action_rank or not villain_positions:
        return False
    return all(action_rank[hero_position] > action_rank.get(position, 99) for position in villain_positions)


def _preflop_decision_context(
    hand: ParsedHand | None,
    fields: dict[str, str],
    dealer_owner: str,
    hero_name: str,
) -> dict[str, object]:
    context: dict[str, object] = {
        "pot_type": "unknown",
        "aggressor": "",
        "aggressor_position": "",
        "hero_is_aggressor": False,
        "limper_count": 0,
        "raise_size_bb": None,
    }
    if hand is None:
        return context
    actions = [str(action) for action in (hand.streets or {}).get("pre_flop", [])]
    raises: list[tuple[str, float | None]] = []
    limpers: list[str] = []
    raise_seen = False
    for action in actions:
        raise_match = re.match(r"^(.+?)\s+raises(?:\s+[\d.,]+)?\s+to\s+([\d.,]+)", action, re.IGNORECASE)
        if not raise_match:
            raise_match = re.match(r"^(.+?)\s+raises\s+([\d.,]+)", action, re.IGNORECASE)
        if raise_match:
            raise_seen = True
            raises.append((raise_match.group(1).strip(), _float_value(raise_match.group(2))))
            continue
        call_match = re.match(r"^(.+?)\s+calls\s+[\d.,]+", action, re.IGNORECASE)
        if call_match and not raise_seen:
            limpers.append(call_match.group(1).strip())

    context["limper_count"] = len(limpers)
    if raises:
        aggressor, amount = raises[-1]
        context["pot_type"] = "3bet" if len(raises) >= 2 else "single_raised"
        context["aggressor"] = aggressor
        context["hero_is_aggressor"] = _same_player(aggressor, hero_name)
        aggressor_seat = _seat_for_player(aggressor, fields, hero_name)
        context["aggressor_position"] = _position_for_seat(aggressor_seat, dealer_owner)
        if amount is not None and hand.big_blind > 0:
            context["raise_size_bb"] = amount / hand.big_blind
    elif limpers:
        context["pot_type"] = "limped"
    else:
        context["pot_type"] = "unopened"
    return context


def _seat_for_player(player_name: str, fields: dict[str, str], hero_name: str) -> str:
    candidates = {
        "hero": hero_name,
        "top_left": fields.get("top_left_name", ""),
        "top_right": fields.get("top_right_name", ""),
        "left": fields.get("left_name", ""),
        "right": fields.get("right_name", ""),
    }
    for seat, candidate in candidates.items():
        if _same_player(player_name, candidate):
            return seat
    return ""


def _same_player(left: str, right: str) -> bool:
    left_key = re.sub(r"[^a-z0-9]", "", (left or "").casefold())
    right_key = re.sub(r"[^a-z0-9]", "", (right or "").casefold())
    if not left_key or not right_key:
        return False
    return left_key == right_key or (min(len(left_key), len(right_key)) >= 5 and (left_key in right_key or right_key in left_key))


def _float_value(value: str) -> float | None:
    try:
        return float((value or "").replace(",", "."))
    except ValueError:
        return None


def _effective_stack_bb(
    fields: dict[str, str],
    players_in_hand: list[str],
    aggressive_seats: list[str],
) -> float | None:
    hero_stack = _bb_value(fields.get("hero_stack", ""))
    if hero_stack is None:
        return None
    target_seats = [seat for seat in aggressive_seats if seat != "hero"] or [
        seat for seat in players_in_hand if seat != "hero"
    ]
    villain_stacks = [
        value
        for seat in target_seats
        for value in [_bb_value(fields.get(f"{seat}_stack", ""))]
        if value is not None
    ]
    if not villain_stacks:
        return None
    return min(hero_stack, max(villain_stacks))


def _decision_amounts(
    fields: dict[str, str],
    players_in_hand: list[str],
    pot_text: str,
    action_text: str = "",
    history_actions: list[str] | None = None,
) -> tuple[float | None, float | None]:
    pot_size = _bb_value(pot_text)
    if pot_size is None:
        return None, None
    direct_call = _call_amount_from_actions(action_text)
    if direct_call is not None:
        return pot_size, direct_call
    hero_bet = _bb_value(fields.get("hero_bet", "")) or 0.0
    # Winamax history gives the exact final amount for a shove ("raises X to
    # Y and is all-in" / "bets Y and is all-in").  It is more reliable than
    # a half-read CALL button, and remains available when the UI OCR is late.
    all_in_total = _history_all_in_total(history_actions or [])
    if all_in_total is not None:
        amount = all_in_total - hero_bet
        if amount > 0:
            return pot_size, amount
    villain_bets = [
        value
        for seat in players_in_hand
        if seat != "hero"
        for value in [_bb_value(fields.get(f"{seat}_bet", ""))]
        if value is not None
    ]
    if not villain_bets:
        return pot_size, None
    amount = max(villain_bets) - hero_bet
    return pot_size, amount if amount > 0 else None


def _call_amount_from_actions(text: str) -> float | None:
    normalized = " ".join((text or "").upper().replace(",", ".").split())
    patterns = (
        r"(\d+(?:\.\d+)?)\s*BB\s*CALL\b",
        r"\bCALL\s*(\d+(?:\.\d+)?)\s*BB",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            if value > 0:
                return value
    return None


def _history_all_in_total(actions: list[str]) -> float | None:
    for line in reversed(actions):
        normalized = " ".join((line or "").lower().replace(",", ".").split())
        if "all-in" not in normalized and "all in" not in normalized:
            continue
        to_match = re.search(r"\bto\s+(\d+(?:\.\d+)?)\b", normalized)
        bet_match = re.search(r"\bbets?\s+(\d+(?:\.\d+)?)\b", normalized)
        match = to_match or bet_match
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def _free_big_blind_names(history_hand: ParsedHand | None) -> list[str]:
    """Return the BB only when they checked a limped preflop pot."""
    if history_hand is None:
        return []
    actions = list((history_hand.streets or {}).get("pre_flop", []) or [])
    if not actions:
        return []
    big_blind = ""
    for action in actions:
        match = re.match(r"^(.+?)\s+posts\s+big blind", str(action), re.IGNORECASE)
        if match:
            big_blind = match.group(1).strip()
            break
    if not big_blind:
        return []
    player_key = re.sub(r"[^a-z0-9]", "", big_blind.lower())
    player_actions = [
        str(action).lower()
        for action in actions
        if player_key and player_key in re.sub(r"[^a-z0-9]", "", str(action).lower())
    ]
    checked = any(" checks" in f" {action}" for action in player_actions)
    voluntarily_entered = any(token in action for action in player_actions for token in (" calls", " raises", " all-in", " all in"))
    return [big_blind] if checked and not voluntarily_entered else []


def _aggressive_villain_seats(fields: dict[str, str], players_in_hand: list[str]) -> list[str]:
    hero_bet = _bb_value(fields.get("hero_bet", "")) or 0.0
    bets = {
        seat: value
        for seat in players_in_hand
        if seat != "hero"
        for value in [_bb_value(fields.get(f"{seat}_bet", ""))]
        if value is not None
    }
    if not bets:
        return []
    maximum = max(bets.values())
    if maximum <= hero_bet:
        return []
    return [seat for seat, value in bets.items() if abs(value - maximum) < 0.001]


def _bb_value(text: str) -> float | None:
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)", text or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _active_villain_profiles(
    profiles: list[VillainRangeProfile],
    players_in_hand: list[str],
) -> list[VillainRangeProfile]:
    """Keep only opponents whose face-down cards are currently visible.

    The OCR can occasionally fail to classify a card back.  In that case we
    deliberately show no range rather than presenting a folded player as if
    they were still in the hand.
    """
    active_seats = set(players_in_hand)
    return [profile for profile in profiles if profile.seat in active_seats]


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

    # Grey preselection controls can contain FOLD/CHECK text, but are not an
    # actionable hero turn. A real Winamax action bar has red buttons.
    if visual_states and not any(getattr(state, "red_ratio", 0.0) >= 0.04 for state in visual_states):
        return 0.0

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
