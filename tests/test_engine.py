"""Own-Chromium downloader, against a local fake snapshot server.
Run: python tests/test_engine.py"""
import io, sys, tempfile, threading, shutil, zipfile, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import chromium_engine as ce

HITS = []
def make_zip():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("chrome-win/chrome.exe", b"MZ fake")
    return b.getvalue()
ZIP = make_zip()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        HITS.append(self.path)
        if self.path.endswith("/LAST_CHANGE"):
            body = b"105"
        elif self.path.endswith("/104/chrome-win.zip"):
            body = ZIP
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

class Engine(unittest.TestCase):
    def test_download_skips_missing_build_and_reuses_install(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        root = Path(tempfile.mkdtemp())
        try:
            self.assertIsNone(ce.installed_exe(root))
            r = ce.ensure(root=root, base=base, log=lambda m: None, windows_only=False)
            self.assertTrue(r["ok"], r)
            self.assertTrue(Path(r["exe"]).exists())
            self.assertEqual(ce.installed_exe(root), r["exe"])
            self.assertIn("/105/chrome-win.zip", HITS)      # tried the newest first
            n = len(HITS)
            r2 = ce.ensure(root=root, base=base, log=lambda m: None, windows_only=False)
            self.assertTrue(r2["ok"]); self.assertEqual(len(HITS), n)   # nothing downloaded twice
        finally:
            srv.shutdown(); shutil.rmtree(root, ignore_errors=True)

    def test_failure_is_reported_not_raised(self):
        r = ce.ensure(root=Path(tempfile.mkdtemp()), base="http://127.0.0.1:1", log=lambda m: None, windows_only=False)
        self.assertFalse(r["ok"]); self.assertIn("Couldn't", r["message"])

    def test_not_windows_is_skipped(self):
        if sys.platform != "win32":
            self.assertFalse(ce.ensure()["ok"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
