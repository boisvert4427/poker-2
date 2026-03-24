from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .detection import summarize_detection
from .live_state import build_live_snapshot
from .ocr import capture_window, run_local_ocr


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
        session_dir = self.ensure_session()
        summary = summarize_detection()
        window = summary["active_table_window"]
        if window is None:
            return None

        image_path = capture_window(window)
        if not image_path:
            return None

        ocr_snapshot = run_local_ocr(window)
        live_snapshot = build_live_snapshot(summary["latest_history_file"], window, ocr_snapshot)

        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        base_name = f"snapshot_{timestamp}"
        target_image = session_dir / f"{base_name}.png"
        target_meta = session_dir / f"{base_name}.json"

        Path(image_path).replace(target_image)

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
            if metadata_path.name.endswith(".review.json"):
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
