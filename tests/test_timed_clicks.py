"""Offline tests for automatic click actions in Trickster Timed Plan."""
import unittest
from unittest.mock import patch
import plan_runner


class ClickActionsTest(unittest.TestCase):
    def test_click_selector_and_repeat_interval(self):
        items, error = plan_runner.clean_actions([
            {"at": 1, "type": "click", "value": "button.next", "interval": 5}
        ], seconds=30)
        self.assertIsNone(error)
        self.assertEqual(items, [{"at": 1.0, "type": "click", "value": "button.next", "interval": 5.0}])

    def test_rejects_bad_intervals_and_missing_selector(self):
        for bad in ["-1", "1", "3601", "not a number"]:
            _, err = plan_runner.clean_actions([
                {"at": 2, "type": "click", "value": "button.next", "interval": bad}
            ], seconds=25)
            self.assertIsNotNone(err, bad)
        _, err = plan_runner.clean_actions([
            {"at": 2, "type": "click", "value": " ", "interval": 2}
        ], seconds=25)
        self.assertIn("selector", err)

    def test_existing_key_actions_unchanged(self):
        items, error = plan_runner.clean_actions([
            {"at": 1, "type": "key", "value": "Shift+N", "repeat": 1}
        ], seconds=10)
        self.assertIsNone(error)
        self.assertEqual(items[0]["value"], "Shift+N")

    def test_repeating_clicks_happen_until_end(self):
        clock = [100.0]
        clicks = []
        class FakeLocator:
            @property
            def first(self):
                return self
            def click(self, timeout=None):
                clicks.append(clock[0])
        class FakePage:
            def locator(self, selector):
                self_selector = selector
                assert self_selector == "button.next"
                return FakeLocator()
            def wait_for_timeout(self, millis):
                clock[0] += millis / 1000
        fn = plan_runner.page_script(
            7, False, [{"at": 1, "type": "click", "value": "button.next", "interval": 2}])
        with patch.object(plan_runner.time, "monotonic", side_effect=lambda: clock[0]):
            fn(FakePage(), None)
        self.assertEqual(len(clicks), 3)
        self.assertTrue(100.8 <= clicks[0] <= 101.4)

    def test_stop_event_prevents_further_clicks(self):
        class AlreadyStopped:
            def is_set(self):
                return True
        class FakePage:
            def locator(self, selector):
                raise AssertionError("Click should never happen after stop")
        fn = plan_runner.page_script(30, False,
                                     [{"at": 1, "type": "click", "value": "button.next", "interval": 2}])
        fn(FakePage(), AlreadyStopped())


if __name__ == "__main__":
    unittest.main()
