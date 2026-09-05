from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1] / "sessions" / "20260902_223643"


def main() -> None:
    points = []
    files = sorted(
        path for path in ROOT.glob("snapshot_*.png")
        if not any(tag in path.stem for tag in ("_calibration", "_live_crops", "_crops"))
    )[:64]
    for path in files:
        image = cv2.imread(str(path))
        if image is None:
            continue
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([15, 100, 100]), np.array([40, 255, 255]))
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
        h, w = image.shape[:2]
        candidates = []
        for index in range(1, count):
            x, y, width, height, area = stats[index]
            if 150 <= area <= 6000 and 8 <= width <= 180 and 8 <= height <= 180:
                cx, cy = centroids[index]
                candidates.append((cx / w, cy / h, area))
        if candidates:
            best = max(candidates, key=lambda item: item[2])
            points.append(best[:2])

    groups = defaultdict(list)
    for x, y in points:
        key = (round(x / 0.04), round(y / 0.04))
        groups[key].append((x, y))
    print(f"PNG analyses: {len(files)}")
    print(f"Dealer detecte: {len(points)}")
    for key, values in sorted(groups.items()):
        xs = [v[0] for v in values]
        ys = [v[1] for v in values]
        print(f"groupe={key} n={len(values)} x={min(xs):.3f}-{max(xs):.3f} y={min(ys):.3f}-{max(ys):.3f}")


if __name__ == "__main__":
    main()
