import unittest
from pathlib import Path
from unittest.mock import patch
import tempfile
import updater

class UpdateChecks(unittest.TestCase):
    def test_latest_release_detection(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "version.txt").write_text("29")
            release = {"body": "Build 30. Official installer",
                       "assets": [{"name": "TricksterSetup.exe", "browser_download_url":
                                   "https://github.com/rickbesada-netizen/Trickster-2/releases/download/latest/TricksterSetup.exe"}]}
            with patch.object(updater, "_json", return_value=release):
                out = updater.check(root, ignore_cooldown=True)
            self.assertTrue(out["available"])
            self.assertEqual(out["current"], 29)
            self.assertEqual(out["build"], 30)
    def test_same_build(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "version.txt").write_text("30")
            with patch.object(updater, "_json", return_value={"body":"Build 30", "assets":[]}):
                out=updater.check(root, ignore_cooldown=True)
            self.assertFalse(out["available"])
    def test_missing_version_explains_failure(self):
        with tempfile.TemporaryDirectory() as root:
            out=updater.check(root,ignore_cooldown=True)
            self.assertEqual(out["current"], 0)
            self.assertIn("build number",out["reason"])
    def test_manual_bypasses_cooldown(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "version.txt").write_text("29")
            rel={"body":"Build 30","assets":[]}
            with patch.object(updater, "_recently_tried", return_value=True), patch.object(updater,"_json",return_value=rel) as fetch:
                out=updater.check(root,ignore_cooldown=True)
            fetch.assert_called_once()
            self.assertEqual(out["build"],30)

if __name__=="__main__":unittest.main()
