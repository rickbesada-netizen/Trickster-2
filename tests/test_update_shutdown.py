"""Offline regression checks for in-app update installation ordering."""
import unittest
import updater


class UpdateShutdownTests(unittest.TestCase):
    def test_helper_waits_before_starting_setup(self):
        script = updater.update_helper_script()
        self.assertIn("Wait-Process -Id $ParentPid", script)
        self.assertLess(script.index("Wait-Process -Id $ParentPid"),
                        script.index("Start-Process -FilePath $SetupPath"))
        self.assertIn("'/NOCLOSEAPPLICATIONS'", script)
        self.assertIn("Another Trickster process is running", script)
        self.assertIn("Start-Process -FilePath $InstalledExe", script)
        self.assertIn("UPDATE FAILED:", script)

    def test_no_force_kill(self):
        script = updater.update_helper_script()
        self.assertNotIn("Stop-Process -Force", script)
        self.assertNotIn("taskkill", script.lower())


if __name__ == "__main__":
    unittest.main()
