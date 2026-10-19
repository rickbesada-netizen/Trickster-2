"""Real-browser test of multi-page + scroll plans. Uses Playwright's Chromium in place of
patchright and the REAL launcher._wait_until_closed / command queue / scroll code.
Run: python tests/test_plan_pages.py"""
import json
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CHROME = next((c for c in ["/opt/pw-browsers/chromium-1194/chrome-linux/chrome", "/opt/pw-browsers/chromium/chrome-linux/chrome"]
               if Path(c).exists()), None)
try:
    import playwright.sync_api as _pw
    sys.modules.setdefault("patchright", types.ModuleType("patchright"))
    sys.modules["patchright.sync_api"] = _pw
    sys.modules["patchright"].sync_api = _pw
    import launcher
except Exception as e:  # pragma: no cover
    launcher = None
    IMPORT_ERR = e

import app_api
import plan_runner

LOG = {"pages": [], "scroll": {}, "keys": [], "typed": [], "loaded": 0.0}


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/beacon":
            q = parse_qs(u.query)
            page, y = q["p"][0], float(q["y"][0])
            LOG["scroll"][page] = max(LOG["scroll"].get(page, 0), y)
            self.send_response(204); self.end_headers(); return
        if u.path == "/key":
            q = parse_qs(u.query)
            LOG["keys"].append((q["k"][0], time.time()))
            self.send_response(204); self.end_headers(); return
        if u.path == "/typed":
            LOG["typed"].append(parse_qs(u.query, keep_blank_values=True)["v"][0])
            self.send_response(204); self.end_headers(); return
        if u.path == "/keys":
            LOG["loaded"] = time.time()
            body = ("<html><body><input id=t autofocus><div style='height:3000px'>keys</div><script>"
                    "addEventListener('keydown',e=>{if(e.key.length>1||e.key==' ')(new Image()).src='/key?k='+encodeURIComponent(e.key)});"
                    "document.getElementById('t').addEventListener('keydown',()=>{});"
                    "setInterval(()=>(new Image()).src='/typed?v='+encodeURIComponent(document.getElementById('t').value),500)"
                    "</script></body></html>").encode()
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        name = u.path.strip("/") or "root"
        LOG["pages"].append(name)
        body = (f"<html><body style='margin:0'><div style='height:4000px'>page {name}</div>"
                f"<script>addEventListener('scroll',()=>(new Image()).src='/beacon?p={name}&y='+scrollY)</script>"
                "</body></html>").encode()
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


def make_launcher():
    def load_profile(path):
        return json.loads(Path(path).read_text())

    def launch(profile, headless=False, check_mode=False, debug_port=None, display_number=None, cloud=None,
               stop_event=None, start_url=None, ready_event=None, commands=None):
        with _pw.sync_playwright() as p:
            b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
            page = b.new_page(viewport={"width": 800, "height": 600})
            page.goto(start_url)
            if ready_event:
                ready_event.set()
            launcher._wait_until_closed(page, stop_event, commands)
            b.close()

    return types.SimpleNamespace(load_profile=load_profile, launch=launch)


@unittest.skipUnless(CHROME and launcher, "needs playwright + chromium")
class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"127.0.0.1:{cls.srv.server_address[1]}"
        cls.tmp = Path(tempfile.mkdtemp())
        pd = cls.tmp / "profiles"
        pd.mkdir()
        for i in range(1, 5):
            n = f"profile_{i:03d}_windows_desktop"
            (pd / f"{n}.json").write_text(json.dumps({"profile_id": n}))
        files = lambda: sorted(pd.glob("*.json"))
        cls.runner = app_api.ProfileRunner(make_launcher(), files, lambda: None)
        cls.plan = plan_runner.PlanRunner(cls.runner, files)

    @classmethod
    def tearDownClass(cls):
        cls.plan.stop()
        cls.runner.close_all(wait=5)
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def wait_done(self, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            if not self.plan.status()["active"]:
                return
            time.sleep(0.3)
        self.fail("plan didn't finish")

    def test_several_pages_in_order_with_scroll_only_where_asked(self):
        LOG["pages"].clear(); LOG["scroll"].clear()
        b = self.base
        r = self.plan.run([
            {"no": "2", "url": f"http://{b}/a", "seconds": 8, "scroll": True},
            {"no": "2", "url": f"http://{b}/b", "seconds": 5, "scroll": False},
            {"no": "2", "url": f"http://{b}/c", "seconds": 8, "scroll": True},
            {"no": "3", "url": f"http://{b}/d", "seconds": 5, "scroll": False},
        ], "together")
        self.assertTrue(r["ok"], r)
        time.sleep(4)
        st = self.plan.status()["items"]
        self.assertEqual([i["pages_total"] for i in st], [3, 1])
        self.wait_done()
        self.assertEqual([i["state"] for i in self.plan.status()["items"]], ["done", "done"])
        # profile 2 visited a, b, c in that order (profile 3 only d)
        two = [p for p in LOG["pages"] if p in ("a", "b", "c")]
        self.assertEqual(two, ["a", "b", "c"])
        self.assertEqual([p for p in LOG["pages"] if p == "d"], ["d"])
        # scrolled the pages it was told to - nearly to the bottom (4000px page, 600px window => max 3400)
        self.assertGreater(LOG["scroll"].get("a", 0), 3000)
        self.assertGreater(LOG["scroll"].get("c", 0), 3000)
        # ...and not the ones it wasn't
        self.assertNotIn("b", LOG["scroll"])
        self.assertNotIn("d", LOG["scroll"])
        self.assertEqual(self.runner.opened(), [])

    def test_scheduled_keys_and_text_fire_at_their_seconds(self):
        LOG["keys"].clear(); LOG["typed"].clear()
        r = self.plan.run([{"no": "1", "url": f"http://{self.base}/keys", "seconds": 14, "scroll": False, "actions": [
            {"at": "9", "type": "text", "value": "hello world"},
            {"at": "3", "type": "key", "value": "Down arrow", "repeat": "2"},
            {"at": "6", "type": "key", "value": "Page Down", "repeat": 1},
        ]}], "one_by_one")
        self.assertTrue(r["ok"], r)
        self.wait_done()
        t0 = LOG["loaded"]
        keys = [(k, round(t - t0, 1)) for k, t in LOG["keys"] if k != " "]  # " " = the space inside the typed text
        names = [k for k, _ in keys]
        self.assertEqual(names, ["ArrowDown", "ArrowDown", "PageDown"], keys)
        self.assertGreaterEqual(keys[0][1], 3.0)   # not before its second
        self.assertLess(keys[0][1], 6.0)
        self.assertGreaterEqual(keys[2][1], 6.0)
        self.assertLess(keys[2][1], 9.0)
        self.assertIn("hello world", LOG["typed"])
        # typing hadn't happened before the 9 second mark
        self.assertEqual(LOG["typed"][0], "")

    def test_bad_actions_are_rejected_with_plain_messages(self):
        base = {"no": "1", "url": "example.com", "seconds": 20}
        for acts, word in [
            ([{"at": "25", "type": "key", "value": "Space"}], "between"),
            ([{"at": "x", "type": "key", "value": "Space"}], "second"),
            ([{"at": "5", "type": "key", "value": "F13"}], "unknown key"),
            ([{"at": "5", "type": "text", "value": ""}], "text"),
            ([{"at": "5", "type": "text", "value": "a" * 400}], "text"),
            ([{"at": "5", "type": "key", "value": "Space", "repeat": 99}], "repeat"),
            ([{"at": "5", "type": "wiggle", "value": "x"}], "pick"),
        ]:
            r = self.plan.run([{**base, "actions": acts}])
            self.assertFalse(r["ok"], acts)
            self.assertIn(word, " ".join(r.get("problems") or [r["message"]]), acts)

    def test_stop_during_scroll(self):
        LOG["pages"].clear(); LOG["scroll"].clear()
        self.plan.run([{"no": "4", "url": f"http://{self.base}/z", "seconds": 120, "scroll": True}], "one_by_one")
        time.sleep(5)
        self.assertEqual(len(self.runner.opened()), 1)
        t0 = time.time()
        self.plan.stop()
        self.wait_done(40)
        self.assertLess(time.time() - t0, 35)
        self.assertEqual(self.runner.opened(), [])
        self.assertEqual(self.plan.status()["items"][0]["state"], "stopped")


if __name__ == "__main__":
    unittest.main(verbosity=2)
