# Trickster cloud worker

Runs queued jobs on a Linux server so profiles can work while your PC is off.

## 1. Add the queue to your database (once)
Open Supabase, go to SQL Editor, paste the contents of `supabase/job_queue.sql`, press Run.

## 2. Set up a server (Ubuntu 22.04 or newer)
Any cloud server works. About 1 CPU core and 1 GB of memory per 3 or 4 profiles at once.

```
sudo apt update && sudo apt install -y python3-venv xvfb git
git clone https://github.com/rickbesada-netizen/Trickster-2 trickster && cd trickster
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
patchright install chromium
```

## 3. Start the worker
```
export TRICKSTER_EMAIL="you@example.com" TRICKSTER_PASSWORD="your password"
export TRICKSTER_MAX_PARALLEL=10
xvfb-run -a python worker.py
```

## 4. Try a job
From any computer with the project:
```
python worker.py --enqueue profile_001_windows_desktop https://example.com 30
```
The worker picks it up within a few seconds. Check the `jobs` table in Supabase for `done` or `failed`.

## Notes
- Each profile uses its own saved proxy. The server's own address is never used.
- Profiles are pulled from your cloud when the worker starts.
- If a worker stops mid-job, the job is handed to another worker after 10 minutes (up to 3 tries).
- Linux servers can look slightly different to websites than Windows PCs (fonts, graphics). Test a few real accounts before scaling up.
