"""Offline coverage for Timed Plan combination keys and script syntax."""
import unittest
import plan_runner


class ShortcutTests(unittest.TestCase):
    def test_standard_playback_shortcuts(self):
        self.assertEqual(plan_runner.normalise_shortcut("Shift+N"), "Shift+N")
        self.assertEqual(plan_runner.normalise_shortcut("Shift+P"), "Shift+P")
        self.assertEqual(plan_runner.normalise_shortcut("K"), "K")
        self.assertEqual(plan_runner.normalise_shortcut("ctrl + shift + n"), "Control+Shift+N")
        self.assertEqual(plan_runner.normalise_shortcut("Ctrl+ArrowRight"), "Control+ArrowRight")

    def test_previous_keys_still_work(self):
        self.assertEqual(plan_runner.normalise_shortcut("Down arrow"), "ArrowDown")
        self.assertEqual(plan_runner.normalise_shortcut("Shift+Tab"), "Shift+Tab")
        self.assertEqual(plan_runner.normalise_shortcut("Page Down"), "PageDown")

    def test_invalid_shortcuts_rejected(self):
        for key in ["", "Shift+", "Shift+Shift+N", "Ctrl+Alt+", "Ctrl+NoSuchKey",
                    "Ctrl+Shift+N+P", "Ctrl++N"]:
            self.assertIsNone(plan_runner.normalise_shortcut(key), key)
        actions, issue = plan_runner.clean_actions(
            [{"at": 2, "type": "key", "value": "Shift+Shift+N", "repeat": 1}], 10)
        self.assertEqual(actions, [])
        self.assertIn("unknown key", issue)

    def test_action_normalized(self):
        actions, issue = plan_runner.clean_actions(
            [{"at": 2, "type": "key", "value": "shift + n", "repeat": 2}], 10)
        self.assertIsNone(issue)
        self.assertEqual(actions[0]["value"], "Shift+N")
        self.assertEqual(actions[0]["repeat"], 2)

    def test_paste_script_supports_shortcuts(self):
        result = plan_runner.parse_script(
            "151 | example.com/playlist | 60 | at 10 press Shift+N; at 30 press Ctrl+ArrowRight")
        self.assertTrue(result["ok"], result)
        self.assertEqual([a["value"] for a in result["rows"][0]["actions"]],
                         ["Shift+N", "Control+ArrowRight"])

    def test_keyboard_press_dispatch(self):
        class FakeKeyboard:
            def __init__(self):
                self.events = []
            def press(self, key):
                self.events.append(key)
        class FakePage:
            def __init__(self):
                self.keyboard = FakeKeyboard()
            def wait_for_timeout(self, milliseconds):
                pass
        page = FakePage()
        plan_runner._do_action(page, {"type": "key", "value": "Shift+N", "repeat": 2})
        self.assertEqual(page.keyboard.events, ["Shift+N", "Shift+N"])


if __name__ == "__main__":
    unittest.main()
