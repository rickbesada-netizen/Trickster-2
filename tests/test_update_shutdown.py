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

    def test_parent_logs_before_helper_and_captures_stderr(self):
        import inspect
        code = inspect.getsource(updater.install)
        self.assertIn('with open(log_path, "a", encoding="utf-8")', code)
        self.assertIn('stderr=subprocess.STDOUT', code)
        self.assertIn('process.poll()', code)
        self.assertIn('CREATE_NO_WINDOW', code)
        self.assertNotIn('DETACHED_PROCESS', code)
        self.assertLess(code.index('with open(log_path, "a"'),
                        code.index('subprocess.Popen('))

    def test_no_force_kill(self):
        script = updater.update_helper_script()
        self.assertNotIn("Stop-Process -Force", script)
        self.assertNotIn("taskkill", script.lower())


if __name__ == "__main__":
    unittest.main()
