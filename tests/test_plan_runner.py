"""Run: python tests/test_plan_runner.py (uses real headless Chromium as the stand-in browser)"""
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app_api
import plan_runner
import test_app_api as t


class Plan(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pdir = self.tmp / "profiles"
        self.pdir.mkdir()
        for i in range(1, 7):
            n = f"profile_{i:03d}_windows_desktop"
            (self.pdir / f"{n}.json").write_text(json.dumps({"profile_id": n}))
        files = lambda: sorted(self.pdir.glob("*.json"))
        self.runner = app_api.ProfileRunner(t.make_fake_launcher(self.tmp), files, lambda: None)
        self.plan = plan_runner.PlanRunner(self.runner, files)
        t.FakeLauncher.started_urls.clear()

    def tearDown(self):
        self.plan.stop()
        self.runner.close_all(wait=5)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait_done(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            if not self.plan.status()["active"]:
                return
            time.sleep(0.2)
        self.fail("plan didn't finish")

    def test_validation(self):
        bad = [
            [{"no": "", "url": "example.com", "seconds": 10}],
            [{"no": "2", "url": "not a site", "seconds": 10}],
            [{"no": "2", "url": "example.com", "seconds": 1}],
            [{"no": "99", "url": "example.com", "seconds": 10}],
            [],
        ]
        for steps in bad:
            r = self.plan.run(steps)
            self.assertFalse(r["ok"], steps)
        self.assertFalse(self.plan.status()["active"])

    def test_same_profile_on_several_rows_becomes_pages_of_one_visit(self):
        items, problems = self.plan._expand([
            {"no": "2", "url": "a.example.com", "seconds": 6, "scroll": True},
            {"no": "3", "url": "x.example.com", "seconds": 5},
            {"no": "2", "url": "b.example.com", "seconds": 7},
        ])
        self.assertEqual(problems, [])
        self.assertEqual([i["no"] for i in items], [2, 3])
        self.assertEqual([(p["url"], p["seconds"], p["scroll"]) for p in items[0]["pages"]],
                         [("https://a.example.com", 6, True), ("https://b.example.com", 7, False)])

    def test_url_normalising(self):
        self.assertEqual(plan_runner.normalise_url("example.com/x"), "https://example.com/x")
        self.assertIsNone(plan_runner.normalise_url("javascript:alert(1)"))
        self.assertIsNone(plan_runner.normalise_url("file:///etc/passwd"))

    def test_one_by_one_runs_in_order_with_own_urls_and_times(self):
        r = self.plan.run([{"no": "2", "url": "alpha.example.com", "seconds": 6},
                           {"no": "5", "url": "https://beta.example.com/page", "seconds": 5}], "one_by_one")
        self.assertTrue(r["ok"], r)
        time.sleep(2)
        st = self.plan.status()["items"]
        self.assertEqual([i["state"] for i in st], ["running", "waiting"])  # second hasn't started yet
        self.assertEqual(len(self.runner.opened()), 1)
        t0 = time.time()
        self.wait_done()
        self.assertEqual([i["state"] for i in self.plan.status()["items"]], ["done", "done"])
        self.assertEqual(self.runner.opened(), [])  # everything closed afterwards
        self.assertEqual(t.FakeLauncher.started_urls, [("profile_002_windows_desktop", "https://alpha.example.com"),
                                                      ("profile_005_windows_desktop", "https://beta.example.com/page")])

    def test_together_runs_at_once_and_shorter_one_closes_first(self):
        self.plan.run([{"no": "1", "url": "a.example.com", "seconds": 12},
                       {"no": "3", "url": "b.example.com", "seconds": 5}], "together")
        time.sleep(3)
        self.assertEqual(len(self.runner.opened()), 2)  # both open together
        time.sleep(5)
        self.assertEqual([e["no"] for e in self.runner.opened()], [1])  # the 5s one already closed, the 12s one still open
        self.wait_done()
        self.assertEqual(self.runner.opened(), [])

    def test_range_in_one_row_and_stop(self):
        self.plan.run([{"no": "1-3", "url": "a.example.com", "seconds": 60}], "together")
        time.sleep(3)
        self.assertEqual(len(self.runner.opened()), 3)
        self.plan.stop()
        self.wait_done(40)
        self.assertEqual(self.runner.opened(), [])
        self.assertTrue(all(i["state"] == "stopped" for i in self.plan.status()["items"]))

    def test_user_closing_early_is_fine(self):
        self.plan.run([{"no": "4", "url": "a.example.com", "seconds": 30}], "one_by_one")
        time.sleep(2.5)
        self.runner.close_all(wait=10)
        self.wait_done(15)
        it = self.plan.status()["items"][0]
        self.assertEqual(it["state"], "done")
        self.assertIn("early", it["note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
