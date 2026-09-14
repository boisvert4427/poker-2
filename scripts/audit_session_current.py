from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from poker_tracker.live_state import build_live_snapshot
from poker_tracker.local_snapshot_analysis import extract_live_table_facts
from poker_tracker.ocr import run_local_ocr_on_image_with_profile


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/consola.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _compact_result(payload: dict) -> list[str]:
    facts = payload["facts"]
    live = payload["live"]
    board = " ".join(facts.get(f"board_card_{index}", "") for index in range(1, 6)).strip()
    players = ", ".join(live.get("players_in_hand", [])) or "-"
    actions = ", ".join(live.get("available_actions", [])) or "-"
    return [
        f"hero={facts.get('hero_cards', '') or '-'} board={board or '-'} dealer={facts.get('dealer_button', '') or '-'}",
        f"pot={facts.get('pot_value', '') or '-'} turn={live.get('is_hero_turn')} actions={actions}",
        "names: " + " | ".join(f"{seat}={facts.get(seat + '_name', '') or '-'}" for seat in ("top_left", "top_right", "left", "right")),
        "stacks: " + " | ".join(f"{seat}={facts.get(seat + '_stack', '') or '-'}" for seat in ("top_left", "top_right", "left", "right", "hero")),
        "bets: " + " | ".join(f"{seat}={facts.get(seat + '_bet', '') or '-'}" for seat in ("top_left", "top_right", "left", "right", "hero")),
        f"active={players}",
        f"runtime={payload['runtime_seconds']:.2f}s",
    ]


def _make_sheets(results: list[dict], output_dir: Path) -> None:
    thumb_size = (840, 455)
    text_height = 170
    cell_width = 900
    cell_height = thumb_size[1] + text_height
    font = _font(18)
    title_font = _font(20)

    for sheet_index, start in enumerate(range(0, len(results), 10), start=1):
        page_results = results[start : start + 10]
        sheet = Image.new("RGB", (cell_width * 2, cell_height * 5), "white")
        draw = ImageDraw.Draw(sheet)
        for offset, payload in enumerate(page_results):
            column = offset % 2
            row = offset // 2
            origin_x = column * cell_width
            origin_y = row * cell_height
            with Image.open(payload["image"]).convert("RGB") as source:
                preview = ImageOps.contain(source, thumb_size)
            image_x = origin_x + (cell_width - preview.width) // 2
            sheet.paste(preview, (image_x, origin_y))
            text_y = origin_y + thumb_size[1] + 4
            draw.text((origin_x + 8, text_y), Path(payload["image"]).name, fill="black", font=title_font)
            text_y += 27
            for line in _compact_result(payload):
                draw.text((origin_x + 8, text_y), line, fill="black", font=font)
                text_y += 20
            draw.rectangle((origin_x, origin_y, origin_x + cell_width - 1, origin_y + cell_height - 1), outline="#777777", width=2)
        sheet.save(output_dir / f"overview_{sheet_index:02d}.jpg", quality=91)


def main() -> int:
    parser = argparse.ArgumentParser(description="Relance l'OCR actuel sur chaque PNG d'une session.")
    parser.add_argument("session", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    session_dir = args.session.resolve()
    images = sorted(session_dir.glob("snapshot_*.png"))
    if not images:
        print(f"Aucun PNG dans {session_dir}", flush=True)
        return 2

    output_dir = (args.output or (ROOT / "data" / "session_audits" / session_dir.name)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for index, image_path in enumerate(images, start=1):
        started = time.perf_counter()
        snapshot = run_local_ocr_on_image_with_profile(image_path, profile="live")
        facts = extract_live_table_facts(snapshot)
        live_snapshot = build_live_snapshot(None, None, snapshot)
        runtime = time.perf_counter() - started
        payload = {
            "image": str(image_path),
            "runtime_seconds": runtime,
            "facts": facts,
            "live": asdict(live_snapshot) if live_snapshot else {},
            "zones": {
                name: {"text": zone.text, "rect": list(zone.rect)}
                for name, zone in snapshot.zones.items()
            },
        }
        results.append(payload)
        (output_dir / f"{image_path.stem}.current.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[{index:03d}/{len(images):03d}] {image_path.name} {runtime:.2f}s", flush=True)

    summary = {
        "session": str(session_dir),
        "image_count": len(results),
        "average_seconds": sum(item["runtime_seconds"] for item in results) / len(results),
        "maximum_seconds": max(item["runtime_seconds"] for item in results),
        "results": results,
    }
    (output_dir / "current_results.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _make_sheets(results, output_dir)
    print(f"Rapport: {output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
