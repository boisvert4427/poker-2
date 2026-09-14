from __future__ import annotations

import json
import shutil
import threading
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .detection import summarize_detection
from .live_state import build_live_snapshot
from .ocr import capture_window, run_local_ocr_on_image
from .history import read_history_text
from .parser import split_winamax_hands


@dataclass(slots=True)
class RecordedSnapshot:
    timestamp: str
    session_id: str
    image_path: str
    metadata_path: str
    window_title: str
    hand_id: str


class SessionRecorder:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.session_dir: Path | None = None
        self.session_id: str | None = None
        self._record_lock = threading.Lock()
        self._audit_lock = threading.Lock()

    def start_session(self) -> Path:
        now = datetime.now()
        self.session_id = now.strftime("%Y%m%d_%H%M%S")
        self.session_dir = self.root_dir / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        return self.session_dir

    def ensure_session(self) -> Path:
        if self.session_dir is None or self.session_id is None:
            return self.start_session()
        return self.session_dir

    def record_snapshot(self) -> RecordedSnapshot | None:
        if not self._record_lock.acquire(blocking=False):
            return None
        try:
            return self._record_snapshot_locked()
        finally:
            self._record_lock.release()

    def record_live_analysis(
        self,
        *,
        image_path: str,
        history_file: object | None,
        window: object | None,
        ocr_snapshot: object | None,
        live_snapshot: object | None,
        elapsed_seconds: float,
        ocr_profile: str,
    ) -> RecordedSnapshot | None:
        """Archive one applied full live analysis and its exact source frame."""
        if not self._audit_lock.acquire(blocking=False):
            return None
        try:
            source = Path(image_path)
            if not source.exists() or live_snapshot is None:
                return None
            session_dir = self.ensure_session()
            now = datetime.now()
            timestamp = now.strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3]
            base_name = f"live_turn_{timestamp}"
            target_image = session_dir / f"{base_name}.png"
            target_meta = session_dir / f"{base_name}.live.json"
            shutil.copy2(source, target_image)

            history_path = str(getattr(history_file, "path", "") or "")
            history_block = ""
            if history_path:
                try:
                    blocks = split_winamax_hands(read_history_text(history_path))
                    history_block = blocks[-1] if blocks else ""
                except (OSError, UnicodeError, ValueError):
                    history_block = ""

            zones = getattr(ocr_snapshot, "zones", {}) or {}
            payload: dict[str, Any] = {
                "kind": "live_hero_turn_audit",
                "timestamp": timestamp,
                "timing": {
                    "full_analysis_seconds": round(float(elapsed_seconds), 4),
                    "ocr_profile": ocr_profile,
                },
                "window": {
                    "title": str(getattr(window, "title", "") or ""),
                    "pid": getattr(window, "pid", None),
                    "hwnd": getattr(window, "hwnd", None),
                    "rect": list(getattr(window, "rect", ()) or ()),
                },
                "history_file": history_path,
                "history_hand": history_block,
                "ocr": {
                    "status": str(getattr(ocr_snapshot, "status", "") or ""),
                    "engine_path": str(getattr(ocr_snapshot, "engine_path", "") or ""),
                    "text": str(getattr(ocr_snapshot, "text", "") or ""),
                    "zones": {
                        name: {
                            "text": str(getattr(zone, "text", "") or ""),
                            "rect": list(getattr(zone, "rect", ()) or ()),
                            "image_path": str(getattr(zone, "image_path", "") or ""),
                        }
                        for name, zone in zones.items()
                    },
                },
                "live_snapshot": asdict(live_snapshot) if is_dataclass(live_snapshot) else None,
            }
            target_meta.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return RecordedSnapshot(
                timestamp=timestamp,
                session_id=self.session_id or "",
                image_path=str(target_image),
                metadata_path=str(target_meta),
                window_title=str(getattr(window, "title", "") or ""),
                hand_id=str(getattr(live_snapshot, "hand_id", "") or ""),
            )
        finally:
            self._audit_lock.release()

    def _record_snapshot_locked(self) -> RecordedSnapshot | None:
        session_dir = self.ensure_session()
        summary = summarize_detection()
        window = summary["active_table_window"]
        if window is None:
            return None

        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        base_name = f"snapshot_{timestamp}"
        target_image = session_dir / f"{base_name}.png"
        target_meta = session_dir / f"{base_name}.json"

        # Capture straight into the archive. The OCR below therefore reads an
        # immutable, uniquely named frame rather than the shared live PNG.
        image_path = capture_window(window, destination=target_image)
        if not image_path:
            return None

        # OCR the exact PNG that will be archived. Capturing the window a
        # second time could associate metadata with a different poker frame.
        ocr_snapshot = run_local_ocr_on_image(image_path)
        live_snapshot = build_live_snapshot(summary["latest_history_file"], window, ocr_snapshot)

        payload: dict[str, Any] = {
            "timestamp": timestamp,
            "window": {
                "title": window.title,
                "pid": window.pid,
                "hwnd": window.hwnd,
                "rect": list(window.rect),
            },
            "history_file": getattr(summary["latest_history_file"], "path", ""),
            "ocr": {
                "status": ocr_snapshot.status,
                "engine_path": ocr_snapshot.engine_path,
                "text": ocr_snapshot.text,
                "zones": {
                    name: {
                        "text": zone.text,
                        "rect": list(zone.rect),
                        "image_path": zone.image_path,
                    }
                    for name, zone in ocr_snapshot.zones.items()
                },
            },
            "live_snapshot": asdict(live_snapshot) if live_snapshot else None,
        }
        target_meta.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        return RecordedSnapshot(
            timestamp=timestamp,
            session_id=self.session_id or "",
            image_path=str(target_image),
            metadata_path=str(target_meta),
            window_title=window.title,
            hand_id=(live_snapshot.hand_id if live_snapshot else ""),
        )

    def list_sessions(self) -> list[Path]:
        if not self.root_dir.exists():
            return []
        return sorted([path for path in self.root_dir.iterdir() if path.is_dir()], key=lambda item: item.name, reverse=True)

    def list_snapshots(self, session_dir: Path) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        for metadata_path in sorted(session_dir.glob("snapshot_*.json")):
            if metadata_path.name.endswith(
                (
                    ".review.json",
                    ".openai.json",
                    ".local.json",
                    ".live.json",
                    ".compare.json",
                    ".pure_live_compare.json",
                    ".match.json",
                    ".history_compare.json",
                )
            ):
                continue
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            image_path = metadata_path.with_suffix(".png")
            review_path = metadata_path.with_name(metadata_path.stem + ".review.json")
            review_payload = {}
            if review_path.exists():
                try:
                    review_payload = json.loads(review_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    review_payload = {}
            snapshots.append(
                {
                    "metadata_path": str(metadata_path),
                    "image_path": str(image_path) if image_path.exists() else "",
                    "payload": payload,
                    "review_path": str(review_path),
                    "review": review_payload,
                }
            )
        return snapshots

    def save_snapshot_review(self, review_path: str, review_payload: dict[str, Any]) -> None:
        Path(review_path).write_text(json.dumps(review_payload, indent=2, ensure_ascii=False), encoding="utf-8")
