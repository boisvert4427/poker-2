from pathlib import Path
from PIL import Image, ImageDraw
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from poker_tracker.config import load_calibration
from poker_tracker.ocr import _scaled_rect

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "sessions" / "20260412_114742"
OUT = ROOT / "data" / "ocr_dataset" / "unseen_batch_04_overview.png"
files = sorted(SESSION.glob("snapshot_*.png"))[30:40]
zones = load_calibration()["zones"]
sheet = Image.new("RGB", (700, len(files) * 170), "white")
draw = ImageDraw.Draw(sheet)
for i, path in enumerate(files):
    with Image.open(path).convert("RGB") as image:
        hero = image.crop(_scaled_rect(image.width, image.height, *zones["hero"]))
        board = image.crop(_scaled_rect(image.width, image.height, *zones["board"]))
        hero.thumbnail((230, 150)); board.thumbnail((430, 150))
        y = i * 170
        sheet.paste(hero, (0, y)); sheet.paste(board, (240, y))
        draw.text((3, y + 152), path.stem.replace("snapshot_2026-04-12T", ""), fill="black")
sheet.save(OUT)
print(OUT)
