"""Ad-aware playlist checks: do not interrupt ordinary playback."""
import unittest
from unittest.mock import patch
import playlist_navigation as nav
import plan_runner

class AdAwareTests(unittest.TestCase):
    def test_positive_ad_skips_ad_button(self):
        class Button:
            @property
            def first(self): return self
            def is_visible(self, timeout=None): return True
            def is_enabled(self, timeout=None): return True
            def click(self, timeout=None): page.clicks += 1
        class Page:
            def __init__(self): self.clicks = 0
            def evaluate(self, js): return {"is_ad": True, "reason": "player ad-showing class"}
            def locator(self, selector): return Button()
        page = Page()
        ok, message = nav.skip_ad_or_next(page)
        self.assertTrue(ok)
        self.assertEqual(page.clicks, 1)
        self.assertIn("Skip Ad", message)

    def test_normal_video_never_skipped(self):
        class Page:
            def evaluate(self, js): return {"is_ad": False, "reason": "no ad detected"}
            def locator(self, selector): raise AssertionError("must not click anything")
        with patch.object(nav, "advance", side_effect=AssertionError("never skip normal video")):
            ok, message = nav.skip_ad_or_next(Page())
        self.assertFalse(ok)
        self.assertIn("no ad", message)

    def test_ad_without_skip_button_attempts_next(self):
        class Button:
            @property
            def first(self): return self
            def is_visible(self, timeout=None): return False
        class Page:
            def evaluate(self, js): return {"is_ad": True, "reason": "visible ad overlay"}
            def locator(self, selector): return Button()
        with patch.object(nav, "advance", return_value=(True, "Playlist next: confirmed item changed")) as advance:
            ok, message = nav.skip_ad_or_next(Page())
            self.assertTrue(ok)
            self.assertIn("confirmed", message)
            advance.assert_called_once()

    def test_15_second_configuration_and_validation(self):
        actions, error = plan_runner.clean_actions([
            {"type": "next", "at": 10, "mode": "ad_aware", "interval": 15}
        ], seconds=120)
        self.assertIsNone(error)
        self.assertEqual(actions[0]["interval"], 15)
        self.assertEqual(actions[0]["mode"], "ad_aware")
        _, error = plan_runner.clean_actions([
            {"type": "next", "at": 10, "mode": "ad_aware", "interval": 0}
        ], seconds=120)
        self.assertIn("repeat interval", error)

    def test_negative_signal_on_detector_exception(self):
        class Page:
            def evaluate(self, js): raise RuntimeError("page changed")
        detected, why = nav.ad_status(Page())
        self.assertFalse(detected)
        self.assertIn("unavailable", why)

if __name__ == "__main__":
    unittest.main()
