"""
Local automation API for the antidetect browser — mirrors ixBrowser's local
API shape (same endpoint paths under /api/v2/, same default port 53200,
same {"error": {...}, "data": {...}} response envelope from API Overview.pdf)
so a script already written against that pattern needs only a profile_id
change, not a rewrite, to target this instead.

The workflow this is for: open a specific profile, drive it with your own
automation (Selenium/Puppeteer/Playwright — whatever you already use) via
the CDP endpoint it hands back, then close it (or just call page.reload()
yourself over that same connection for a "refresh" — there's no separate
refresh endpoint, same as ixBrowser doesn't have one either; the open
connection already gives you full control).

Run this server, then in your own separate script:

    import requests
    r = requests.post("http://localhost:53200/api/v2/profile-open",
                       json={"profile_id": "profile_001_windows_desktop"})
    ws = r.json()["data"]["ws"]

    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ws)
        page = browser.contexts[0].pages[0]
        page.goto("https://example.com")
        # ...your own automation from here...
        page.reload()  # "refresh"

    # when done:
    requests.post("http://localhost:53200/api/v2/profile-close",
                   json={"profile_id": "profile_001_windows_desktop"})

See examples/automation_example.py for a complete working version of this.

Run the server:
    pip install -r requirements-api.txt
    python api_server.py
Runs on http://localhost:53200 by default — same port ixBrowser uses. If
an actual ixBrowser install is running on the same machine, change PORT
below (both can't bind it at once).

IMPORTANT: Playwright's sync API must be called from the single thread
that started it. This server deliberately runs single-threaded (Flask's
built-in dev server, threaded=False) to satisfy that — don't wrap this in
a production WSGI server (gunicorn, etc.) without redesigning around that
constraint, since a multi-threaded/multi-worker server would break it.

Deliberately NOT a byte-for-byte clone of ixBrowser's API — two real
differences worth knowing:
- profile_id here is this project's own string identifier (e.g.
  "profile_001_windows_desktop" — the filename stem, already used
  everywhere else in this codebase), not ixBrowser's integer one.
  Remapping the whole profile system to numeric IDs would be a much
  bigger, unrelated change from what was actually asked for.
- The response has no "pid" or "webdriver" path. patchright's persistent-
  context API (launch_persistent_context) doesn't expose the OS process
  handle the way ixBrowser's own closed-source implementation apparently
  does — there's no Browser object to read a pid from, only the
  BrowserContext. And this project doesn't bundle a separate chromedriver
  binary the way ixBrowser ships one per Chromium version; connect via
  the "ws" CDP endpoint instead, which is what patchright/Selenium 4's
  CDP-based drivers use anyway.
"""

import json
import socket
import urllib.request
from pathlib import Path

from flask import Flask, jsonify, request
from patchright.sync_api import sync_playwright

import launcher
import generate_profiles as generate_profiles_module

PROJECT_ROOT = Path(__file__).parent
PROFILES_DIR = PROJECT_ROOT / "profiles"
PORT = 53200

app = Flask(__name__)

playwright_instance = None
# profile_id -> {"context": BrowserContext, "page": Page, "port": int, "ws": str|None}
running_contexts = {}


def ok(data=None):
    return jsonify({"error": {"code": 0, "message": "success"}, "data": data})


def err(code, message, status=200):
    # ixBrowser returns errors with HTTP 200 and the error inside the body
    # (see the PDF's "Failed (200)" examples) — matched here on purpose, so
    # error handling written against that pattern works unchanged. Pass
    # status=404/500 if you'd rather check HTTP codes instead.
    return jsonify({"error": {"code": code, "message": message}, "data": None}), status


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _profile_path(profile_id: str) -> Path:
    return PROFILES_DIR / f"{profile_id}.json"


def _ws_endpoint(port: int):
    """The real CDP websocket URL for a running Chromium instance, read
    from its own /json/version endpoint — not fabricated, this is exactly
    what Chromium itself reports once launched with
    --remote-debugging-port."""
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=5) as resp:
            info = json.loads(resp.read())
            return info.get("webSocketDebuggerUrl")
    except Exception:
        return None


@app.route("/api/v2/profile-list", methods=["POST"])
def profile_list():
    body = request.get_json(silent=True) or {}
    name_filter = (body.get("name") or "").lower()
    page = int(body.get("page", 1))
    limit = int(body.get("limit", 10))

    all_profiles = []
    for path in sorted(PROFILES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        profile_id = data.get("profile_id", path.stem)
        if name_filter and name_filter not in profile_id.lower():
            continue
        all_profiles.append({
            "profile_id": profile_id,
            "name": profile_id,
            "is_open": profile_id in running_contexts,
        })

    start = (page - 1) * limit
    return ok({"list": all_profiles[start:start + limit], "total": len(all_profiles)})


@app.route("/api/v2/profile-open", methods=["POST"])
def profile_open():
    body = request.get_json(silent=True) or {}
    profile_id = body.get("profile_id")
    if not profile_id:
        return err(1000, "profile_id is required")

    if profile_id in running_contexts:
        entry = running_contexts[profile_id]
        return ok({
            "debugging_address": f"127.0.0.1:{entry['port']}",
            "debugging_port": entry["port"],
            "profile_id": profile_id,
            "ws": entry.get("ws"),
        })

    profile_path = _profile_path(profile_id)
    if not profile_path.exists():
        return err(2007, "Profile does not exist")

    headless = bool(body.get("headless", False))
    check_mode = bool(body.get("check", False))
    port = find_free_port()
    profile = launcher.load_profile(str(profile_path))

    try:
        context, page = launcher.build_context(playwright_instance, profile, headless=headless, debug_port=port)
        launcher.navigate(page, profile, check_mode=check_mode)
    except Exception as e:
        return err(2008, f"Launch failed: {e}")

    ws = _ws_endpoint(port)
    running_contexts[profile_id] = {"context": context, "page": page, "port": port, "ws": ws}
    return ok({
        "debugging_address": f"127.0.0.1:{port}",
        "debugging_port": port,
        "profile_id": profile_id,
        "ws": ws,
    })


@app.route("/api/v2/profile-opened-list", methods=["POST"])
def profile_opened_list():
    result = [
        {"profile_id": pid, "debugging_port": e["port"], "ws": e.get("ws")}
        for pid, e in running_contexts.items()
    ]
    return ok({"list": result})


@app.route("/api/v2/profile-close", methods=["POST"])
def profile_close():
    body = request.get_json(silent=True) or {}
    profile_id = body.get("profile_id")
    entry = running_contexts.pop(profile_id, None)
    if not entry:
        return err(1009, "Process not found")
    try:
        entry["context"].close()
    except Exception:
        pass
    return ok()


@app.route("/api/v2/profile-close-in-batches", methods=["POST"])
def profile_close_in_batches():
    body = request.get_json(silent=True) or {}
    profile_ids = body.get("profile_id", [])
    closed, not_found = [], []
    for profile_id in profile_ids:
        entry = running_contexts.pop(profile_id, None)
        if entry:
            try:
                entry["context"].close()
            except Exception:
                pass
            closed.append(profile_id)
        else:
            not_found.append(profile_id)
    return ok({"closed": closed, "not_found": not_found})


@app.route("/profiles/generate", methods=["POST"])
def generate_profiles():
    """Not part of ixBrowser's API (it doesn't need this — profiles are
    created through its own UI/fingerprint marketplace) but kept here
    since it's this project's own equivalent of that, and genuinely useful
    for unattended/scripted profile creation."""
    body = request.get_json(silent=True) or {}
    count = int(body.get("count", 10))
    try:
        message = generate_profiles_module.generate(count, output_dir=str(PROFILES_DIR))
        return ok({"message": message})
    except Exception as e:
        return err(1000, str(e))


def main():
    global playwright_instance
    with sync_playwright() as p:
        playwright_instance = p
        print(f"Automation API running at http://localhost:{PORT}")
        print('POST /api/v2/profile-open        {"profile_id": "..."} -> data.ws (CDP endpoint)')
        print('POST /api/v2/profile-opened-list {}')
        print('POST /api/v2/profile-close       {"profile_id": "..."}')
        app.run(host="localhost", port=PORT, threaded=False)


if __name__ == "__main__":
    main()
