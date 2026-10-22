import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import plan_runner as pr


class ScriptTests(unittest.TestCase):
    def test_basic_lines(self):
        r = pr.parse_script("""
# comment
1-20 | instagram.com | 60 | scroll
1-20 | facebook.com | 45 | scroll; at 10 press Down x3; at 30 type hello world
21 | google.com | 30
""")
        self.assertTrue(r["ok"], r["problems"])
        a, b, c = r["rows"]
        self.assertEqual((a["no"], a["url"], a["seconds"], a["scroll"]), ("1-20", "instagram.com", "60", True))
        self.assertEqual(b["actions"][0], {"at": "10", "type": "key", "value": "Down arrow", "repeat": 3})
        self.assertEqual(b["actions"][1], {"at": "30", "type": "text", "value": "hello world", "repeat": 1})
        self.assertFalse(c["scroll"])

    def test_spaces_instead_of_pipes_and_default_seconds(self):
        r = pr.parse_script("5 example.com 40 scroll; at 5 press End\n7 example.org")
        self.assertTrue(r["ok"], r["problems"])
        self.assertEqual(r["rows"][0]["actions"][0]["value"], "End")
        self.assertEqual(r["rows"][1]["seconds"], "30")

    def test_key_names(self):
        for text, label in [("down", "Down arrow"), ("Page Down", "Page Down"), ("pgup", "Page Up"),
                            ("esc", "Escape"), ("Shift+Tab", "Shift+Tab"), ("Down arrow", "Down arrow")]:
            r = pr.parse_script(f"1 | a.com | 30 | at 5 press {text}")
            self.assertTrue(r["ok"], (text, r["problems"]))
            self.assertEqual(r["rows"][0]["actions"][0]["value"], label)

    def test_problems_are_reported_with_line_numbers(self):
        r = pr.parse_script("1 | a.com | abc\n2 | b.com | 30 | at 5 press Banana\njust-one-word\n3 | c.com | 30 | dance")
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["problems"]), 4)
        self.assertTrue(r["problems"][0].startswith("Line 1"))

    def test_empty(self):
        self.assertFalse(pr.parse_script("  \n# only a comment")["ok"])

    def test_rows_pass_the_real_validation(self):
        r = pr.parse_script("1-3 | example.com | 60 | scroll; at 10 press Down x3; at 30 type hi")
        acts, why = pr.clean_actions(r["rows"][0]["actions"], 60)
        self.assertIsNone(why)
        self.assertEqual(len(acts), 2)


if __name__ == "__main__":
    unittest.main()
