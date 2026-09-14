from __future__ import annotations

import unittest

from PIL import Image, ImageDraw

from poker_tracker.ocr import _bet_marker_visible


class OcrGateTests(unittest.TestCase):
    def test_empty_table_zone_skips_bet_ocr(self):
        crop = Image.new("RGB", (100, 40), (0, 70, 25))
        self.assertFalse(_bet_marker_visible(crop))

    def test_orange_bet_marker_keeps_bet_ocr(self):
        crop = Image.new("RGB", (100, 40), (0, 70, 25))
        ImageDraw.Draw(crop).rectangle((20, 8, 80, 32), fill=(210, 100, 35))
        self.assertTrue(_bet_marker_visible(crop))


if __name__ == "__main__":
    unittest.main()
