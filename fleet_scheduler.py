"""Fleet controller for authorised campaigns on an operator-owned platform.

Runs inside the Trickster Windows app, but drives an installed ixBrowser Local
API (or Trickster's compatible local endpoint) using separate HTTP clients
for each worker. All browser automation sessions are isolated by profile.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import random
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from zoneinfo import ZoneInfo

SLOTS = (20, 30, 40, 10)
PASS_OFFSETS_HOURS = (0, 2, 4, 6)
MAX_API_REQUESTS = 3
API_LIMIT = threading.BoundedSemaphore(MAX_API_REQUESTS)
WORKER_LOCK = threading.Lock()
ACTIVE_PROFILES = set()
MAX_MONTHLY_BYTES = 100 * 1024**3
SOFT_STOP_BYTES = 80 * 1024**3


def machine_layout():
    """Exactly 1,000 profiles: 2x133 + 8x67 + 3x66."""
    sizes = [133, 133] + [67] * 8 + [66] * 3
    concurrency = [24, 24] + [12] * 11
    assert sum(sizes) == 1000 and sum(concurrency) == 180
    result, first = [], 0
    for index, (n, cap) in enumerate(zip(sizes, concurrency)):
        result.append({"machine": index, "start": first, "end": first + n,
                       "count": n, "max_workers": cap, "ram_gb": 32 if index < 2 else 16})
        first += n
    return result


def select_daily_clips(profile_id, campaigns, today):
    """Ten distinct clips from each campaign, shuffled per profile/day."""
    if len(campaigns) != 10 or any(len(c.get("clips", [])) != 100 for c in campaigns):
        raise ValueError("Expected exactly ten campaigns with 100 clips each")
    selected = []
    for campaign in campaigns:
        seed = hashlib.sha256(f"{today}|{profile_id}|{campaign['id']}".encode()).digest()
        rnd = random.Random(int.from_bytes(seed, "big"))
        for clip in rnd.sample(campaign["clips"], 10):
            selected.append(dict(clip, campaign_id=campaign["id"],
                                 creator_url=campaign["creator_url"],
                                 link_selector=campaign.get("link_selector", "a[href]"),
                                 quality_selector=campaign.get("quality_selector", "")))
    seed = hashlib.sha256(f"{today}|{profile_id}|shuffle".encode()).digest()
    random.Random(int.from_bytes(seed, "big")).shuffle(selected)
    ids = [(x["campaign_id"], x["id"]) for x in selected]
    if len(set(ids)) != 100:
        raise ValueError("Duplicate campaign/clip IDs in daily selection")
    return selected


def profile_partition(profile_ids, machine):
    layout = machine_layout()[machine]
    if len(profile_ids) != 1000 or len(set(map(str, profile_ids))) != 1000:
        raise ValueError("profile_ids must contain exactly 1000 unique IDs")
    return profile_ids[layout["start"]:layout["end"]], layout["max_workers"]


def wait_until(deadline, stop):
    while not stop.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        stop.wait(min(remaining, 0.5))
    return False


class LocalApiClient:
    """Worker-owned HTTP client; the API itself is capped at 3 concurrent calls."""
    def __init__(self, base_url, token=""):
        self.base = base_url.rstrip("/")
        self.token = token
        self.opener = urllib.request.build_opener()

    def call(self, name, payload):
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + "/api/v2/" + name,
                                     data=body, headers=headers, method="POST")
        with API_LIMIT:
            with self.opener.open(req, timeout=100) as res:
                parsed = json.load(res)
        if parsed.get("error", {}).get("code", 0):
            raise RuntimeError(f"API {name}: {parsed['error']}")
        return parsed.get("data") or {}

    def open(self, pid):
        return self.call("profile-open", {"profile_id": pid})

    def close(self, pid):
        return self.call("profile-close", {"profile_id": pid})


class FleetController:
    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = threading.RLock()
        self.state = {"active": False, "pass": 0, "completed": 0,
                      "failed": 0, "running": 0, "last_error": "", "machine": None}

    def status(self):
        with self.lock:
            return dict(self.state)

    def _set(self, **kwargs):
        with self.lock:
            self.state.update(kwargs)

    def start(self):
        if self.thread and self.thread.is_alive():
            return {"ok": False, "message": "Fleet schedule already running"}
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            machine = int(config["machine_index"])
            profile_ids = config["profile_ids"]
            profiles, cap = profile_partition(profile_ids, machine)
            campaigns = config["campaigns"]
            select_daily_clips(profiles[0], campaigns, dt.date.today().isoformat())
            if not (0 <= int(config.get("operating_hour", 11)) <= 23):
                raise ValueError("operating_hour must be between 0 and 23")
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            return {"ok": False, "message": str(exc)}
        self.stop_event.clear()
        self._set(active=True, machine=machine, completed=0, failed=0,
                  running=0, last_error="", pass_number=0)
        self.thread = threading.Thread(target=self._run, args=(config, profiles, cap),
                                       name="fleet-scheduler", daemon=True)
        self.thread.start()
        return {"ok": True, "message": f"Scheduled {len(profiles)} profiles with a {cap}-worker cap"}

    def stop(self):
        self.stop_event.set()
        return {"ok": True, "message": "Stop requested; active profiles will close via API"}

    def _run(self, config, profiles, cap):
        try:
            while not self.stop_event.is_set():
                self._execute(config, profiles, cap)
        except Exception as exc:
            self._set(last_error=f"{type(exc).__name__}: {exc}")
        finally:
            self._set(active=False, running=0)

    def _execute(self, config, profiles, cap):
        tz = ZoneInfo(config.get("timezone", "Australia/Melbourne"))
        now = dt.datetime.now(tz)
        hour = int(config.get("operating_hour", 11))
        start = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if now >= start + dt.timedelta(hours=8):
            start += dt.timedelta(days=1)
        elif now < start:
            pass
        # An app launched during the operating window may join the current day.
        if now >= start:
            day = start.date().isoformat()
        else:
            day = start.date().isoformat()
        deadline = start + dt.timedelta(hours=8)
        seconds_to_start = max(0, (start - now).total_seconds())
        if self.stop_event.wait(seconds_to_start):
            return
        started_monotonic = time.monotonic()
        eight_hours_end = started_monotonic + max(0, (deadline - dt.datetime.now(tz)).total_seconds())
        ledger = Path(config.get("ledger_path") or self.config_path.with_name("fleet_ledger.json"))
        progress = self._read_ledger(ledger)
        bandwidth = Path(config.get("bandwidth_path") or self.config_path.with_name("fleet_bandwidth.json"))
        byte_usage = self._read_ledger(bandwidth)
        for pass_index, (count, offset) in enumerate(zip(SLOTS, PASS_OFFSETS_HOURS)):
            if self.stop_event.is_set() or time.monotonic() >= eight_hours_end:
                break
            pass_start = started_monotonic + max(0, offset * 3600 - seconds_to_start)
            if not wait_until(pass_start, self.stop_event):
                break
            self._set(pass_number=pass_index + 1)
            with ThreadPoolExecutor(max_workers=cap) as executor:
                futures = []
                for pid in profiles:
                    if self.stop_event.is_set() or time.monotonic() >= eight_hours_end:
                        break
                    picks = select_daily_clips(pid, config["campaigns"], day)
                    clips = picks[sum(SLOTS[:pass_index]):sum(SLOTS[:pass_index + 1])]
                    futures.append(executor.submit(self._visit_batch, pid, clips, config, day,
                                                   progress, ledger, byte_usage, bandwidth,
                                                   eight_hours_end))
                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception as exc:
                        self._set(last_error=str(exc))
        self.stop_event.wait(max(0, (deadline - dt.datetime.now(tz)).total_seconds()))

    def _visit_batch(self, pid, clips, config, day, progress, ledger,
                     byte_usage, bandwidth, cutoff):
        if self.stop_event.is_set() or time.monotonic() >= cutoff:
            return
        month = day[:7]
        key = f"{day}:{pid}"
        with self.lock:
            already = set(progress.get(key, []))
            used_bytes = int(byte_usage.get(f"{month}:{pid}", 0))
        if used_bytes >= SOFT_STOP_BYTES:
            return
        with WORKER_LOCK:
            if pid in ACTIVE_PROFILES:
                return
            ACTIVE_PROFILES.add(pid)
        client = LocalApiClient(config.get("api_url", "http://127.0.0.1:53200"),
                                config.get("api_token", ""))
        with self.lock:
            self.state["running"] += 1
        opened = False
        browser = None
        try:
            response = client.open(pid)
            opened = True
            ws = response.get("ws")
            debug = response.get("debugging_address")
            if not ws and debug:
                ws = debug if debug.startswith(("http://", "https://", "ws://", "wss://")) else "http://" + debug
            if not ws:
                raise RuntimeError(f"Profile {pid}: API did not return CDP connection details")
            from patchright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(ws)
                if not browser.contexts:
                    raise RuntimeError("No profile browser context")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                transfer = {"bytes": 0}
                cdp = context.new_cdp_session(page)
                cdp.send("Network.enable")
                cdp.on("Network.loadingFinished", lambda event: transfer.__setitem__(
                    "bytes", transfer["bytes"] + max(0, int(event.get("encodedDataLength", 0)))))
                page.route("**/*", lambda route: route.abort() if
                           route.request.resource_type in ("image", "font")
                           else route.continue_())
                for clip in clips:
                    if self.stop_event.is_set() or time.monotonic() >= cutoff:
                        break
                    if used_bytes + transfer["bytes"] >= SOFT_STOP_BYTES:
                        self._set(last_error=f"Profile {pid}: estimated bandwidth safety limit reached")
                        break
                    ident = f"{clip['campaign_id']}:{clip['id']}"
                    if ident in already:
                        continue
                    page.goto(clip["creator_url"], wait_until="domcontentloaded", timeout=30000)
                    selector = clip.get("link_selector") or "a[href]"
                    href = clip.get("href")
                    if not href:
                        raise ValueError("Each clip requires its href on the creator page")
                    # Find the creator page's link; never navigate directly to clip URL.
                    try:
                        link = page.locator(f"a[href='{href}']").first
                        link.click(timeout=15000)
                    except Exception:
                        # Never fall back to direct navigation: keep the creator-page route.
                        raise RuntimeError(f"Clip link {href} not found on creator page")
                    page.wait_for_timeout(random.randint(250, 950))
                    quality = clip.get("quality_selector")
                    if quality:
                        try:
                            page.locator(quality).first.select_option("360p", timeout=1500)
                        except Exception:
                            try:
                                page.locator(quality).first.select_option("480p", timeout=1500)
                            except Exception:
                                pass
                    clip_seconds = float(clip.get("duration_seconds") or 0)
                    if clip_seconds <= 0:
                        clip_seconds = float(page.locator("video").first.evaluate("(v) => v.duration", timeout=4000))
                    if not (1 <= clip_seconds <= 600):
                        raise ValueError("Invalid clip duration")
                    try:
                        page.locator("video").first.evaluate("(v) => v.play().catch(() => {})", timeout=3000)
                    except Exception:
                        pass
                    dwell = clip_seconds * random.uniform(0.60, 1.15)
                    while dwell > 0 and not self.stop_event.is_set() and time.monotonic() < cutoff:
                        tick = min(dwell, 0.5)
                        self.stop_event.wait(tick)
                        dwell -= tick
                    if self.stop_event.is_set() or time.monotonic() >= cutoff:
                        break
                    with self.lock:
                        already.add(ident)
                        progress[key] = sorted(already)
                        self._atomic_write(ledger, progress)
                        byte_usage[f"{month}:{pid}"] = used_bytes + transfer["bytes"]
                        self._atomic_write(bandwidth, byte_usage)
                        self.state["completed"] += 1
                    self.stop_event.wait(random.uniform(0.4, 2.5))
        except Exception as exc:
            with self.lock:
                self.state["failed"] += 1
                self.state["last_error"] = f"profile {pid}: {exc}"
        finally:
            # Do not use browser.close() -- profile-close is the system of record.
            if opened:
                try:
                    client.close(pid)
                except Exception as exc:
                    self._set(last_error=f"profile {pid} close error: {exc}")
            with WORKER_LOCK:
                ACTIVE_PROFILES.discard(pid)
            with self.lock:
                self.state["running"] = max(0, self.state["running"] - 1)

    @staticmethod
    def _read_ledger(path):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _atomic_write(path, obj):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(obj), encoding="utf-8")
        os.replace(tmp, path)
