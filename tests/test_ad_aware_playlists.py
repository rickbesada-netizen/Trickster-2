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
        self.assertEqual(actions[0]["interval"], 0)
        self.assertEqual(actions[0]["ad_check_seconds"], 15)
        self.assertEqual(actions[0]["mode"], "ended")
        self.assertTrue(actions[0]["check_ads"])
        converted, error = plan_runner.clean_actions([
            {"type": "next", "at": 10, "mode": "ad_aware", "interval": 0}
        ], seconds=120)
        self.assertIsNone(error)
        self.assertEqual(converted[0]["mode"], "ended")

    def test_separate_user_interval_and_ad_checks(self):
        actions, error = plan_runner.clean_actions([
            {"type": "next", "at": 10, "mode": "interval",
             "interval": 120, "check_ads": True}
        ], seconds=500)
        self.assertIsNone(error)
        self.assertEqual(actions[0]["interval"], 120)
        self.assertEqual(actions[0]["ad_check_seconds"], 15)
        self.assertTrue(actions[0]["check_ads"])

    def test_ad_check_does_not_invoke_next_without_skip(self):
        class Button:
            @property
            def first(self): return self
            def is_visible(self, timeout=None): return False
        class Page:
            def locator(self, selector): return Button()
        with patch.object(nav, "advance", side_effect=AssertionError("never call Next")):
            ok, message = nav.skip_ad_if_available(Page())
        self.assertFalse(ok)
        self.assertIn("no enabled Skip Ad", message)

    def test_visible_skip_button_succeeds_without_ad_overlay(self):
        class Button:
            @property
            def first(self): return self
            def is_visible(self, timeout=None): return True
            def is_enabled(self, timeout=None): return True
            def click(self, timeout=None): self_page.clicks += 1
        class Page:
            def __init__(self): self.clicks=0
            def locator(self, selector): return Button()
        self_page = Page()
        with patch.object(nav, "advance", side_effect=AssertionError("not Next")):
            ok, message = nav.skip_ad_if_available(self_page)
        self.assertTrue(ok)
        self.assertEqual(self_page.clicks, 1)

    def test_ad_poll_does_not_override_user_video_interval(self):
        clock = [0.0]
        ad_checks, advances = [], []
        class Page:
            def wait_for_timeout(self, milliseconds):
                clock[0] += milliseconds / 1000.0
        def playback(_page):
            t = clock[0]
            return {"ready": True, "ended": False, "ad": t < 12,
                    "identity": "video-A", "current_time": max(0, t - 12)}
        def ad_check(*args):
            ad_checks.append(clock[0])
            return False, "Ad check: no enabled Skip Ad button"
        def advance(*args):
            advances.append(clock[0])
            return True, "Playlist next: confirmed item changed"
        action = {"at": 0, "type": "next", "mode": "interval",
                  "interval": 10, "check_ads": True, "ad_check_seconds": 15}
        with patch.object(plan_runner.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(nav, "skip_ad_if_available", side_effect=ad_check), \
             patch.object(nav, "content_playback_status", side_effect=playback), \
             patch.object(nav, "advance", side_effect=advance):
            plan_runner.page_script(34, False, [action])(Page(), None)
        self.assertGreaterEqual(len(ad_checks), 2)
        self.assertTrue(all(b - a >= 14.7 for a, b in zip(ad_checks, ad_checks[1:])))
        self.assertTrue(21.0 <= advances[0] <= 24.0, advances)
        self.assertTrue(all(t > 15 for t in advances))

    def test_negative_signal_on_detector_exception(self):
        class Page:
            def evaluate(self, js): raise RuntimeError("page changed")
        detected, why = nav.ad_status(Page())
        self.assertFalse(detected)
        self.assertIn("unavailable", why)

if __name__ == "__main__":
    unittest.main()
