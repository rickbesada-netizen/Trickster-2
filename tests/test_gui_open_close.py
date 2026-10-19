"""Tests the main-screen Open by NO. / Close buttons' backend (gui/app.py Api)
with GUI-only modules stubbed out. Run: python tests/test_gui_open_close.py"""
import importlib.util
import json
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Any(types.ModuleType):
    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return Any(n)

    def __call__(self, *a, **k):
        return Any("x")


for name in ["webview", "patchright", "patchright.async_api", "patchright.sync_api", "httpx", "supabase",
             "win32gui", "win32con", "pythoncom", "pywintypes", "win32com", "PIL.ImageDraw"]:
    sys.modules.setdefault(name, Any(name))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))
spec = importlib.util.spec_from_file_location("appmod", ROOT / "gui" / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class FakeCloud:
    def is_signed_in(self):
        return False


class GuiOpenClose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        (cls.tmp / "profiles").mkdir()
        for f in (ROOT / "profiles").glob("profile_*.json"):
            shutil.copy(f, cls.tmp / "profiles" / f.name)
        app.PROFILES_DIR = cls.tmp / "profiles"
        app.WRITABLE_DIR = cls.tmp
        app.CloudSync = FakeCloud
        app.Api._sync_extension_removal_policy = lambda self: None

        launched = []

        def fake_launch(profile, headless=False, check_mode=False, debug_port=None, display_number=None,
                        cloud=None, stop_event=None, start_url=None, ready_event=None, commands=None):
            launched.append((profile["profile_id"], display_number))
            while not stop_event.is_set():
                time.sleep(0.05)

        app.launcher.launch = fake_launch
        cls.launched = launched
        cls.api = app.Api()
        cls.api.api_set_enabled(False)  # no need for the HTTP side here

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_open_close_flow(self):
        files = self.api._profile_files()
        r = self.api.open_profiles("3-5, 14")
        self.assertTrue(r["ok"], r)
        self.assertEqual(sorted(r["opened"]), sorted(f.name for f in [files[2], files[3], files[4], files[13]]))
        time.sleep(0.3)
        self.assertEqual(sorted(self.api.open_files()), sorted(r["opened"]))
        # badge number on each window equals the NO. in the table
        self.assertEqual(sorted(n for _, n in self.launched), [3, 4, 5, 14])
        # table data flags them open
        lp = self.api.list_profiles()
        self.assertEqual([p["number"] for p in lp if p["is_open"]], [3, 4, 5, 14])
        # opening again doesn't start duplicates
        r2 = self.api.open_profiles("3")
        self.assertIn("already open", r2["message"])
        # close one
        r3 = self.api.close_profiles([files[2].name])
        self.assertTrue(r3["ok"])
        time.sleep(0.3)
        self.assertEqual(len(self.api.open_files()), 3)
        # close all
        r4 = self.api.close_all_profiles()
        self.assertIn("Closed 3", r4["message"])
        time.sleep(0.3)
        self.assertEqual(self.api.open_files(), [])
        self.assertEqual(self.api.close_all_profiles()["message"], "No profiles are open.")

    def test_bad_input(self):
        self.assertFalse(self.api.open_profiles("")["ok"])
        self.assertFalse(self.api.open_profiles("999999")["ok"])
        r = self.api.open_profiles("1-40")
        self.assertFalse(r["ok"])
        self.assertIn("25", r["message"])
        self.assertEqual(self.api.open_files(), [])


class StartPage(GuiOpenClose):
    def test_start_page_saved_validated_and_cleared(self):
        f = self.api._profile_files()[0].name
        r = self.api.save_profile_proxy(f, "", "", "", "ads.google.com")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.api.get_profile_proxy(f)["start_url"], "https://ads.google.com")
        bad = self.api.save_profile_proxy(f, "", "", "", "not a website")
        self.assertFalse(bad["ok"])
        self.assertEqual(self.api.get_profile_proxy(f)["start_url"], "https://ads.google.com")  # unchanged
        self.assertTrue(self.api.save_profile_proxy(f, "", "", "", "")["ok"])
        self.assertEqual(self.api.get_profile_proxy(f)["start_url"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
