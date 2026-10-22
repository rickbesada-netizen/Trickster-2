"""
Timed plans: "open profile 14 on this website for 30 seconds, then profile 15
on that website for 10 seconds".

Each row = profile NO.(s) + website + seconds (+ optional "scroll down").
Put the SAME profile NO. on several rows to make that profile visit several
sites one after another in the same window - rows are used in order.

The clock for a page starts once the page has loaded. When a profile has
finished its last page it is closed (session saved as normal). Profiles run
either one after another or all at the same time.

"Scroll down" is plain: it glides the page downward at an even pace so it
reaches the bottom about when the page's time is up (and keeps going if the
page grows, e.g. lazy-loaded content).

"Actions" are keyboard presses / typed text you schedule for exact seconds
into a page's time ("at 10s press Down 3 times", "at 20s type hello"). They
fire at exactly the second you set - no random timing, no mouse movement,
no clicking. For anything more custom, drive a profile from your own script
through the local API.
"""

import re
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import bulk_proxy

MIN_SECONDS = 5
MAX_SECONDS = 4 * 3600
MAX_PAGES_PER_PROFILE = 20


def normalise_url(raw: str) -> Optional[str]:
    raw = (raw or "").strip()
    if not raw or " " in raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    u = urllib.parse.urlsplit(raw)
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    if "." not in u.hostname and u.hostname != "localhost":
        return None
    return raw


# What the app's "Press a key" list offers -> the name the browser expects.
KEYS = {
    "Down arrow": "ArrowDown", "Up arrow": "ArrowUp", "Left arrow": "ArrowLeft", "Right arrow": "ArrowRight",
    "Page Down": "PageDown", "Page Up": "PageUp", "Space": "Space", "Home": "Home", "End": "End",
    "Tab": "Tab", "Shift+Tab": "Shift+Tab", "Enter": "Enter", "Escape": "Escape", "Backspace": "Backspace",
}
MAX_ACTIONS_PER_PAGE = 30
MAX_TEXT_LENGTH = 300
MAX_KEY_REPEAT = 50


def clean_actions(raw, seconds) -> Tuple[List[dict], Optional[str]]:
    """Validates the Actions list for one page. Returns (actions, problem)."""
    out: List[dict] = []
    for n, a in enumerate(raw or [], 1):
        a = a or {}
        kind = a.get("type")
        if kind not in ("key", "text"):
            return [], f"action {n}: pick 'Press a key' or 'Type text'"
        try:
            at = float(str(a.get("at", "")).strip())
        except ValueError:
            return [], f"action {n}: type the second it should happen at"
        if at < 0 or at >= seconds:
            return [], f"action {n}: the second must be between 0 and {seconds - 1} (this page is shown for {seconds}s)"
        if kind == "key":
            label = a.get("value")
            key = KEYS.get(label) or (label if label in KEYS.values() else None)
            if not key:
                return [], f"action {n}: unknown key '{label}'"
            try:
                repeat = int(a.get("repeat") or 1)
            except ValueError:
                repeat = 1
            if repeat < 1 or repeat > MAX_KEY_REPEAT:
                return [], f"action {n}: repeat must be 1 to {MAX_KEY_REPEAT}"
            out.append({"at": at, "type": "key", "value": key, "repeat": repeat})
        else:
            text = str(a.get("value") or "")
            if not text or len(text) > MAX_TEXT_LENGTH or "\n" in text or "\r" in text:
                return [], f"action {n}: text must be 1 to {MAX_TEXT_LENGTH} characters on one line"
            out.append({"at": at, "type": "text", "value": text})
    if len(out) > MAX_ACTIONS_PER_PAGE:
        return [], f"up to {MAX_ACTIONS_PER_PAGE} actions per page"
    out.sort(key=lambda x: x["at"])
    return out, None


# ---- paste-a-script ----------------------------------------------------------
# One line per step:   profiles | website | seconds | options
# options (separated by ;):  scroll   |   at 10 press Down arrow x3   |   at 30 type hello
_KEY_ALIASES = {
    "down": "Down arrow", "up": "Up arrow", "left": "Left arrow", "right": "Right arrow",
    "pgdn": "Page Down", "pagedown": "Page Down", "pgup": "Page Up", "pageup": "Page Up",
    "esc": "Escape", "return": "Enter", "spacebar": "Space",
}


def _key_label(name: str) -> Optional[str]:
    n = " ".join(name.strip().lower().replace("arrow", " ").split())
    flat = n.replace(" ", "")
    if flat in _KEY_ALIASES:
        return _KEY_ALIASES[flat]
    for label in KEYS:
        l = label.lower()
        if l == n or l.replace(" arrow", "") == n or l.replace(" ", "") == flat:
            return label
    return None


def _parse_option(opt: str, line_no: int):
    """Returns ("scroll", True) or ("action", dict) or ("error", message)."""
    o = opt.strip()
    low = o.lower()
    if low in ("scroll", "scroll down"):
        return "scroll", True
    m = re.match(r"^at\s+(\d+(?:\.\d+)?)\s*s?\s+(press|type)\s+(.+)$", o, re.I)
    if not m:
        return "error", f"Line {line_no}: couldn't read '{o}' (try: scroll, at 10 press Down, at 30 type hello)"
    at, kind, rest = m.group(1), m.group(2).lower(), m.group(3).strip()
    if kind == "type":
        return "action", {"at": at, "type": "text", "value": rest, "repeat": 1}
    repeat = 1
    r = re.match(r"^(.*?)\s*(?:x|\u00d7)\s*(\d+)\s*(?:times)?$", rest, re.I)
    if r:
        rest, repeat = r.group(1), int(r.group(2))
    label = _key_label(rest)
    if not label:
        return "error", f"Line {line_no}: unknown key '{rest}'"
    return "action", {"at": at, "type": "key", "value": label, "repeat": repeat}


def parse_script(text: str):
    """Turns pasted lines into plan rows (the same shape the table uses).
    Returns {"ok": bool, "rows": [...], "problems": [...]}"""
    rows, problems = [], []
    for line_no, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
        else:
            parts = line.split(None, 3)
        if len(parts) < 2:
            problems.append(f"Line {line_no}: needs at least profiles and a website")
            continue
        no, url = parts[0], parts[1]
        secs = parts[2] if len(parts) > 2 and parts[2] else "30"
        opts = parts[3] if len(parts) > 3 else ""
        if not re.fullmatch(r"\d+(\.\d+)?", secs):
            problems.append(f"Line {line_no}: seconds should be a number (got '{secs}')")
            continue
        row = {"no": no, "url": url, "seconds": secs, "scroll": False, "actions": []}
        bad = False
        for opt in [o for o in opts.split(";") if o.strip()]:
            kind, val = _parse_option(opt, line_no)
            if kind == "error":
                problems.append(val)
                bad = True
            elif kind == "scroll":
                row["scroll"] = True
            else:
                row["actions"].append(val)
        if not bad:
            rows.append(row)
    if not rows and not problems:
        problems.append("Nothing to read yet - paste one line per step, like: 1-20 | example.com | 60 | scroll")
    return {"ok": not problems, "rows": rows, "problems": problems}


# ---- things that run ON the profile's own browser thread -------------------

def go_to(url: str):
    def fn(page, stop_event):
        page.goto(url, timeout=30000)
    return fn


def _do_action(page, action: dict):
    try:
        if action["type"] == "key":
            for i in range(action["repeat"]):
                page.keyboard.press(action["value"])
                if action["repeat"] > 1:
                    page.wait_for_timeout(300)
        else:
            page.keyboard.type(action["value"], delay=60)  # fixed pace, same every time
    except Exception:
        pass  # a key press during a navigation etc. - skip it rather than abort the page


def page_script(seconds: float, scroll: bool, actions: List[dict]):
    """Runs one page's whole time on the browser thread: optional steady
    scroll toward the bottom (re-measured each tick so growing pages work),
    plus the scheduled key presses / typing, each fired at its exact second."""
    todo = sorted(actions or [], key=lambda a: a["at"])

    def fn(page, stop_event):
        start = time.time()
        end = start + seconds
        tick = 0.2
        i = 0
        while True:
            now = time.time()
            if now >= end or (stop_event is not None and stop_event.is_set()):
                return
            while i < len(todo) and todo[i]["at"] <= now - start:
                _do_action(page, todo[i])
                i += 1
            if scroll:
                try:
                    remaining = page.evaluate(
                        "Math.max(0, document.documentElement.scrollHeight - window.innerHeight - window.scrollY)")
                    left = end - time.time()
                    if remaining > 0 and left > 0:
                        step = remaining / max(left, tick) * tick
                        page.evaluate("d => window.scrollBy(0, d)", step)
                except Exception:
                    pass  # mid-navigation; try again next tick
            page.wait_for_timeout(int(tick * 1000))
    return fn


class PlanRunner:
    def __init__(self, runner, files_fn: Callable[[], List[Path]]):
        self._runner = runner
        self._files = files_fn
        self._lock = threading.Lock()
        self._items: List[dict] = []
        self._active = False
        self._stop = threading.Event()
        self._mode = "one_by_one"

    # ---- validation / expansion ----
    def _expand(self, steps) -> Tuple[List[dict], List[str]]:
        files = self._files()
        items: List[dict] = []
        by_path = {}
        problems: List[str] = []
        for row, step in enumerate(steps or [], 1):
            step = step or {}
            text = str(step.get("no", "")).strip()
            url_raw = str(step.get("url", "")).strip()
            secs_raw = str(step.get("seconds", "")).strip()
            if not text and not url_raw and not secs_raw:
                continue  # blank row
            url = normalise_url(url_raw)
            try:
                seconds = int(float(secs_raw))
            except ValueError:
                seconds = 0
            if not text:
                problems.append(f"Row {row}: type the profile NO.")
                continue
            if not url:
                problems.append(f"Row {row}: the website looks wrong (try something like example.com)")
                continue
            if seconds < MIN_SECONDS or seconds > MAX_SECONDS:
                problems.append(f"Row {row}: seconds must be between {MIN_SECONDS} and {MAX_SECONDS}")
                continue
            acts, why = clean_actions(step.get("actions"), seconds)
            if why:
                problems.append(f"Row {row}: {why}")
                continue
            paths, bad = bulk_proxy.resolve_many(text, files)
            if bad:
                problems.append(f"Row {row}: {'; '.join(bad)}")
                continue
            page = {"url": url, "seconds": seconds, "scroll": bool(step.get("scroll")), "actions": acts}
            for p in paths:
                it = by_path.get(p)
                if it is None:
                    it = {"path": p, "no": files.index(p) + 1, "profile": p.stem, "pages": [],
                          "state": "waiting", "page_index": 0, "left": 0, "note": "", "url": "", "scroll": False}
                    by_path[p] = it
                    items.append(it)
                it["pages"].append({**page, "actions": [dict(a) for a in acts]})
        for it in items:
            if len(it["pages"]) > MAX_PAGES_PER_PROFILE:
                problems.append(f"NO. {it['no']} has {len(it['pages'])} pages - up to {MAX_PAGES_PER_PROFILE} per profile")
            it["url"] = it["pages"][0]["url"]
            it["scroll"] = it["pages"][0]["scroll"]
            it["left"] = it["pages"][0]["seconds"]
        return items, problems

    # ---- public ----
    def run(self, steps, mode: str = "one_by_one") -> dict:
        with self._lock:
            if self._active:
                return {"ok": False, "message": "A plan is already running - stop it first."}
        items, problems = self._expand(steps)
        if problems:
            return {"ok": False, "message": problems[0], "problems": problems}
        if not items:
            return {"ok": False, "message": "Add at least one step (profile NO., website and seconds)."}
        with self._lock:
            self._items = items
            self._active = True
            self._stop = threading.Event()
            self._mode = "together" if mode == "together" else "one_by_one"
        threading.Thread(target=self._drive, daemon=True, name="plan").start()
        how = "all at the same time" if self._mode == "together" else "one after another"
        return {"ok": True, "message": f"Plan started: {len(items)} profile(s), {how}."}

    def stop(self) -> dict:
        with self._lock:
            if not self._active:
                return {"ok": True, "message": "No plan is running."}
        self._stop.set()
        return {"ok": True, "message": "Stopping the plan and closing its profiles..."}

    def status(self) -> dict:
        with self._lock:
            items = []
            for it in self._items:
                d = {k: v for k, v in it.items() if k not in ("path", "pages")}
                d["pages_total"] = len(it["pages"])
                items.append(d)
            return {"active": self._active, "mode": self._mode, "items": items}

    # ---- internals ----
    def _set(self, item, **kw):
        with self._lock:
            item.update(kw)

    def _drive(self):
        try:
            if self._mode == "together":
                threads = [threading.Thread(target=self._run_item, args=(it,), daemon=True) for it in self._items]
                for t in threads:
                    t.start()
                    time.sleep(0.6)  # tiny stagger so the PC isn't hit by every launch in one instant
                for t in threads:
                    t.join()
            else:
                for it in self._items:
                    if self._stop.is_set():
                        self._set(it, state="stopped", note="plan stopped before this step")
                        continue
                    self._run_item(it)
        finally:
            with self._lock:
                self._active = False

    def _wait_page(self, it, pid, page_def, scroll_done) -> str:
        """Counts down one page's time. Returns "ok", "stopped" or "closed"."""
        end = time.time() + page_def["seconds"]
        while True:
            left = end - time.time()
            if left <= 0:
                return "ok"
            if self._stop.is_set():
                return "stopped"
            if not self._runner.is_open(pid):
                return "closed"
            self._set(it, left=int(left + 0.99))
            time.sleep(0.25)

    def _run_item(self, it: dict):
        pid = None
        try:
            first = it["pages"][0]
            self._set(it, state="opening", page_index=0, url=first["url"], scroll=first["scroll"], left=first["seconds"])
            try:
                entry = self._runner.start(it["path"], source="plan", with_cdp=False, start_url=first["url"])
            except Exception as e:  # noqa: BLE001
                self._set(it, state="failed", note=str(e))
                return
            if entry.get("already"):
                self._set(it, state="failed", note="already open - close it first")
                return
            pid = entry["profile_id"]

            # wait for the window to be up and the first page loaded
            deadline = time.time() + 120
            while not entry["ready"].is_set():
                if self._stop.is_set():
                    self._set(it, state="stopped")
                    return
                if not self._runner.is_open(pid):
                    self._set(it, state="failed", note=entry.get("error") or "the browser closed during startup")
                    return
                if time.time() > deadline:
                    self._set(it, state="failed", note="took too long to open")
                    return
                time.sleep(0.2)

            notes = []
            for idx, page_def in enumerate(it["pages"]):
                self._set(it, page_index=idx, url=page_def["url"], scroll=page_def["scroll"], left=page_def["seconds"])
                if idx > 0:
                    self._set(it, state="opening")
                    done = self._runner.submit(pid, go_to(page_def["url"]))
                    if done is None:
                        self._set(it, state="done", note="you closed it early")
                        return
                    while not done["event"].wait(0.25):
                        if self._stop.is_set():
                            self._set(it, state="stopped")
                            return
                        if not self._runner.is_open(pid):
                            self._set(it, state="done", note="you closed it early")
                            return
                    if done["error"]:
                        notes.append(f"couldn't load {page_def['url']}")
                self._set(it, state="running")
                if page_def["scroll"] or page_def["actions"]:
                    self._runner.submit(pid, page_script(page_def["seconds"], page_def["scroll"], page_def["actions"]))
                outcome = self._wait_page(it, pid, page_def, None)
                if outcome == "stopped":
                    self._set(it, state="stopped")
                    return
                if outcome == "closed":
                    self._set(it, state="done", left=0, note="you closed it early")
                    return

            self._set(it, state="closing", left=0)
            self._runner.close_many([pid], wait=25.0)
            self._set(it, state="done", note="; ".join(notes))
        finally:
            if pid and self._stop.is_set():
                self._runner.close_many([pid], wait=25.0)
