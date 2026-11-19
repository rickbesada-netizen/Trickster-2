"""Offline mobile/desktop playlist navigation checks."""
import threading
import unittest
from unittest.mock import patch
import playlist_navigation as nav
import plan_runner


class Target:
    @property
    def first(self):
        return self
    def __init__(self, callback=None, visible=True):
        self.callback = callback
        self.visible = visible
    def is_visible(self, timeout=None):
        return self.visible
    def is_enabled(self, timeout=None):
        return True
    def click(self, timeout=None):
        if self.callback:
            self.callback()


class FakeVideo:
    @property
    def first(self):
        return self
    def evaluate(self, js, timeout=None):
        return "https://media.example/a.mp4"


class FakePage:
    def __init__(self, mobile=False, has_next=True, changes=True):
        self.url = "https://m.example/watch?v=a&index=1" if mobile else "https://www.example/watch?v=a&index=1"
        self.has_next = has_next
        self.changes = changes
        self.mobile = mobile
        self.clicks = 0
    def _click(self):
        self.clicks += 1
        if self.changes:
            self.url = self.url.replace("v=a&index=1", "v=b&index=2")
    def get_by_role(self, role, name):
        return Target(self._click, visible=self.has_next and role == "button")
    def locator(self, css):
        if css == "video":
            return FakeVideo()
        return Target(self._click, visible=False)


class NavigationTests(unittest.TestCase):
    def test_desktop_next_confirmed(self):
        page = FakePage()
        success, msg = nav.advance(page, confirmation_seconds=0.1)
        self.assertTrue(success, msg)
        self.assertIn("confirmed", msg)
        self.assertEqual(page.clicks, 1)

    def test_real_mobile_next_player_button_is_second_of_pair(self):
        class ButtonPair:
            def __init__(self, owner):
                self.owner = owner
            def count(self):
                return 2
            def nth(self, index):
                assert index == 1, "The second of previous/next buttons is Next"
                return Target(self.owner._click)
        class MobilePlayer(FakePage):
            def __init__(self):
                super().__init__(mobile=True, has_next=False)
                self.url = "https://m.youtube.com/watch?v=a&index=1&list=PLTEST"
            def locator(self, selector):
                if selector == "button.player-middle-controls-prev-next-button":
                    return ButtonPair(self)
                return super().locator(selector)
        page = MobilePlayer()
        result, msg = nav.advance(page, confirmation_seconds=0.1)
        self.assertTrue(result, msg)
        self.assertEqual(page.clicks, 1)
        self.assertIn("mobile player Next", msg)

    def test_mobile_no_next_button_still_returns_diagnostic(self):
        class NoMobileButtons(FakePage):
            def __init__(self):
                super().__init__(mobile=True, has_next=False)
                self.url = "https://m.youtube.com/watch?v=a&list=PLTEST"
            def locator(self, selector):
                if selector == "button.player-middle-controls-prev-next-button":
                    class Zero:
                        def count(self):
                            return 0
                    return Zero()
                return super().locator(selector)
        page = NoMobileButtons()
        result, msg = nav.advance(page, confirmation_seconds=0)
        self.assertFalse(result)
        self.assertIn("mobile player next button pair not found", msg)

    def test_mobile_layout_without_fingerprint_detection(self):
        page = FakePage(mobile=True)
        success, _ = nav.advance(page, confirmation_seconds=0.1)
        self.assertTrue(success)
        self.assertIn("index=2", page.url)

    def test_missing_next_control_reports_failure(self):
        page = FakePage(has_next=False)
        success, message = nav.advance(page, confirmation_seconds=0)
        self.assertFalse(success)
        self.assertIn("no usable Next control", message)

    def test_mobile_playlist_link_fallback_when_player_controls_hidden(self):
        class PlaylistPage(FakePage):
            def __init__(self):
                super().__init__(mobile=True, has_next=False)
                self.marked = False
            def evaluate(self, script):
                self.marked = True
                return {"found": True, "count": 4}
            def locator(self, css):
                if css == '[data-trickster-next-target="1"]':
                    return Target(self._click, visible=self.marked)
                return super().locator(css)
        page = PlaylistPage()
        success, message = nav.advance(page, confirmation_seconds=0.1)
        self.assertTrue(success, message)
        self.assertIn("mobile playlist", message)
        self.assertEqual(page.clicks, 1)

    def test_playlist_fallback_does_not_click_unrelated_suggestions(self):
        class NoPlaylistPage(FakePage):
            def evaluate(self, script):
                return {"found": False, "why": "next playlist link not in current panel"}
        page = NoPlaylistPage(mobile=True, has_next=False)
        success, msg = nav.advance(page, confirmation_seconds=0)
        self.assertFalse(success)
        self.assertEqual(page.clicks, 0)

    def test_click_without_navigation_not_marked_success(self):
        page = FakePage(changes=False)
        success, message = nav.advance(page, confirmation_seconds=0)
        self.assertFalse(success)
        self.assertIn("no item change", message)

    def test_stopped_does_not_click(self):
        stop = threading.Event()
        stop.set()
        page = FakePage()
        success, _ = nav.advance(page, stop)
        self.assertFalse(success)
        self.assertEqual(page.clicks, 0)

    def test_next_interval_and_end_validation(self):
        interval, error = plan_runner.clean_actions(
            [{"type": "next", "at": 2, "mode": "interval", "interval": 15}], 40)
        self.assertIsNone(error)
        self.assertEqual(interval[0]["interval"], 15)
        ended, error = plan_runner.clean_actions(
            [{"type": "next", "at": 2, "mode": "ended", "interval": 0}], 40)
        self.assertIsNone(error)
        self.assertEqual(ended[0]["mode"], "ended")
        _, error = plan_runner.clean_actions(
            [{"type": "next", "at": 2, "mode": "interval", "interval": 0}], 40)
        self.assertIn("repeat interval", error)


if __name__ == "__main__":
    unittest.main()
