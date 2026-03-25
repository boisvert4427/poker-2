from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .detection import guess_history_locations
from .history import extract_table_token, find_history_file_for_table, read_history_text
from .parser import ParsedHand, parse_winamax_hand
from .session_recorder import SessionRecorder


@dataclass(slots=True)
class HandMatch:
    matched: bool
    reason: str
    score: float
    snapshot_timestamp: str
    history_file: str
    snapshot_hand_id: str
    matched_hand_id: str
    table_name: str
    hero_name: str
    hero_cards: str
    played_at: str
    board: str


def parse_all_hands_from_history(path: str) -> list[ParsedHand]:
    raw = read_history_text(path)
    chunks = [chunk.strip() for chunk in raw.split("\n\n\n") if chunk.strip()]
    hands: list[ParsedHand] = []
    for chunk in chunks:
        hand = parse_winamax_hand(chunk)
        if hand.hand_id:
            hand.source_file = path
            hands.append(hand)
    return hands


def match_snapshot_payload_to_history(payload: dict[str, Any]) -> HandMatch:
    history_file = payload.get("history_file", "")
    snapshot_ts = payload.get("timestamp", "")
    live = payload.get("live_snapshot") or {}
    snapshot_hand_id = live.get("hand_id", "") or ""
    history_files = _candidate_history_files(payload)

    if not history_files:
        return HandMatch(
            matched=False,
            reason="history_file_missing",
            score=0.0,
            snapshot_timestamp=snapshot_ts,
            history_file=history_file,
            snapshot_hand_id=snapshot_hand_id,
            matched_hand_id="",
            table_name="",
            hero_name="",
            hero_cards="",
            played_at="",
            board="",
        )

    hands: list[ParsedHand] = []
    seen_ids: set[str] = set()
    for candidate in history_files:
        for hand in parse_all_hands_from_history(candidate):
            if hand.hand_id and hand.hand_id in seen_ids:
                continue
            if hand.hand_id:
                seen_ids.add(hand.hand_id)
            hands.append(hand)

    if not hands:
        return HandMatch(
            matched=False,
            reason="history_parse_empty",
            score=0.0,
            snapshot_timestamp=snapshot_ts,
            history_file=history_file,
            snapshot_hand_id=snapshot_hand_id,
            matched_hand_id="",
            table_name="",
            hero_name="",
            hero_cards="",
            played_at="",
            board="",
        )

    by_id = {hand.hand_id: hand for hand in hands if hand.hand_id}
    if snapshot_hand_id and snapshot_hand_id in by_id and _hand_id_match_is_plausible(payload, by_id[snapshot_hand_id]):
        hand = by_id[snapshot_hand_id]
        return _build_match(payload, hand, reason="hand_id", score=1.0)

    best_hand: ParsedHand | None = None
    best_score = -1.0
    best_reason = "fallback"

    for hand in hands:
        delta = _timestamp_delta_minutes(snapshot_ts, hand.played_at or "")
        if delta is not None and delta > 180:
            continue
        score = 0.0
        if _snapshot_table_matches_hand(payload, hand):
            score += 0.35
        if _norm(hand.hero_name) and _norm(hand.hero_name) == _norm(live.get("hero_name", "")):
            score += 0.20
        if _norm(hand.hero_cards) and _norm(hand.hero_cards) == _norm(live.get("hero_cards", "")):
            score += 0.30
        if _norm(_visible_board(hand)) and _norm(_visible_board(hand)) == _norm(live.get("visible_board", "")):
            score += 0.25
        ts_bonus = _timestamp_similarity(snapshot_ts, hand.played_at)
        score += ts_bonus
        if score > best_score:
            best_score = score
            best_hand = hand

    if best_hand is None or best_score < 0.45:
        return HandMatch(
            matched=False,
            reason="no_confident_match",
            score=max(best_score, 0.0),
            snapshot_timestamp=snapshot_ts,
            history_file=history_file,
            snapshot_hand_id=snapshot_hand_id,
            matched_hand_id="",
            table_name="",
            hero_name="",
            hero_cards="",
            played_at="",
            board="",
        )

    return _build_match(payload, best_hand, reason=best_reason, score=best_score)


def match_session_to_history(session_dir: Path) -> dict[str, Any]:
    recorder = SessionRecorder(session_dir.parent)
    snapshots = recorder.list_snapshots(session_dir)
    matches: list[dict[str, Any]] = []
    matched_count = 0
    reason_counts: dict[str, int] = {}

    for snapshot in snapshots:
        payload = snapshot.get("payload", {})
        match = match_snapshot_payload_to_history(payload)
        match_path = Path(snapshot["metadata_path"]).with_name(Path(snapshot["metadata_path"]).stem + ".match.json")
        match_path.write_text(json.dumps(asdict(match), indent=2, ensure_ascii=False), encoding="utf-8")
        matches.append({"metadata_path": snapshot["metadata_path"], "match_path": str(match_path), **asdict(match)})
        if match.matched:
            matched_count += 1
        reason_counts[match.reason] = reason_counts.get(match.reason, 0) + 1

    summary = {
        "session": str(session_dir),
        "snapshots": len(snapshots),
        "matched": matched_count,
        "match_rate": round(matched_count / len(snapshots), 3) if snapshots else 0.0,
        "reason_counts": reason_counts,
        "matches": matches,
    }
    summary_path = session_dir / "history_match.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def _build_match(payload: dict[str, Any], hand: ParsedHand, *, reason: str, score: float) -> HandMatch:
    live = payload.get("live_snapshot") or {}
    return HandMatch(
        matched=True,
        reason=reason,
        score=round(score, 3),
        snapshot_timestamp=payload.get("timestamp", ""),
        history_file=hand.source_file or payload.get("history_file", ""),
        snapshot_hand_id=live.get("hand_id", "") or "",
        matched_hand_id=hand.hand_id or "",
        table_name=hand.table_name or "",
        hero_name=hand.hero_name or "",
        hero_cards=hand.hero_cards or "",
        played_at=hand.played_at or "",
        board=_visible_board(hand),
    )


def _visible_board(hand: ParsedHand) -> str:
    for street in ("summary", "river", "turn", "flop"):
        value = hand.board_by_street.get(street)
        if value:
            return value
    return ""


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _timestamp_similarity(snapshot_timestamp: str, played_at: str) -> float:
    if not snapshot_timestamp or not played_at:
        return 0.0
    try:
        snap = datetime.strptime(snapshot_timestamp, "%Y-%m-%dT%H-%M-%S")
        hand = datetime.strptime(played_at, "%Y/%m/%d %H:%M:%S UTC")
    except ValueError:
        return 0.0
    delta_minutes = abs((snap - hand).total_seconds()) / 60
    if delta_minutes <= 2:
        return 0.15
    if delta_minutes <= 10:
        return 0.08
    if delta_minutes <= 60:
        return 0.03
    return 0.0


def _timestamp_delta_minutes(snapshot_timestamp: str, played_at: str) -> float | None:
    if not snapshot_timestamp or not played_at:
        return None
    try:
        snap = datetime.strptime(snapshot_timestamp, "%Y-%m-%dT%H-%M-%S")
        hand = datetime.strptime(played_at, "%Y/%m/%d %H:%M:%S UTC")
    except ValueError:
        return None
    return abs((snap - hand).total_seconds()) / 60


def _snapshot_table_matches_hand(payload: dict[str, Any], hand: ParsedHand) -> bool:
    window = payload.get("window") or {}
    live = payload.get("live_snapshot") or {}
    window_token = extract_table_token(window.get("title", ""))
    if window_token:
        hand_token = extract_table_token(f"Winamax {hand.table_name}") if hand.table_name else ""
        return _norm(window_token) == _norm(hand_token) or _norm(window_token) == _norm(hand.table_name)

    candidates = [
        extract_table_token(f"Winamax {live.get('table_name', '')}") if live.get("table_name") else "",
        live.get("table_name", ""),
    ]
    hand_token = extract_table_token(f"Winamax {hand.table_name}") if hand.table_name else ""
    hand_norms = {_norm(hand.table_name), _norm(hand_token)}
    return any(_norm(candidate) in hand_norms for candidate in candidates if candidate)


def _hand_id_match_is_plausible(payload: dict[str, Any], hand: ParsedHand) -> bool:
    if not _snapshot_table_matches_hand(payload, hand):
        return False
    delta = _timestamp_delta_minutes(payload.get("timestamp", ""), hand.played_at or "")
    if delta is not None and delta > 360:
        return False
    return True


def _candidate_history_files(payload: dict[str, Any]) -> list[str]:
    raw_history = payload.get("history_file", "") or ""
    history_dirs = [
        item.path
        for item in guess_history_locations()
        if item.exists and item.accessible and item.path.lower().endswith("history")
    ]
    window = payload.get("window") or {}
    table_title = window.get("title", "") or ""
    table_history = find_history_file_for_table(history_dirs, table_title)
    if table_history and Path(table_history.path).exists():
        return [table_history.path]

    candidates: list[str] = []
    if raw_history and Path(raw_history).exists():
        candidates.append(raw_history)
    return candidates
