"""
Trickster cloud worker: runs queued jobs (pages to visit, scrolls, timed key
presses) on saved profiles, on a server, without anyone sitting at it.

Each job is "open profile X, visit these pages for these seconds, close it".
Logins and cookies come from the cloud the same way they do in the app, and
each profile uses its own saved proxy.

Run it on a Linux server (see worker/README.md):
    TRICKSTER_EMAIL=... TRICKSTER_PASSWORD=... xvfb-run -a python worker.py

Add a test job from any computer:
    python worker.py --enqueue profile_001_windows_desktop https://example.com 30
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))

PROFILES_DIR = ROOT / "profiles"
POLL_SECONDS = 5
HEARTBEAT_SECONDS = 30


def log(msg):
    print(f"[worker {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def profile_files(profiles_dir=PROFILES_DIR):
    if not Path(profiles_dir).exists():
        return []
    return sorted(p for p in Path(profiles_dir).glob("*.json") if not p.stem.endswith("_state"))


def steps_for_job(job, files):
    """Turns a job row into the plan steps the app's PlanRunner understands.
    Returns (steps, error)."""
    names = [p.stem for p in files]
    pid = job.get("profile_id")
    if pid not in names:
        return None, f"profile '{pid}' isn't on this worker"
    pages = job.get("pages") or []
    if not pages:
        return None, "job has no pages"
    number = names.index(pid) + 1
    steps = []
    for page in pages:
        steps.append({
            "no": str(number),
            "url": page.get("url", ""),
            "seconds": page.get("seconds", 30),
            "scroll": bool(page.get("scroll")),
            "actions": page.get("actions") or [],
        })
    return steps, None


class CloudJobStore:
    """The job table in Supabase."""

    def __init__(self, cloud):
        self.cloud = cloud

    @property
    def _client(self):
        return self.cloud._get_client()

    def claim(self, worker, limit):
        res = self._client.rpc("claim_jobs", {"p_worker": worker, "p_limit": limit}).execute()
        return res.data or []

    def heartbeat(self, job_id):
        self._client.table("jobs").update({"heartbeat": _now()}).eq("id", job_id).execute()

    def finish(self, job_id, ok, result):
        self._client.table("jobs").update({
            "status": "done" if ok else "failed", "finished_at": _now(), "result": result,
        }).eq("id", job_id).execute()

    def enqueue(self, profile_id, pages, run_at=None):
        row = {"org_id": self.cloud.org_id, "profile_id": profile_id, "pages": pages}
        if run_at:
            row["run_at"] = run_at
        return self._client.table("jobs").insert(row).execute().data


def _now():
    return datetime.now(timezone.utc).isoformat()


class Worker:
    def __init__(self, store, plan_factory, files_fn, name=None, max_parallel=10,
                 poll=POLL_SECONDS, heartbeat=HEARTBEAT_SECONDS, sleep=time.sleep):
        self.store = store
        self.plan_factory = plan_factory   # () -> object with run(steps) and status()
        self.files_fn = files_fn
        self.name = name or f"{socket.gethostname()}-{os.getpid()}"
        self.max_parallel = max_parallel
        self.poll = poll
        self.heartbeat = heartbeat
        self._sleep = sleep
        self._lock = threading.Lock()
        self._running = 0
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def running(self):
        with self._lock:
            return self._running

    def run_job(self, job):
        """Runs one job to the end and reports the outcome. Never raises."""
        jid = job["id"]
        beat_stop = threading.Event()

        def beat():
            while not beat_stop.wait(self.heartbeat):
                try:
                    self.store.heartbeat(jid)
                except Exception as e:  # noqa: BLE001
                    log(f"heartbeat failed for {jid}: {e}")

        threading.Thread(target=beat, daemon=True).start()
        ok, result = False, {}
        try:
            steps, err = steps_for_job(job, self.files_fn())
            if err:
                result = {"error": err}
            else:
                plan = self.plan_factory()
                started = plan.run(steps)
                if not started.get("ok"):
                    result = {"error": started.get("message", "couldn't start")}
                else:
                    while plan.status().get("active"):
                        self._sleep(0.5)
                    items = plan.status().get("items", [])
                    states = [i.get("state") for i in items]
                    ok = bool(items) and all(s == "done" for s in states)
                    result = {"states": states, "notes": [i.get("note", "") for i in items if i.get("note")]}
                    if not ok:
                        result["error"] = "; ".join(i.get("note") or i.get("state", "") for i in items) or "no result"
        except Exception as e:  # noqa: BLE001
            result = {"error": f"{type(e).__name__}: {e}"}
        finally:
            beat_stop.set()
            try:
                self.store.finish(jid, ok, result)
            except Exception as e:  # noqa: BLE001
                log(f"couldn't report job {jid}: {e}")
            with self._lock:
                self._running -= 1
            log(f"job {jid} ({job.get('profile_id')}): {'done' if ok else 'failed - ' + str(result.get('error'))}")

    def tick(self):
        """One polling round. Returns how many jobs were started."""
        with self._lock:
            free = self.max_parallel - self._running
        if free <= 0:
            return 0
        try:
            jobs = self.store.claim(self.name, free)
        except Exception as e:  # noqa: BLE001
            log(f"couldn't check the queue: {e}")
            return 0
        for job in jobs:
            with self._lock:
                self._running += 1
            threading.Thread(target=self.run_job, args=(job,), daemon=True).start()
            self._sleep(0.6)  # stagger launches a little
        return len(jobs)

    def loop(self):
        log(f"worker '{self.name}' started, up to {self.max_parallel} jobs at once")
        while not self._stop.is_set():
            self.tick()
            self._sleep(self.poll)


def build_cloud(email, password):
    from cloud import CloudSync
    cloud = CloudSync()
    cloud.sign_in(email, password)
    return cloud


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trickster cloud worker")
    ap.add_argument("--enqueue", nargs=3, metavar=("PROFILE_ID", "URL", "SECONDS"),
                    help="add a test job to the queue and exit")
    ap.add_argument("--max-parallel", type=int, default=int(os.environ.get("TRICKSTER_MAX_PARALLEL", "10")))
    ap.add_argument("--name", default=os.environ.get("TRICKSTER_WORKER_NAME"))
    args = ap.parse_args(argv)

    email, password = os.environ.get("TRICKSTER_EMAIL"), os.environ.get("TRICKSTER_PASSWORD")
    if not email or not password:
        sys.exit("Set TRICKSTER_EMAIL and TRICKSTER_PASSWORD (your Trickster account).")
    cloud = build_cloud(email, password)
    store = CloudJobStore(cloud)

    if args.enqueue:
        pid, url, secs = args.enqueue
        store.enqueue(pid, [{"url": url, "seconds": int(secs), "scroll": True}])
        log(f"queued {pid} -> {url} for {secs}s")
        return

    n = cloud.pull_profiles(PROFILES_DIR)
    log(f"loaded {n} profile(s) from the cloud")

    import launcher
    import app_api
    import plan_runner
    runner = app_api.ProfileRunner(launcher, profile_files, lambda: cloud)

    def plan_factory():
        return plan_runner.PlanRunner(runner, profile_files)

    Worker(store, plan_factory, profile_files, name=args.name, max_parallel=args.max_parallel).loop()


if __name__ == "__main__":
    main()
