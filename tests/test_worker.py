import sys, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import worker


class FakeStore:
    def __init__(self, jobs):
        self.jobs, self.done, self.beats = list(jobs), {}, 0
        self.lock = threading.Lock()

    def claim(self, name, limit):
        with self.lock:
            out, self.jobs = self.jobs[:limit], self.jobs[limit:]
            return out

    def heartbeat(self, jid):
        self.beats += 1

    def finish(self, jid, ok, result):
        self.done[jid] = (ok, result)


class FakePlan:
    def __init__(self, fail=False):
        self.fail, self._left = fail, 2
        self.steps = None

    def run(self, steps):
        self.steps = steps
        return {"ok": True}

    def status(self):
        self._left -= 1
        active = self._left > 0
        return {"active": active, "items": [{"state": "failed" if self.fail else "done",
                                             "note": "boom" if self.fail else ""}]}


class WorkerTests(unittest.TestCase):
    def files(self):
        return [Path("profile_a.json"), Path("profile_b.json")]

    def test_steps_use_profile_number(self):
        steps, err = worker.steps_for_job(
            {"profile_id": "profile_b", "pages": [{"url": "x.com", "seconds": 5, "scroll": True,
                                                    "actions": [{"at": 1, "key": "End"}]}]}, self.files())
        self.assertIsNone(err)
        self.assertEqual(steps[0]["no"], "2")
        self.assertTrue(steps[0]["scroll"])
        self.assertEqual(steps[0]["actions"][0]["key"], "End")

    def test_unknown_profile_and_empty_pages(self):
        self.assertIn("isn't on this worker", worker.steps_for_job({"profile_id": "zzz", "pages": [{}]}, self.files())[1])
        self.assertIn("no pages", worker.steps_for_job({"profile_id": "profile_a", "pages": []}, self.files())[1])

    def _run(self, jobs, fail=False, max_parallel=2):
        store = FakeStore(jobs)
        w = worker.Worker(store, lambda: FakePlan(fail), self.files, name="t", max_parallel=max_parallel,
                          poll=0.01, heartbeat=0.01, sleep=lambda s: time.sleep(0.001))
        started = 0
        for _ in range(50):
            started += w.tick()
            if len(store.done) == len(jobs):
                break
            time.sleep(0.01)
        for _ in range(100):
            if w.running() == 0:
                break
            time.sleep(0.01)
        return store, started

    def test_jobs_run_and_report_done(self):
        jobs = [{"id": str(i), "profile_id": "profile_a", "pages": [{"url": "a.com", "seconds": 5}]} for i in range(3)]
        store, started = self._run(jobs)
        self.assertEqual(started, 3)
        self.assertTrue(all(ok for ok, _ in store.done.values()))

    def test_failure_is_reported_not_raised(self):
        jobs = [{"id": "1", "profile_id": "profile_a", "pages": [{"url": "a.com", "seconds": 5}]}]
        store, _ = self._run(jobs, fail=True)
        ok, result = store.done["1"]
        self.assertFalse(ok)
        self.assertIn("boom", result["error"])

    def test_bad_job_reports_error(self):
        store, _ = self._run([{"id": "9", "profile_id": "nope", "pages": [{"url": "a.com"}]}])
        self.assertFalse(store.done["9"][0])

    def test_respects_max_parallel(self):
        store = FakeStore([{"id": str(i), "profile_id": "profile_a", "pages": [{"url": "a.com"}]} for i in range(5)])
        w = worker.Worker(store, lambda: FakePlan(), self.files, max_parallel=2, sleep=lambda s: None)
        w._running = 2
        self.assertEqual(w.tick(), 0)


if __name__ == "__main__":
    unittest.main()
