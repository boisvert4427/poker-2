from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from poker_tracker.detection import WinamaxWindow
from poker_tracker.ocr import OcrSnapshot, OcrZoneResult
from poker_tracker.session_recorder import SessionRecorder


@dataclass
class MiniLiveSnapshot:
    hand_id: str
    hero_cards: str
    recommendation: dict[str, str]


class SessionRecorderTests(unittest.TestCase):
    def test_live_analysis_archives_matching_png_json_and_history(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = root / "source.png"
            image.write_bytes(b"fake-png")
            history = root / "history.txt"
            history.write_text(
                "Winamax Poker - CashGame - HandId: #123 - Holdem no limit (0.01/0.02) - 2026/09/16 19:31:32 UTC\n"
                "Table: 'Nice 06' 5-max Seat #1 is the button\n"
                "Dealt to RougeLion [Ah Kh]\n"
                "*** SUMMARY ***\n"
                "Total pot 0.10 | Rake 0.00\n"
                "Seat 1: RougeLion showed [Ah Kh] and won 0.10\n",
                encoding="utf-8",
            )
            ocr = OcrSnapshot(
                image_path=str(image),
                engine_available=True,
                engine_path="tesseract",
                status="ok",
                text="",
                zones={"pot": OcrZoneResult("pot", "pot.png", "3 BB", (1, 2, 3, 4))},
            )
            live = MiniLiveSnapshot("123", "Ah Kh", {"action": "RAISE"})
            recorder = SessionRecorder(root / "sessions")

            result = recorder.record_live_analysis(
                image_path=str(image),
                history_file=SimpleNamespace(path=str(history)),
                window=WinamaxWindow(1, 2, "Table", True, (0, 0, 100, 100)),
                ocr_snapshot=ocr,
                live_snapshot=live,
                elapsed_seconds=1.23456,
                ocr_profile="live",
            )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(Path(result.image_path).exists())
            payload = json.loads(Path(result.metadata_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "live_hero_turn_audit")
            self.assertEqual(payload["timing"]["full_analysis_seconds"], 1.2346)
            self.assertEqual(payload["live_snapshot"]["hero_cards"], "Ah Kh")
            self.assertIn("HandId: #123", payload["history_hand"])
            self.assertEqual(payload["hand_link"]["hand_id"], "123")
            self.assertEqual(payload["hand_link"]["outcome"], "won")
            self.assertIn("summary", payload["hand_link"]["actions_by_street"])


if __name__ == "__main__":
    unittest.main()
