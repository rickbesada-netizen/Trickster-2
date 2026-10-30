import json, shutil, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app_api
import generate_profiles


class FakeRunner:
    def __init__(self): self.open_ids = set(); self.reset_called = []
    def is_open(self, pid): return pid in self.open_ids
    def info(self, pid): return None
    def opened(self): return [{"profile_id": p, "source": "api"} for p in self.open_ids]
    def reset(self, pid): self.reset_called.append(pid); return True
    def submit(self, pid, fn): return None


class MoreApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pdir = self.tmp / "profiles"; self.udd = self.pdir / "user_data"
        generate_profiles.generate(3, output_dir=str(self.pdir), seed=3)
        self.runner = FakeRunner()
        self.api = app_api.LocalApi(self.runner, self.files, lambda p, n: {"profile_id": p.stem, "no": n},
                                    lambda t: {"ok": True})
        self.api.configure(self.pdir, self.udd)

    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)
    def files(self): return sorted(p for p in self.pdir.glob("*.json") if not p.stem.endswith("_state"))
    def call(self, route, **body): return self.api.dispatch(route, body)

    def test_create_copy_update_delete(self):
        r = self.call("profile-create", count=2, group="Clients", url="example.com")
        self.assertEqual(len(r["created"]), 2)
        self.assertEqual(len(self.files()), 5)
        d = json.loads((self.pdir / f"{r['created'][0]}.json").read_text())
        self.assertEqual((d["group"], d["start_url"]), ("Clients", "example.com"))
        c = self.call("profile-copy", profile_id=1)
        self.assertEqual(len(self.files()), 6)
        orig = json.loads(self.files()[0].read_text()); cp = json.loads((self.pdir / f"{c['created'][0]}.json").read_text())
        self.assertNotEqual(orig["canvas_seed"], cp["canvas_seed"]); self.assertEqual(orig["user_agent"], cp["user_agent"])
        u = self.call("profile-update", profile_id=2, group="VIP", locale="en-AU")
        self.assertEqual(sorted(u["updated"]), ["group", "locale"])
        self.assertEqual(json.loads(self.files()[1].read_text())["group"], "VIP")
        with self.assertRaises(app_api.ApiError):
            self.call("profile-update", profile_id=2, user_agent="x")
        d = self.call("profile-delete", profile_id=[1, 2])
        self.assertEqual(len(d["deleted"]), 2); self.assertEqual(len(self.files()), 4)
        (self.udd / d["deleted"][0]).mkdir(parents=True)
        self.assertEqual(self.call("empty-recycle-bin")["removed"], 2)
        self.assertFalse((self.udd / d["deleted"][0]).exists())

    def test_cannot_change_an_open_profile(self):
        pid = self.files()[0].stem; self.runner.open_ids.add(pid)
        for route in ("profile-delete", "profile-random-fingerprint-configuration", "profile-clear-cache"):
            with self.assertRaises(app_api.ApiError) as cm:
                self.call(route, profile_id=1)
            self.assertEqual(cm.exception.code, 2009)

    def test_random_fingerprint_keeps_identity(self):
        path = self.files()[0]; before = json.loads(path.read_text())
        self.call("profile-update", profile_id=1, group="G")
        r = self.call("profile-random-fingerprint-configuration", profile_id=1)
        after = json.loads(path.read_text())
        self.assertEqual((after["profile_id"], after["group"], after["proxy"]), (before["profile_id"], "G", before["proxy"]))
        self.assertNotEqual(before["canvas_seed"], after["canvas_seed"])
        self.assertEqual(r["profile_id"], after["profile_id"])

    def test_groups(self):
        self.call("profile-update-groups-in-batches", profile_id=[1, 2], group="A")
        self.assertEqual(self.call("group-list")["list"], [{"name": "A", "count": 2}])
        self.assertEqual(self.call("group-update", group="A", name="B")["renamed"], 2)
        self.assertEqual(self.call("group-delete", group="B")["ungrouped"], 2)
        self.assertEqual(self.call("group-list")["total"], 0)

    def test_clear_cache_and_cookies(self):
        pid = self.files()[0].stem; base = self.udd / pid / "Default"
        (base / "Cache").mkdir(parents=True); (base / "Cache" / "x").write_text("1")
        (base / "Network").mkdir(); (base / "Network" / "Cookies").write_text("c"); (base / "Login Data").write_text("l")
        self.call("profile-clear-cache", profile_id=1)
        self.assertFalse((base / "Cache").exists()); self.assertTrue((base / "Network" / "Cookies").exists())
        self.call("profile-clear-cache-and-cookies", profile_id=1)
        self.assertFalse((base / "Network" / "Cookies").exists()); self.assertTrue((base / "Login Data").exists())
        self.call("profile-clear-saved-user-password", profile_id=1)
        self.assertFalse((base / "Login Data").exists())

    def test_cookies_need_open_profile_and_reset(self):
        with self.assertRaises(app_api.ApiError) as cm:
            self.call("profile-get-cookies", profile_id=1)
        self.assertEqual(cm.exception.code, 2009)
        self.assertTrue(self.call("profile-open-state-reset", profile_id=1)["was_listed"])


if __name__ == "__main__":
    unittest.main()
