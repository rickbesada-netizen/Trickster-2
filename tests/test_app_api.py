"""End-to-end test of the built-in API using a REAL headless Chromium with a
remote-debugging port, standing in for launcher.launch(). Run from the
project root:  python tests/test_app_api.py"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app_api

CHROME = None
for cand in ["/opt/pw-browsers/chromium-1194/chrome-linux/chrome", "/opt/pw-browsers/chromium/chrome-linux/chrome"]:
    if Path(cand).exists():
        CHROME = cand
        break

TOKEN = "t" * 32


class FakeLauncher(types.SimpleNamespace):
    started_urls = []
    ignore_stop = False  # True = pretend the launching thread never notices the stop flag


def make_fake_launcher(tmp):
    def load_profile(path):
        return json.loads(Path(path).read_text())

    def launch(profile, headless=False, check_mode=False, debug_port=None, display_number=None, cloud=None, stop_event=None,
               start_url=None, ready_event=None, commands=None):
        d = Path(tmp) / "ud" / profile["profile_id"]
        d.mkdir(parents=True, exist_ok=True)
        args = [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={d}", "about:blank"]
        FakeLauncher.started_urls.append((profile["profile_id"], start_url))
        if debug_port:
            args.append(f"--remote-debugging-port={debug_port}")
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        if ready_event is not None:
            ready_event.set()
        while proc.poll() is None:
            if stop_event is not None and stop_event.is_set() and not FakeLauncher.ignore_stop:
                proc.terminate()
            time.sleep(0.1)

    return FakeLauncher(load_profile=load_profile, launch=launch)


@unittest.skipUnless(CHROME, "no chromium available")
class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.pdir = cls.tmp / "profiles"
        cls.pdir.mkdir()
        names = ["profile_001_android_tablet", "profile_001_windows_desktop", "profile_002_macos_laptop",
                 "profile_003_windows_desktop"]
        for n in names:
            (cls.pdir / f"{n}.json").write_text(json.dumps({"profile_id": n, "group": "g1" if n.endswith("laptop") else "",
                                                           "proxy": {"server": "http://your-proxy-host:1", "username": "", "password": ""}}))
        files = lambda: sorted(cls.pdir.glob("*.json"))
        cls.assigned = []

        def describe(path, no):
            d = json.loads(path.read_text())
            return {"no": no, "profile_id": d["profile_id"], "name": d["profile_id"], "group": d.get("group") or None,
                    "proxy_configured": "your-proxy-host" not in d["proxy"]["server"]}

        def bulk(text):
            cls.assigned.append(text)
            return {"ok": True, "message": "Assigned", "details": ["x"], "skipped": []}

        runner = app_api.ProfileRunner(make_fake_launcher(cls.tmp), files, lambda: None)
        api = app_api.LocalApi(runner, files, describe, bulk)
        cls.runner = runner
        cls.server = app_api.LocalApiServer(api, 0, lambda: TOKEN)
        cls.server.start()
        cls.base = f"http://127.0.0.1:{cls.server.port}/api/v2/"

    @classmethod
    def tearDownClass(cls):
        try:
            cls.runner and [cls.runner.close(e["profile_id"], wait=5) for e in cls.runner.opened()]
        except Exception:
            pass
        cls.server.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, route, body=None, token=TOKEN, headers=None, method="POST"):
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        h.update(headers or {})
        req = urllib.request.Request(self.base + route, data=json.dumps(body or {}).encode() if method == "POST" else None,
                                     headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    # ---- security ----
    def test_auth_and_browser_guards(self):
        self.assertEqual(self.call("ping", token=None)[0], 401)
        self.assertEqual(self.call("ping", token="wrong" * 8)[0], 401)
        self.assertEqual(self.call("ping", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.call("ping", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.call("ping", method="OPTIONS")[0], 403)
        st, body = self.call("ping", method="GET")
        self.assertEqual((st, body["error"]["code"]), (200, 0))
        st, _ = self.call("ping", token=None, headers={"X-API-Key": TOKEN})
        self.assertEqual(st, 200)

    def test_list_by_no_and_name(self):
        st, b = self.call("profile-list", {"limit": 2})
        self.assertEqual(b["data"]["total"], 4)
        self.assertEqual([r["no"] for r in b["data"]["list"]], [1, 2])
        st, b = self.call("profile-list", {"group": "g1"})
        self.assertEqual([r["profile_id"] for r in b["data"]["list"]], ["profile_002_macos_laptop"])

    def test_errors(self):
        self.assertNotEqual(self.call("profile-open", {"profile_id": 99})[1]["error"]["code"], 0)
        self.assertNotEqual(self.call("profile-open", {})[1]["error"]["code"], 0)
        self.assertNotEqual(self.call("profile-open", {"profile_id": "1-2"})[1]["error"]["code"], 0)  # two profiles, single call
        self.assertEqual(self.call("nope")[0], 404)

    def test_proxy_endpoints(self):
        st, b = self.call("proxy-bulk-assign", {"text": "3,h.com:1:u:p"})
        self.assertEqual(b["error"]["code"], 0)
        st, b = self.call("profile-update-proxy", {"profile_id": 2, "proxy": "h.com:5:u:p"})
        self.assertEqual(b["data"]["server"], "http://h.com:5")
        self.assertEqual(self.assigned[-1], "2,h.com:5:u:p")

    # ---- the real thing: open -> drive over CDP -> close ----
    def test_open_cdp_close(self):
        st, b = self.call("profile-open", {"profile_id": 3})  # NO. 3 = profile_002_macos_laptop
        self.assertEqual(b["error"]["code"], 0, b)
        d = b["data"]
        self.assertEqual((d["profile_id"], d["no"]), ("profile_002_macos_laptop", 3))
        self.assertTrue(d["ws"].startswith("ws://127.0.0.1:"))
        # CDP really answers
        with urllib.request.urlopen(f"http://127.0.0.1:{d['debugging_port']}/json/version", timeout=5) as r:
            self.assertIn("Browser", json.loads(r.read()))
        # opening again returns the same browser instead of launching a second
        st, b2 = self.call("profile-open", {"no": 3})
        self.assertEqual(b2["data"]["debugging_port"], d["debugging_port"])
        st, b = self.call("profile-opened-list")
        self.assertEqual([e["no"] for e in b["data"]["list"]], [3])
        st, b = self.call("profile-list", {"name": "macos"})
        self.assertTrue(b["data"]["list"][0]["is_open"])
        # close
        st, b = self.call("profile-close", {"profile_id": "profile_002_macos_laptop"})
        self.assertEqual(b["error"]["code"], 0, b)
        time.sleep(0.5)
        self.assertEqual(self.call("profile-opened-list")[1]["data"]["list"], [])
        with self.assertRaises(Exception):
            urllib.request.urlopen(f"http://127.0.0.1:{d['debugging_port']}/json/version", timeout=2)
        # closing something not open
        self.assertEqual(self.call("profile-close", {"profile_id": 3})[1]["error"]["code"], 1009)

    def test_gui_style_open_without_port_can_still_be_closed(self):
        path = sorted(self.pdir.glob("*.json"))[3]
        entry = self.runner.start(path, source="gui", with_cdp=False)
        self.assertIsNone(entry["port"])
        self.assertIn(entry["file"], [e["file"] for e in self.runner.opened()])
        self.assertTrue(self.runner.close(entry["profile_id"]))
        time.sleep(0.3)
        self.assertEqual(self.runner.opened(), [])

    def test_close_falls_back_to_chromium_quit_if_stop_flag_ignored(self):
        FakeLauncher.ignore_stop = True
        try:
            path = sorted(self.pdir.glob("*.json"))[2]
            entry = self.runner.start(path, source="api", with_cdp=True)
            self.assertTrue(self.runner.close(entry["profile_id"], wait=10))
            time.sleep(0.5)
            self.assertEqual(self.runner.opened(), [])
        finally:
            FakeLauncher.ignore_stop = False

    def test_batch_open_and_close_all(self):
        st, b = self.call("profile-open-batch", {"profiles": ["1-2", 4]})
        self.assertEqual(b["data"]["opened"], 3, b)
        self.assertEqual(sorted(r["no"] for r in b["data"]["results"]), [1, 2, 4])
        st, b = self.call("profile-close-all")
        self.assertEqual(len(b["data"]["closed"]), 3, b)
        time.sleep(0.5)
        self.assertEqual(self.call("profile-opened-list")[1]["data"]["list"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
