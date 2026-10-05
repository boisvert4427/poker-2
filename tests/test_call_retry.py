import unittest

from poker_tracker.live_state import _call_amount_from_center_button


class CallRetryTests(unittest.TestCase):
    def test_keyboard_shortcut_between_amount_and_call(self):
        self.assertEqual(_call_amount_from_center_button("12,5 BB c\nCALL"), 12.5)
        self.assertEqual(_call_amount_from_center_button("64 BB =\nCALL"), 64)

    def test_raise_and_empty_button_are_not_call_amounts(self):
        for text in ("12,5 BB B RAISE TO", "CHECK", "a", "0 BB C CALL"):
            self.assertIsNone(_call_amount_from_center_button(text))
