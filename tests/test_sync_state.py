"""Logins travel between computers. Run: python tests/test_sync_state.py"""
import sys, types, tempfile, shutil, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "gui"))
for name in ("httpx", "supabase"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["supabase"].create_client = lambda *a, **k: None
sys.modules["supabase"].Client = object
sys.modules["supabase"].ClientOptions = object
import cloud  # noqa: E402

CHROME = next((c for c in ["/opt/pw-browsers/chromium-1194/chrome-linux/chrome", "/opt/pw-browsers/chromium/chrome-linux/chrome"] if Path(c).exists()), None)
try:
    import playwright.sync_api as pw
except Exception:
    pw = None


class FakeBucket:
    def __init__(self, store): self.s = store
    def upload(self, path, data, opts=None): self.s[path] = bytes(data)
    def download(self, path):
        if path not in self.s: raise KeyError(path)
        return self.s[path]

def make_cloud(store):
    c = object.__new__(cloud.CloudSync)
    c.org_id = "org1"
    c.is_signed_in = lambda: True
    c._get_client = lambda: types.SimpleNamespace(storage=types.SimpleNamespace(from_=lambda b: FakeBucket(store)))
    return c


class Sync(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.store = {}
        self.cl = make_cloud(self.store)
    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_state_moves_between_computers_and_only_when_newer(self):
        a, b = self.tmp / "A", self.tmp / "B"
        cookies = [{"name": "SID", "value": "abc", "domain": ".google.com", "path": "/"}]
        cloud.machine_id = lambda: "pc-A"
        self.assertIsNone(self.cl.pull_state("p1", a))                 # nothing saved yet
        self.cl.push_state("p1", a, {"cookies": cookies})
        self.assertIsNone(self.cl.pull_state("p1", a))                 # A already has the newest
        cloud.machine_id = lambda: "pc-B"
        self.assertEqual(self.cl.pull_state("p1", b), cookies)         # B gets A's logins
        newer = cookies + [{"name": "HSID", "value": "x", "domain": ".google.com", "path": "/"}]
        import time; time.sleep(0.01)
        self.cl.push_state("p1", b, {"cookies": newer})
        cloud.machine_id = lambda: "pc-A"
        self.assertEqual(self.cl.pull_state("p1", a), newer)           # back on A: newer copy arrives
        self.assertIsNone(self.cl.pull_state("p1", a))

    def test_other_computers_raw_files_dont_overwrite_this_ones(self):
        a, b = self.tmp / "A", self.tmp / "B"
        (a / "Default").mkdir(parents=True); (a / "Default" / "Cookies").write_text("A-encrypted"); (a / "Local State").write_text("A-key")
        (b / "Default").mkdir(parents=True); (b / "Default" / "Cookies").write_text("B-own"); (b / "Local State").write_text("B-key")
        cloud.machine_id = lambda: "pc-A"
        self.cl.push_session("p1", a)
        cloud.machine_id = lambda: "pc-B"
        self.cl.pull_session("p1", b)
        self.assertEqual((b / "Local State").read_text(), "B-key")           # untouched
        self.assertEqual((b / "Default" / "Cookies").read_text(), "B-own")
        cloud.machine_id = lambda: "pc-A"
        (a / "Default" / "Cookies").write_text("changed"); (a / "Local State").write_text("changed")
        self.cl.pull_session("p1", a)                                        # same computer: restored as before
        self.assertEqual((a / "Default" / "Cookies").read_text(), "A-encrypted")

    @unittest.skipUnless(CHROME and pw, "needs playwright + chromium")
    def test_cookies_really_log_a_second_browser_in(self):
        seen = []
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                if self.path == "/login":
                    self.send_response(200); self.send_header("Set-Cookie", "SID=secret123; Max-Age=3600; Path=/"); self.end_headers(); self.wfile.write(b"ok"); return
                seen.append(self.headers.get("Cookie", "")); self.send_response(200); self.end_headers(); self.wfile.write(b"hi")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            with pw.sync_playwright() as p:
                b1 = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
                c1 = b1.new_context(); c1.new_page().goto(base + "/login")
                state = c1.storage_state(); b1.close()                    # "computer A" closes
                cloud.machine_id = lambda: "pc-A"
                self.cl.push_state("p1", self.tmp / "A", state)
                cloud.machine_id = lambda: "pc-B"
                cookies = self.cl.pull_state("p1", self.tmp / "B")        # "computer B" opens
                b2 = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
                c2 = b2.new_context(); c2.add_cookies(cookies); c2.new_page().goto(base + "/whoami")
                b2.close()
        finally:
            srv.shutdown()
        self.assertIn("SID=secret123", seen[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
