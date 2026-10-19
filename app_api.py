"""
Built-in local API for the Profile Manager app.

Runs INSIDE the desktop app (no separate server to start, no Flask to
install) on 127.0.0.1:53200 by default - the same port and response shape as
ixBrowser's local API, so scripts written for that need little change.

Everything is addressed by the same profile NO. you see in the table's first
column, or by profile name, so you can say "open 14", "open 3-8", or
"open profile_014_windows_desktop":

    POST /api/v2/profile-list            {"name": "...", "group": "...", "page": 1, "limit": 50}
    POST /api/v2/profile-open            {"profile_id": 14}              (or "no": 14, or a name)
    POST /api/v2/profile-open-batch      {"profiles": ["1-5", 14, "profile_020_ios_phone"]}
    POST /api/v2/profile-opened-list     {}
    POST /api/v2/profile-close           {"profile_id": 14}
    POST /api/v2/profile-close-in-batches{"profile_id": [14, 15]}
    POST /api/v2/profile-close-all       {}
    POST /api/v2/profile-update-proxy    {"profile_id": 14, "proxy": "host:port:user:pass"}
    POST /api/v2/proxy-bulk-assign       {"text": "14,host:port:user:pass\\n15,..."}
    GET/POST /api/v2/ping

profile-open returns data.ws - a Chrome DevTools (CDP) websocket you drive
with Playwright / patchright / Puppeteer / Selenium 4:

    browser = playwright.chromium.connect_over_cdp(data["ws"])

Security (this API can open logged-in browsers, so it is locked down):
  * listens on 127.0.0.1 only - not reachable from other computers
  * every request needs the token shown in the app:
        Authorization: Bearer <token>        (or header  X-API-Key: <token>)
  * requests that carry a browser Origin header, or a Host other than
    localhost/127.0.0.1, are refused - so a web page you happen to visit
    can't call it.
"""

import base64
import hmac
import json
import os
import secrets
import queue
import socket
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional

import bulk_proxy

DEFAULT_PORT = 53200
OPEN_TIMEOUT_SECONDS = 90


# --------------------------------------------------------------------------
# config (enabled / port / token) persisted next to the app
# --------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    cfg = {}
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    changed = False
    if not isinstance(cfg.get("token"), str) or len(cfg["token"]) < 16:
        cfg["token"] = secrets.token_urlsafe(24)
        changed = True
    if not isinstance(cfg.get("port"), int) or not (1024 <= cfg["port"] <= 65535):
        cfg["port"] = DEFAULT_PORT
        changed = True
    if not isinstance(cfg.get("enabled"), bool):
        cfg["enabled"] = True
        changed = True
    if changed:
        save_config(path, cfg)
    return cfg


def save_config(path: Path, cfg: dict) -> None:
    try:
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------
# tiny CDP websocket client - just enough to send Browser.close
# --------------------------------------------------------------------------

def cdp_browser_close(ws_url: str, timeout: float = 5.0) -> bool:
    """Politely asks Chromium to quit ({"method": "Browser.close"}) over its
    DevTools websocket. Needs no third-party websocket library, and works from
    any thread (Playwright's own objects can't be touched across threads)."""
    u = urllib.parse.urlparse(ws_url)
    try:
        sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
    except OSError:
        return False
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                return False
            buf += chunk
        if b" 101 " not in buf.split(b"\r\n", 1)[0] + b" ":
            return False
        payload = b'{"id":1,"method":"Browser.close"}'
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        sock.sendall(bytes([0x81, 0x80 | len(payload)]) + mask + masked)
        try:
            sock.recv(4096)  # the reply, or the connection dropping as it quits
        except OSError:
            pass
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cdp_ws(port: int) -> Optional[str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
            return json.loads(r.read()).get("webSocketDebuggerUrl")
    except Exception:
        return None


# --------------------------------------------------------------------------
# tracks every open browser window (opened from the GUI or from the API)
# --------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ProfileRunner:
    """Owns the running-profile registry. Each profile runs launcher.launch()
    in its own thread (exactly what the GUI's Launch button always did), so
    this adds no new browser-launching code path."""

    def __init__(self, launcher_module, files_fn: Callable[[], List[Path]], cloud_fn: Callable[[], object]):
        self._launcher = launcher_module
        self._files = files_fn
        self._cloud = cloud_fn
        self._lock = threading.Lock()
        self._running: Dict[str, dict] = {}

    # -- queries --
    def is_open(self, profile_id: str) -> bool:
        with self._lock:
            return profile_id in self._running

    def info(self, profile_id: str) -> Optional[dict]:
        with self._lock:
            e = self._running.get(profile_id)
            return dict(e) if e else None

    def opened(self) -> List[dict]:
        with self._lock:
            return [
                {"profile_id": pid, "no": e["no"], "file": e["file"], "debugging_port": e["port"], "ws": e["ws"],
                 "source": e["source"]}
                for pid, e in self._running.items()
            ]

    # -- start --
    def start(self, path: Path, *, source: str, with_cdp: bool, headless: bool = False,
              check_mode: bool = False, start_url: Optional[str] = None) -> dict:
        """Starts the profile. Returns the registry entry (already-open
        profiles return their existing entry, flagged "already": True)."""
        files = self._files()
        try:
            no = files.index(path) + 1
        except ValueError:
            no = None
        profile = self._launcher.load_profile(str(path))
        pid = profile["profile_id"]

        with self._lock:
            existing = self._running.get(pid)
            if existing:
                out = dict(existing)
                out["already"] = True
                return out
            port = _free_port() if with_cdp else None
            entry = {"profile_id": pid, "no": no, "file": path.name, "port": port, "ws": None, "source": source,
                     "error": None, "started": time.time(), "stop": threading.Event(), "ready": threading.Event(),
                     "commands": queue.Queue()}
            self._running[pid] = entry

        def run():
            try:
                self._launcher.launch(profile, headless=headless, check_mode=check_mode, debug_port=port,
                                      display_number=no, cloud=self._cloud(), stop_event=entry["stop"],
                                      start_url=start_url, ready_event=entry["ready"], commands=entry["commands"])
            except Exception as e:  # noqa: BLE001 - surfaced to the API caller below
                entry["error"] = str(e)
                print(f"Launch error for {pid}: {e}")
            finally:
                with self._lock:
                    if self._running.get(pid) is entry:
                        del self._running[pid]

        threading.Thread(target=run, daemon=True, name=f"profile-{pid}").start()

        if with_cdp:
            deadline = time.time() + OPEN_TIMEOUT_SECONDS
            while time.time() < deadline:
                ws = _cdp_ws(port)
                if ws:
                    entry["ws"] = ws
                    break
                with self._lock:
                    if self._running.get(pid) is not entry:  # launch thread ended early
                        raise ApiError(2008, f"Launch failed: {entry['error'] or 'the browser exited during startup'}")
                time.sleep(0.25)
            else:
                raise ApiError(2008, f"Timed out after {OPEN_TIMEOUT_SECONDS}s waiting for the browser to start")
        return dict(entry)

    # -- run something on an open profile's page (executed on its own thread) --
    def submit(self, profile_id: str, fn) -> Optional[dict]:
        """Queues fn(page, stop_event) to run on the profile's browser thread.
        Returns a "done" dict ({"event": Event, "error": str|None}) to wait
        on, or None if that profile isn't open."""
        with self._lock:
            entry = self._running.get(profile_id)
        if not entry:
            return None
        done = {"event": threading.Event(), "error": None}
        entry["commands"].put((fn, done))
        return done

    # -- stop --
    def close_many(self, profile_ids: List[str], wait: float = 25.0) -> List[str]:
        """Closes several open profiles at once. Returns the ids that were
        open (and so were asked to close). Each is asked to shut down
        cleanly (so its session is saved/synced as normal); any still
        running after a while that has a DevTools port is told to quit."""
        with self._lock:
            entries = {pid: self._running[pid] for pid in profile_ids if pid in self._running}
        for e in entries.values():
            e["stop"].set()

        def gone(pid, e):
            with self._lock:
                return self._running.get(pid) is not e

        started = time.time()
        deadline = started + wait
        fallback_at = started + min(wait / 2, 10.0)
        tried_cdp = set()
        while time.time() < deadline:
            pending = {pid: e for pid, e in entries.items() if not gone(pid, e)}
            if not pending:
                break
            if time.time() >= fallback_at:
                for pid, e in pending.items():
                    if pid not in tried_cdp and e["port"]:
                        tried_cdp.add(pid)
                        ws = e["ws"] or _cdp_ws(e["port"])
                        if ws:
                            cdp_browser_close(ws)
            time.sleep(0.2)
        return list(entries)

    def close(self, profile_id: str, wait: float = 25.0) -> bool:
        return bool(self.close_many([profile_id], wait=wait))

    def close_all(self, wait: float = 25.0) -> List[str]:
        return self.close_many([e["profile_id"] for e in self.opened()], wait=wait)


# --------------------------------------------------------------------------
# the API itself
# --------------------------------------------------------------------------

class LocalApi:
    def __init__(self, runner: ProfileRunner, files_fn: Callable[[], List[Path]],
                 describe_fn: Callable[[Path, int], dict], bulk_assign_fn: Callable[[str], dict]):
        self.runner = runner
        self._files = files_fn
        self._describe = describe_fn
        self._bulk_assign = bulk_assign_fn

    # -- resolving what the caller means --
    def resolve(self, ref) -> List[Path]:
        files = self._files()
        if isinstance(ref, bool) or ref is None or ref == "":
            raise ApiError(1000, "profile_id is required")
        if isinstance(ref, int):
            ref = str(ref)
        matches, why = bulk_proxy.resolve_target(str(ref), files)
        if matches:
            return matches
        # Fall back to a unique partial-name match ("windows_desktop" alone is too broad, "profile_014_win" fine).
        needle = str(ref).strip().lower()
        partial = [p for p in files if needle and needle in p.stem.lower()]
        if len(partial) == 1:
            return partial
        if len(partial) > 1:
            raise ApiError(2007, f"'{ref}' matches {len(partial)} profiles - be more specific or use the NO.")
        raise ApiError(2007, f"Profile does not exist: {why or ref}")

    def resolve_one(self, body: dict) -> Path:
        ref = body.get("profile_id", body.get("no", body.get("name")))
        found = self.resolve(ref)
        if len(found) != 1:
            raise ApiError(1000, f"'{ref}' matches {len(found)} profiles; this call takes exactly one "
                                 "(use the -batch version for several)")
        return found[0]

    def _refs_from(self, body: dict, *keys) -> List[Path]:
        raw = None
        for k in keys:
            if k in body and body[k] not in (None, ""):
                raw = body[k]
                break
        if raw is None:
            raise ApiError(1000, f"one of {', '.join(keys)} is required")
        items = raw if isinstance(raw, list) else [raw]
        out: List[Path] = []
        for item in items:
            for p in self.resolve(item):
                if p not in out:
                    out.append(p)
        return out

    # -- endpoints: each takes the JSON body, returns "data" --
    def ping(self, body):
        return {"app": "Trickster", "profiles": len(self._files()), "open": len(self.runner.opened())}

    def profile_list(self, body):
        name = str(body.get("name") or "").lower()
        group = body.get("group")
        page = max(1, int(body.get("page", 1)))
        limit = max(1, min(1000, int(body.get("limit", 50))))
        rows = []
        for no, path in enumerate(self._files(), 1):
            d = self._describe(path, no)
            if not d:
                continue
            if name and name not in d["profile_id"].lower():
                continue
            if group is not None and (d.get("group") or "") != group:
                continue
            e = self.runner.info(d["profile_id"])
            d["is_open"] = bool(e)
            d["debugging_port"] = e["port"] if e else None
            rows.append(d)
        start = (page - 1) * limit
        return {"list": rows[start:start + limit], "total": len(rows), "page": page, "limit": limit}

    def _open_data(self, entry: dict) -> dict:
        return {
            "profile_id": entry["profile_id"], "no": entry["no"],
            "debugging_address": f"127.0.0.1:{entry['port']}" if entry["port"] else None,
            "debugging_port": entry["port"], "ws": entry["ws"],
        }

    def profile_open(self, body):
        path = self.resolve_one(body)
        entry = self.runner.start(path, source="api", with_cdp=True,
                                  headless=bool(body.get("headless", False)),
                                  check_mode=bool(body.get("check", False)),
                                  start_url=body.get("url") or None)
        if not entry["port"]:
            raise ApiError(2009, "This profile is already open from the app's Launch button, which has no "
                                 "automation port. Close that window first, then open it through the API.")
        return self._open_data(entry)

    def profile_open_batch(self, body):
        paths = self._refs_from(body, "profiles", "profile_id", "no")
        results = []
        for path in paths:
            try:
                entry = self.runner.start(path, source="api", with_cdp=True,
                                          headless=bool(body.get("headless", False)))
                if not entry["port"]:
                    raise ApiError(2009, "already open from the Launch button (no automation port)")
                results.append({"ok": True, **self._open_data(entry)})
            except ApiError as e:
                results.append({"ok": False, "profile_id": path.stem, "code": e.code, "message": e.message})
        return {"results": results, "opened": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])}

    def profile_opened_list(self, body):
        return {"list": self.runner.opened()}

    def profile_close(self, body):
        path = self.resolve_one(body)
        pid = self._pid(path)
        if not self.runner.close(pid):
            raise ApiError(1009, "Process not found (that profile isn't open)")
        return None

    def _pid(self, path: Path) -> str:
        d = self._describe(path, 0)
        return d["profile_id"] if d else path.stem

    def profile_close_batch(self, body):
        paths = self._refs_from(body, "profile_id", "profiles", "no")
        closed, not_found, failed = [], [], []
        for path in paths:
            pid = self._pid(path)
            try:
                (closed if self.runner.close(pid) else not_found).append(pid)
            except ApiError as e:
                failed.append({"profile_id": pid, "message": e.message})
        return {"closed": closed, "not_found": not_found, "failed": failed}

    def profile_close_all(self, body):
        return {"closed": self.runner.close_all(wait=15.0), "failed": []}

    def profile_update_proxy(self, body):
        path = self.resolve_one(body)
        raw = body.get("proxy")
        if isinstance(raw, dict):
            raw = ",".join([str(raw.get("server", "")), str(raw.get("username", "")), str(raw.get("password", ""))])
        proxy = bulk_proxy.parse_proxy_string(str(raw or ""))
        if not proxy:
            raise ApiError(1000, "proxy not recognised - use host:port:user:pass or http://host:port,user,pass")
        files = self._files()
        line = f"{files.index(path) + 1},{raw}"
        res = self._bulk_assign(line)
        if not res.get("ok"):
            raise ApiError(1000, res.get("message", "couldn't save the proxy"))
        return {"profile_id": self._pid(path), "server": proxy["server"]}

    def proxy_bulk_assign(self, body):
        text = body.get("text")
        if text is None and isinstance(body.get("lines"), list):
            text = "\n".join(str(x) for x in body["lines"])
        res = self._bulk_assign(text or "")
        if not res.get("ok"):
            raise ApiError(1000, res.get("message", "nothing assigned"))
        return {"message": res.get("message"), "assigned": res.get("details", []), "skipped": res.get("skipped", [])}

    ROUTES = {
        "ping": "ping",
        "profile-list": "profile_list",
        "profile-open": "profile_open",
        "profile-open-batch": "profile_open_batch",
        "profile-open-in-batches": "profile_open_batch",
        "profile-opened-list": "profile_opened_list",
        "profile-close": "profile_close",
        "profile-close-in-batches": "profile_close_batch",
        "profile-close-all": "profile_close_all",
        "profile-update-proxy": "profile_update_proxy",
        "proxy-bulk-assign": "proxy_bulk_assign",
    }

    def dispatch(self, route: str, body: dict):
        name = self.ROUTES.get(route)
        if not name:
            raise ApiError(404, f"Unknown endpoint: {route}")
        return getattr(self, name)(body)


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def _make_handler(api: LocalApi, token_fn: Callable[[], str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AntidetectLocalApi/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        def _send(self, status: int, payload: dict):
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _fail(self, status: int, code: int, message: str):
            self._send(status, {"error": {"code": code, "message": message}, "data": None})

        def _guard(self) -> bool:
            try:
                host = urllib.parse.urlsplit("//" + (self.headers.get("Host") or "")).hostname or ""
            except ValueError:
                host = ""
            if host.lower() not in _LOCAL_HOSTS:
                self._fail(403, 403, "Forbidden host")
                return False
            if self.headers.get("Origin"):
                self._fail(403, 403, "Browser-originated requests are not allowed")
                return False
            supplied = ""
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                supplied = auth[7:].strip()
            if not supplied:
                supplied = (self.headers.get("X-API-Key") or "").strip()
            if not supplied or not hmac.compare_digest(supplied.encode(), token_fn().encode()):
                self._fail(401, 401, "Missing or wrong API token (copy it from the app's API panel)")
                return False
            return True

        def _handle(self, body: dict):
            path = urllib.parse.urlparse(self.path).path
            prefix = "/api/v2/"
            if not path.startswith(prefix):
                return self._fail(404, 404, "Not found")
            try:
                data = api.dispatch(path[len(prefix):].strip("/"), body)
                self._send(200, {"error": {"code": 0, "message": "success"}, "data": data})
            except ApiError as e:
                self._send(404 if e.code == 404 else 200, {"error": {"code": e.code, "message": e.message}, "data": None})
            except (ValueError, TypeError) as e:
                self._send(200, {"error": {"code": 1000, "message": f"Bad request: {e}"}, "data": None})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"error": {"code": 500, "message": f"Internal error: {e}"}, "data": None})

        def do_GET(self):
            if not self._guard():
                return
            q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()}
            self._handle(q)

        def do_POST(self):
            if not self._guard():
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > 2_000_000:
                return self._fail(413, 413, "Body too large")
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw.strip() else {}
                if not isinstance(body, dict):
                    raise ValueError("JSON body must be an object")
            except (ValueError, UnicodeDecodeError) as e:
                return self._fail(400, 1000, f"Invalid JSON: {e}")
            self._handle(body)

        def do_OPTIONS(self):  # no CORS: a browser preflight must fail
            self._fail(403, 403, "CORS is not enabled")

    return Handler


class LocalApiServer:
    def __init__(self, api: LocalApi, port: int, token_fn: Callable[[], str]):
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(api, token_fn))
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="local-api")

    def start(self):
        self._thread.start()

    def stop(self):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass
