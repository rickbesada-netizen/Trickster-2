"""Old tabs from a previous session get closed; the main tab stays. Also checks the
bundled extension set (AppBlocker in, Cold Turkey out). Run: python tests/test_stray_tabs.py"""
import json, sys, types, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
CHROME = next((c for c in ["/opt/pw-browsers/chromium-1194/chrome-linux/chrome", "/opt/pw-browsers/chromium/chrome-linux/chrome"] if Path(c).exists()), None)
try:
    import playwright.sync_api as _pw
    sys.modules.setdefault("patchright", types.ModuleType("patchright"))
    sys.modules["patchright.sync_api"] = _pw
    sys.modules["patchright"].sync_api = _pw
    import launcher
except Exception:
    launcher = None


class Stray(unittest.TestCase):
    @unittest.skipUnless(CHROME and launcher, "needs playwright + chromium")
    def test_only_main_tab_survives(self):
        with _pw.sync_playwright() as p:
            b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
            ctx = b.new_context()
            main = ctx.new_page(); main.goto("about:blank")
            for u in ("data:text/html,History", "data:text/html,Settings", "data:text/html,NewTab"):
                ctx.new_page().goto(u)
            self.assertEqual(len(ctx.pages), 4)
            launcher._close_stray_tabs(ctx, main)
            self.assertEqual(ctx.pages, [main])
            b.close()

    def test_bundled_extensions(self):
        ext = Path(__file__).resolve().parent.parent / "extensions"
        self.assertFalse((ext / "Cold_Turkey_Blocker").exists())
        m = json.loads((ext / "AppBlocker_Web_Filter" / "manifest.json").read_text())
        self.assertEqual(m["manifest_version"], 3)
        self.assertEqual(launcher._known_extension_id(str(ext / "AppBlocker_Web_Filter")) if launcher else "bghhcnjlkiacnebfdfkpmihgnlohglci",
                         "bghhcnjlkiacnebfdfkpmihgnlohglci")

    def test_no_polling_close_loop_in_launch(self):
        src = (Path(__file__).resolve().parent.parent / "launcher.py").read_text()
        launch_body = src[src.index("def launch("):src.index("def main(")]
        self.assertNotIn("run_extension_monitor_loop(", launch_body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
