from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

from poker_tracker.local_snapshot_analysis import _detect_cards_visible


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "ocr_dataset"
FIELDS = [
    "top_left_cards_visible",
    "top_right_cards_visible",
    "left_cards_visible",
    "right_cards_visible",
]


def features(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read {path}")
    image = cv2.resize(image, (16, 16), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    flat = rgb.reshape(-1)
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    stats = np.array([
        red.mean(), green.mean(), blue.mean(),
        red.std(), green.std(), blue.std(),
        np.mean((red > 0.45) & (red > green * 1.15) & (red > blue * 1.15)),
        np.mean((red > 0.70) & (green > 0.70) & (blue > 0.70)),
        np.mean((red + green + blue) / 3.0 > 0.62),
    ], dtype=np.float32)
    return np.concatenate([flat, stats])


def main() -> None:
    labels = json.loads((DATASET / "crop_labels.json").read_text(encoding="utf-8"))
    records = [row for field in FIELDS for row in labels[field]]
    train = [row for row in records if row["split"] == "train"]
    validation = [row for row in records if row["split"] == "validation"]
    test = [row for row in records if row["split"] == "test"]

    train_x = np.vstack([features(ROOT / row["image"]) for row in train])
    classes = ["not_visible", "visible"]
    centroids = {
        label: train_x[[row["label"] == label for row in train]].mean(axis=0).tolist()
        for label in classes
    }

    def evaluate(rows: list[dict]) -> float:
        if not rows:
            return 0.0
        start = time.perf_counter()
        correct = 0
        for row in rows:
            vector = features(ROOT / row["image"])
            predicted = min(classes, key=lambda label: np.linalg.norm(vector - np.array(centroids[label])))
            correct += predicted == row["label"]
        elapsed = time.perf_counter() - start
        print(f"{rows[0]['split']}: {correct}/{len(rows)} accuracy={correct / len(rows):.3f} elapsed={elapsed:.3f}s")
        return correct / len(rows)

    evaluate(validation)
    evaluate(test)

    def evaluate_rule(rows: list[dict]) -> float:
        if not rows:
            return 0.0
        correct = 0
        uncertain = 0
        for row in rows:
            predicted = _detect_cards_visible(str(ROOT / row["image"]))
            uncertain += predicted == "uncertain"
            correct += predicted == row["label"]
        accuracy = correct / len(rows)
        print(
            f"{rows[0]['split']} rule: {correct}/{len(rows)} "
            f"accuracy={accuracy:.3f} uncertain={uncertain}"
        )
        return accuracy

    evaluate_rule(validation)
    evaluate_rule(test)
    model = {"type": "nearest_centroid", "classes": classes, "centroids": centroids}
    (DATASET / "visibility_model.json").write_text(
        json.dumps(model, indent=2), encoding="utf-8"
    )
    print(f"MODEL={DATASET / 'visibility_model.json'}")


if __name__ == "__main__":
    main()
