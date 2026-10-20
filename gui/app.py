"""
Desktop GUI for the antidetect browser starter.

Wraps launcher.py and generate_profiles.py in a clickable window using
pywebview (a thin native window around an HTML/CSS/JS frontend — no
Electron/Node.js needed, keeps everything in Python, packages cleanly with
PyInstaller into a single .exe).

Run directly for development:
    python gui/app.py

Package into a standalone Windows .exe: see README.md → "Packaging as an EXE"
"""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from cloud import CloudSync
import profile_pools
import bulk_proxy
import app_api
import plan_runner
import generate_profiles as generate_profiles_module
import launcher
import extension_policy
import updater

# Same reasoning as launcher.py: bundled resources (the gui/web HTML/CSS/JS)
# vs. writable/persistent data (profiles/) need different base paths once
# frozen into a .exe.
if getattr(sys, "frozen", False):
    RESOURCE_DIR = Path(sys._MEIPASS)
    WRITABLE_DIR = Path(sys.executable).parent
else:
    RESOURCE_DIR = Path(__file__).parent.parent
    WRITABLE_DIR = Path(__file__).parent.parent

PROJECT_ROOT = WRITABLE_DIR
PROFILES_DIR = WRITABLE_DIR / "profiles"
EXTENSIONS_DIR = WRITABLE_DIR / "extensions"
LOCK_CONFIG_PATH = EXTENSIONS_DIR / ".lock_config.json"

# Extensions that ship WITH the product (AppBlocker Web Filter, with its
# manifest "key" already pinned — see the key-pinning fix elsewhere in
# this project) are bundled INSIDE the exe as data (build_exe.bat's
# --add-data "extensions;extensions"), not left sitting in the dev
# project folder expecting someone to copy them into place — a real
# customer running the packaged app should never have to do that
# themselves. This seeds any bundled extension that isn't already in the
# writable/persistent EXTENSIONS_DIR, once, the first time the app runs
# (or after an update adds a new one) — anything the customer adds later
# via the GUI's own Extension Management screen is never touched, since
# this only ever copies a folder that's missing, never overwrites one
# that's already there.
#
# In dev mode, RESOURCE_DIR and WRITABLE_DIR are the same folder, so this
# is naturally a no-op (source already matches destination) rather than
# needing a separate dev-mode check.
BUNDLED_EXTENSIONS_DIR = RESOURCE_DIR / "extensions"


# Extensions the product no longer ships. Removed from the writable folder on
# startup so an older install doesn't keep loading them next to the new one.
RETIRED_EXTENSIONS = ["Cold_Turkey_Blocker"]


def _remove_retired_extensions():
    for name in RETIRED_EXTENSIONS:
        old = EXTENSIONS_DIR / name
        if old.exists():
            try:
                shutil.rmtree(old)
                print(f"Removed retired extension: {name}")
            except Exception as e:
                print(f"Couldn't remove retired extension {name}: {e}")


def _seed_bundled_extensions():
    _remove_retired_extensions()
    if not BUNDLED_EXTENSIONS_DIR.exists():
        return
    EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
    for sub in BUNDLED_EXTENSIONS_DIR.iterdir():
        if not sub.is_dir():
            continue
        dest = EXTENSIONS_DIR / sub.name
        if dest.exists():
            continue
        try:
            shutil.copytree(sub, dest)
            print(f"Seeded bundled extension: {sub.name}")
        except Exception as e:
            print(f"Couldn't seed bundled extension {sub.name}: {e}")


_seed_bundled_extensions()

# By default, patchright installs/looks for Chromium in a folder relative
# to wherever its own package files live on disk. Fine in dev mode (a
# stable location), but fatal once frozen into a --onefile exe: PyInstaller
# extracts the whole bundle (patchright included) to a BRAND NEW temp
# folder on every single launch (e.g. .../Temp/_MEI00002b282/...,
# a different random name each run) — so Chromium would need to be
# re-downloaded on every single launch, and worse, a launch attempted
# before that re-download finishes just fails outright ("Executable
# doesn't exist at .../_MEI.../chromium-1234/chrome-win64/chrome.exe").
# Setting PLAYWRIGHT_BROWSERS_PATH (which both Playwright and patchright's
# Node driver read at runtime, not at import time — safe to set any time
# before the first actual install/launch call, not just this early)
# points it at a real persistent folder next to the exe instead — the
# same one-time-download-then-reuse behavior dev mode already has for
# free. Must happen before ensure_chromium()/launcher.launch() are ever
# called, which is guaranteed here since those only run later, in
# response to user action.
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(WRITABLE_DIR / "browsers")

# --windowed builds have no console at all — every print() this app and
# launcher.py make (which is most of how failures have been diagnosed
# throughout this project's development) would otherwise go nowhere
# visible, leaving both us and any future real user of the packaged exe
# completely blind when something fails. Redirecting stdout/stderr to a
# log file next to the exe fixes that for the frozen build specifically;
# dev mode (python gui/app.py) keeps printing to the normal console as
# before, unaffected.
if getattr(sys, "frozen", False):
    LOG_PATH = WRITABLE_DIR / "trickster.log"
    try:
        _log_file = open(LOG_PATH, "a", buffering=1, encoding="utf-8")
        sys.stdout = _log_file
        sys.stderr = _log_file
        print(f"\n=== Started {datetime.now().isoformat()} ===", flush=True)
    except Exception:
        pass  # if even this fails, just proceed without logging rather than crash startup


class Api:
    """Methods exposed to the frontend JS as window.pywebview.api.<method>()"""

    def __init__(self):
        self.cloud = CloudSync()
        self.window = None  # set in main(), needed for file-picker dialogs
        self._sync_extension_removal_policy()

        # Built-in local API (see app_api.py). Underscore-prefixed on
        # purpose: pywebview only exposes public attributes to the JS side.
        self._runner = app_api.ProfileRunner(launcher, self._profile_files, lambda: self.cloud)
        self._local_api = app_api.LocalApi(self._runner, self._profile_files, self._api_describe, self.bulk_assign_proxies)
        self._plan = plan_runner.PlanRunner(self._runner, self._profile_files)
        self._api_cfg_path = WRITABLE_DIR / "api_config.json"
        self._api_cfg = app_api.load_config(self._api_cfg_path)
        self._api_server = None
        self._api_error = None
        if self._api_cfg["enabled"]:
            self._start_api_server()

    # --- Built-in local API ---

    def _api_describe(self, path, number):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        return {
            "no": number,
            "profile_id": data.get("profile_id", path.stem),
            "name": data.get("profile_id", path.stem),
            "file": path.name,
            "group": (data.get("group") or "").strip() or None,
            "os": "macOS" if "Macintosh" in data.get("user_agent", "") else "Windows",
            "locale": data.get("locale", ""),
            "timezone": data.get("timezone_id", ""),
            "proxy_configured": "your-proxy-host" not in data.get("proxy", {}).get("server", ""),
        }

    def _start_api_server(self):
        self._stop_api_server()
        try:
            self._api_server = app_api.LocalApiServer(self._local_api, self._api_cfg["port"], lambda: self._api_cfg["token"])
            self._api_server.start()
            self._api_error = None
        except OSError as e:
            self._api_server = None
            self._api_error = (f"Couldn't start on port {self._api_cfg['port']} ({e}). Something else is using it "
                               "(ixBrowser?) - pick a different port.")

    def _stop_api_server(self):
        if self._api_server:
            self._api_server.stop()
            self._api_server = None

    def api_status(self):
        cfg = self._api_cfg
        return {
            "enabled": cfg["enabled"],
            "running": self._api_server is not None,
            "port": cfg["port"],
            "token": cfg["token"],
            "url": f"http://127.0.0.1:{cfg['port']}/api/v2/",
            "error": self._api_error,
            "open_profiles": len(self._runner.opened()),
        }

    def api_set_enabled(self, enabled):
        self._api_cfg["enabled"] = bool(enabled)
        app_api.save_config(self._api_cfg_path, self._api_cfg)
        if enabled:
            self._start_api_server()
        else:
            self._stop_api_server()
            self._api_error = None
        return self.api_status()

    def api_set_port(self, port):
        try:
            port = int(port)
        except (TypeError, ValueError):
            return {"ok": False, "message": "Port must be a number", **self.api_status()}
        if not (1024 <= port <= 65535):
            return {"ok": False, "message": "Port must be between 1024 and 65535", **self.api_status()}
        self._api_cfg["port"] = port
        app_api.save_config(self._api_cfg_path, self._api_cfg)
        if self._api_cfg["enabled"]:
            self._start_api_server()
        return {"ok": self._api_error is None, "message": self._api_error or f"API now on port {port}", **self.api_status()}

    def api_regenerate_token(self):
        import secrets
        self._api_cfg["token"] = secrets.token_urlsafe(24)
        app_api.save_config(self._api_cfg_path, self._api_cfg)
        return self.api_status()

    def startup_tasks(self):
        """Runs before the browser-engine setup: moves old data in (once) and
        installs a newer Trickster if one is published. Never raises."""
        try:
            if updater.migrate_old_data(PROFILES_DIR, log=lambda m: print(m, flush=True)):
                print("[migrate] done", flush=True)
        except Exception as e:
            print(f"[migrate] skipped: {e}", flush=True)
        if not getattr(sys, "frozen", False):
            return {"updating": False}
        try:
            info = updater.check(RESOURCE_DIR)
            if info.get("available"):
                print(f"[update] build {info['build']} available, installing", flush=True)
                updater.install(info["url"], updater.installed_exe_path(), log=lambda m: print(m, flush=True))
                return {"updating": True}
        except Exception as e:
            print(f"[update] skipped: {e}", flush=True)
        return {"updating": False}

    def ensure_chromium(self):
        """Called once by the frontend before anything else loads (see
        script.js's pywebviewready handler) — makes sure Chromium is
        actually downloaded for patchright before a customer ever tries
        to launch a profile, instead of them hitting a confusing failure
        deep in launcher.py the first time they click Launch. Safe/cheap
        to call every startup: patchright's own installer no-ops quickly
        if everything's already present, so this doesn't mean a ~300MB
        re-download on every run — only the very first one (or after a
        patchright version bump that needs a newer browser build).

        Deliberately does NOT call `patchright install chromium` as a
        subprocess of this app's own executable — sys.executable points
        at Trickster.exe itself once frozen (see the Generate/
        Launch note in README about exactly this class of bug), not a
        real Python interpreter that understands "-m patchright install".
        Instead this drives patchright's own bundled installer directly:
        it ships a small Node.js binary + cli.js under the patchright
        package's own folder (patchright/driver/), used for the CDP
        bridge regardless of install status, so it's already proven to
        resolve correctly in the frozen build (launching profiles at all
        depends on this exact same path lookup) — this just runs that
        same driver with ["install", "chromium"] args instead of calling
        patchright's own main(), which calls sys.exit() itself and would
        tear down the whole GUI process if invoked directly here."""
        # Own engine first. If it is (or becomes) available, profiles use it,
        # so the ~300MB patchright browser is not needed and we skip that
        # second download entirely (it doubled the first-run wait).
        try:
            import chromium_engine
            res = chromium_engine.ensure(log=lambda m: print(m, flush=True))
            print(f"[engine] {res['message']}", flush=True)
            if res.get("ok"):
                return {"ok": True, "message": "Browser engine ready."}
        except Exception as e:
            print(f"[engine] skipped: {e}", flush=True)

        try:
            from patchright._impl._driver import compute_driver_executable, get_driver_env
        except Exception as e:
            return {"ok": False, "message": f"Couldn't locate patchright's installer: {e}"}

        try:
            driver_executable, driver_cli = compute_driver_executable()
        except Exception as e:
            return {"ok": False, "message": f"Couldn't resolve the bundled driver: {e}"}

        try:
            # Popen + streaming, not subprocess.run(capture_output=True) —
            # capture_output buffers everything until the process exits,
            # so nothing gets printed (or written to the log file) until
            # the whole download finishes. For a ~300MB first-time
            # download, that means several minutes of a static spinner
            # with genuinely zero way to tell "still working" from
            # "silently stuck" — streaming line-by-line as it happens
            # fixes that for anyone watching the log file live.
            process = subprocess.Popen(
                [driver_executable, driver_cli, "install", "chromium"],
                env=get_driver_env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                # --windowed builds have no console attached at all. A
                # child process spawned without stdin explicitly handled
                # (above) and without this flag can get killed almost
                # immediately by Windows with STATUS_CONTROL_C_EXIT
                # (0xC000013A / 3221225786) — exactly the failure just
                # seen — because Windows tries to associate it with a
                # console that doesn't exist. CREATE_NO_WINDOW tells it
                # not to try creating one at all.
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            for line in process.stdout:
                print(f"[chromium-install] {line.rstrip()}", flush=True)
            returncode = process.wait(timeout=600)  # first-time download can be slow on a bad connection
        except Exception as e:
            return {"ok": False, "message": f"Chromium setup failed to run: {e}"}

        # The installer treats ANY of its sub-downloads failing as an
        # overall failure — including chrome-headless-shell, a separate
        # component this app never actually uses (profiles always launch
        # headed, never headless). Seen in practice: the real Chromium
        # browser downloaded successfully, then a dropped connection made
        # chrome-headless-shell fail and get retried forever, with the
        # exit code alone giving no way to tell the difference from an
        # actual failure. Check for the specific file this app needs
        # directly, regardless of what the installer's exit code says —
        # that's the real success criterion, not an aggregate exit code
        # covering things we don't need.
        try:
            from patchright.sync_api import sync_playwright as _sync_playwright_check
            with _sync_playwright_check() as _p:
                exe_path = _p.chromium.executable_path
            if exe_path and Path(exe_path).exists():
                print(f"[chromium-install] Required browser confirmed present at {exe_path} "
                      "— treating setup as complete regardless of installer exit code.", flush=True)
                self._ensure_own_engine()
                return {"ok": True, "message": "Chromium ready."}
        except Exception as e:
            print(f"[chromium-install] Direct executable check failed: {e}", flush=True)

        if returncode != 0:
            return {"ok": False, "message": f"Chromium setup failed (exit code {returncode}) — "
                                             "see the log file for details."}
        return {"ok": True, "message": "Chromium ready."}

    def _ensure_own_engine(self):
        """Trickster's own Chromium (no 'Chrome for Testing' bar). Best-effort:
        any problem just means the standard browser is used, as before."""
        try:
            import chromium_engine
            res = chromium_engine.ensure(log=lambda m: print(m, flush=True))
            print(f"[engine] {res['message']}", flush=True)
        except Exception as e:
            print(f"[engine] skipped: {e}", flush=True)

    def _profile_files(self):
        """THE ordered list of profile files. The table's NO. column, the
        number badge on a launched window, bulk assign, and the local API
        all use this one list, so "profile NO. 14" means the same thing
        everywhere."""
        if not PROFILES_DIR.exists():
            return []
        return sorted(p for p in PROFILES_DIR.glob("*.json") if not p.stem.endswith("_state"))

    def list_profiles(self):
        if not PROFILES_DIR.exists():
            return []
        profiles = []
        open_now = {e["file"] for e in self._runner.opened()}
        for number, path in enumerate(self._profile_files(), 1):
            try:
                data = json.loads(path.read_text())
                profiles.append({
                    "number": number,
                    "is_open": path.name in open_now,
                    "id": data.get("profile_id", path.stem),
                    "file": path.name,
                    "os": "macOS" if "Macintosh" in data.get("user_agent", "") else "Windows",
                    "gpu": data.get("webgl_renderer", "").split(",")[0].replace("ANGLE (", ""),
                    "proxy_configured": "your-proxy-host" not in data.get("proxy", {}).get("server", ""),
                    "locale": data.get("locale", ""),
                    "timezone": data.get("timezone_id", ""),
                    "canvas_seed": data.get("canvas_seed", 0),
                    "group": (data.get("group") or "").strip() or None,
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return profiles

    # --- Groups ---
    # A group is nothing more than a free-text "group" field stored on
    # each profile's own JSON file — no separate groups table/file to
    # keep in sync. A group exists exactly as long as at least one
    # profile has that value; creating one is just assigning it to a
    # profile for the first time, and "deleting" one only clears that
    # field on its members — profiles themselves are never touched
    # beyond that one field. Since push_profiles/pull_profiles already
    # sync each profile's entire JSON (see gui/cloud.py), this field
    # rides along automatically — no cloud schema change needed.

    def list_groups(self):
        """Every distinct group currently in use, with how many profiles
        are in each — computed fresh from the profiles themselves each
        time, so it can never drift out of sync with what's actually
        assigned."""
        if not PROFILES_DIR.exists():
            return []
        counts = {}
        for path in sorted(PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            group = (data.get("group") or "").strip()
            if group:
                counts[group] = counts.get(group, 0) + 1
        return [{"name": name, "count": count} for name, count in sorted(counts.items())]

    def assign_group(self, filenames, group_name):
        """Sets the "group" field on every listed profile file — or
        clears it, if group_name is empty, which is how a profile is
        removed from a group (see remove_from_group, which just calls
        this with an empty name)."""
        if not filenames:
            return {"ok": False, "message": "No profiles selected"}
        group_name = (group_name or "").strip()
        updated = 0
        for filename in filenames:
            path = PROFILES_DIR / filename
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if group_name:
                data["group"] = group_name
            else:
                data.pop("group", None)
            path.write_text(json.dumps(data, indent=2))
            updated += 1
        if updated == 0:
            return {"ok": False, "message": "None of the selected profiles were found"}
        verb = (f"Added {updated} profile(s) to '{group_name}'" if group_name
                else f"Removed {updated} profile(s) from their group")
        return {"ok": True, "message": self._auto_push(verb)}

    def rename_group(self, old_name, new_name):
        old_name = (old_name or "").strip()
        new_name = (new_name or "").strip()
        if not old_name or not new_name:
            return {"ok": False, "message": "Both the old and new group name are required"}
        updated = 0
        for path in sorted(PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if (data.get("group") or "").strip() == old_name:
                data["group"] = new_name
                path.write_text(json.dumps(data, indent=2))
                updated += 1
        if updated == 0:
            return {"ok": False, "message": f"No profiles found in group '{old_name}'"}
        return {"ok": True, "message": self._auto_push(f"Renamed '{old_name}' to '{new_name}' ({updated} profile(s))")}

    def delete_group(self, group_name):
        """Un-groups every profile currently in this group — the
        profiles themselves are never deleted or otherwise changed,
        only their "group" label is cleared."""
        group_name = (group_name or "").strip()
        if not group_name:
            return {"ok": False, "message": "No group specified"}
        updated = 0
        for path in sorted(PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if (data.get("group") or "").strip() == group_name:
                data.pop("group", None)
                path.write_text(json.dumps(data, indent=2))
                updated += 1
        if updated == 0:
            return {"ok": False, "message": f"No profiles found in group '{group_name}'"}
        return {"ok": True, "message": self._auto_push(f"Deleted group '{group_name}' ({updated} profile(s) ungrouped)")}

    def get_fingerprint_options(self):
        """Everything the dropdown-based fingerprint editor needs, built
        from the exact same pools generate_profiles.py draws from — so
        picking from these dropdowns can never produce a mismatched combo.
        Desktop platforms (Windows/macOS) expose separate GPU + hardware
        dropdowns (any GPU legitimately pairs with any screen/RAM on a real
        PC). Mobile platforms (Android/iOS) expose one 'devices' list per
        device class instead — a phone's chip/GPU/screen are fixed together
        in real life, so they're picked as one bundle, not mixed."""
        platforms = []
        gpus = {}
        hardware = {}
        devices = {}
        for key, plat in profile_pools.PLATFORMS.items():
            platforms.append({
                "value": key, "label": plat["label"], "kind": plat["kind"],
                "device_classes": [{"value": dc, "label": profile_pools.DEVICE_CLASSES[dc]["label"]
                                     if dc in profile_pools.DEVICE_CLASSES else dc.capitalize()}
                                    for dc in plat["device_classes"]],
                "fonts_preview": ", ".join(plat["fonts"]),
                "ua_preview": plat.get("ua", ""),  # desktop only — mobile UA varies per device, not per platform
            })
            if plat["kind"] == "desktop":
                gpus[key] = [{"value": i, "label": g["label"]} for i, g in enumerate(plat["gpus"])]
                for dc in plat["device_classes"]:
                    hardware[dc] = [{"value": i, "label": o["label"]} for i, o in enumerate(profile_pools.hardware_options(dc))]
            else:
                devices[key] = {
                    dc: [{"value": i, "label": d["label"], "ua_preview": d["ua"]} for i, d in enumerate(plat["devices"][dc])]
                    for dc in plat["device_classes"]
                }

        return {
            "platforms": platforms,
            "gpus": gpus,
            "hardware": hardware,
            "devices": devices,
            "locales": [{"value": i, "label": l["label"]} for i, l in enumerate(profile_pools.LOCALES)],
        }

    def get_profile_config(self, filename):
        path = PROFILES_DIR / filename
        if not path.exists():
            return {"ok": False, "message": "Profile not found"}
        data = json.loads(path.read_text())

        # Reverse-match the profile's current raw values back to dropdown
        # selections (best-effort — a profile edited outside this UI, or an
        # older one from before this feature existed, might not match any
        # pool entry exactly; falls back to sensible defaults if so).
        ua = data.get("user_agent", "")
        if "Android" in ua:
            platform_key = "android"
        elif "iPhone" in ua or "iPad" in ua or ("CriOS" in ua and "Mac OS X" not in ua.split("CriOS")[0]):
            platform_key = "ios"
        elif "Macintosh" in ua:
            platform_key = "macos"
        else:
            platform_key = "windows"

        plat = profile_pools.PLATFORMS[platform_key]
        result = {
            "ok": True,
            "platform": platform_key,
            "kind": plat["kind"],
            "canvas_seed": data.get("canvas_seed", 1),
        }

        if plat["kind"] == "desktop":
            gpus = plat["gpus"]
            gpu_index = next((i for i, g in enumerate(gpus)
                               if g["renderer"] == data.get("webgl_renderer")), 0)
            device_class = "desktop" if data.get("viewport", {}).get("width", 0) >= 1920 and \
                data.get("hardware_concurrency", 0) >= 8 and data.get("device_memory", 0) >= 16 else "laptop"
            hw_opts = profile_pools.hardware_options(device_class)
            hw_index = next((i for i, o in enumerate(hw_opts)
                              if o["hardware_concurrency"] == data.get("hardware_concurrency")
                              and o["device_memory"] == data.get("device_memory")
                              and o["viewport"]["width"] == data.get("viewport", {}).get("width")), 0)
            result.update({"device_class": device_class, "gpu_index": gpu_index, "hardware_index": hw_index})
        else:
            device_class = "tablet" if data.get("viewport", {}).get("width", 0) >= 600 else "phone"
            devices = plat["devices"][device_class]
            device_index = next((i for i, d in enumerate(devices) if d["ua"] == ua), 0)
            result.update({"device_class": device_class, "device_index": device_index})

        locale_index = next((i for i, l in enumerate(profile_pools.LOCALES)
                              if l["timezone_id"] == data.get("timezone_id")), 0)
        result["locale_index"] = locale_index
        return result

    def save_profile_config(self, filename, config):
        path = PROFILES_DIR / filename
        if not path.exists():
            return {"ok": False, "message": "Profile not found"}
        data = json.loads(path.read_text())

        try:
            platform_key = config["platform"]
            plat = profile_pools.PLATFORMS[platform_key]
            locale = profile_pools.LOCALES[int(config["locale_index"])]

            data["locale"] = locale["locale"]
            data["timezone_id"] = locale["timezone_id"]
            data["geolocation"] = locale["geolocation"]
            data["canvas_seed"] = int(config["canvas_seed"])
            data["platform"] = plat["platform"]
            data["fonts"] = plat["fonts"]

            if plat["kind"] == "desktop":
                gpu = plat["gpus"][int(config["gpu_index"])]
                hw = profile_pools.hardware_options(config["device_class"])[int(config["hardware_index"])]
                data["user_agent"] = plat["ua"]
                data["webgl_vendor"] = gpu["vendor"]
                data["webgl_renderer"] = gpu["renderer"]
                data["hardware_concurrency"] = hw["hardware_concurrency"]
                data["device_memory"] = hw["device_memory"]
                data["viewport"] = hw["viewport"]
                data["is_mobile"] = False
                data["has_touch"] = False
                data["device_scale_factor"] = 1
            else:
                device = plat["devices"][config["device_class"]][int(config["device_index"])]
                data["user_agent"] = device["ua"]
                data["webgl_vendor"] = device["gpu_vendor"]
                data["webgl_renderer"] = device["gpu_renderer"]
                data["hardware_concurrency"] = device["hardware_concurrency"]
                data["device_memory"] = device["device_memory"]
                data["viewport"] = device["viewport"]
                data["is_mobile"] = True
                data["has_touch"] = True
                data["device_scale_factor"] = device["device_scale_factor"]
        except (KeyError, IndexError, ValueError) as e:
            return {"ok": False, "message": f"Invalid selection: {e}"}

        path.write_text(json.dumps(data, indent=2))
        return {"ok": True, "message": self._auto_push("Fingerprint updated")}

    def _auto_push(self, message: str) -> str:
        """Silently pushes to the cloud after a mutating action, if signed
        in. This exists because profiles were being lost across sessions —
        Push was manual-only, and starting from a fresh folder each time
        (a real, observed pattern) meant anything not explicitly pushed
        before closing was gone the next time. Auto-pushing after every
        change means the cloud is always current without needing to
        remember a button. Failures here are appended to the message but
        don't fail the primary action — losing cloud backup shouldn't block
        the thing you were actually trying to do."""
        if not self.cloud.is_signed_in():
            return message
        try:
            self.cloud.push_profiles(PROFILES_DIR)
            return message + " (synced to cloud)"
        except Exception as e:
            return message + f" (cloud sync failed: {e})"

    def generate_profiles(self, count):
        try:
            count = int(count)
        except (TypeError, ValueError):
            return {"ok": False, "message": "Count must be a number"}

        try:
            message = generate_profiles_module.generate(count, output_dir=str(PROFILES_DIR))
        except Exception as e:
            return {"ok": False, "message": f"Generation failed: {e}"}
        return {"ok": True, "message": self._auto_push(message)}

    def launch_profile(self, filename, check_mode=False):
        profile_path = PROFILES_DIR / filename
        if not profile_path.exists():
            return {"ok": False, "message": f"Profile not found: {filename}"}

        # Position in the same sorted list the table uses, so the badge
        # shown on the actual browser window matches the "NO." column
        # exactly — e.g. opening the row labelled "3" shows a "3" badge.
        sorted_files = self._profile_files()
        display_number = next((i + 1 for i, p in enumerate(sorted_files) if p.name == filename), None)

        # Goes through the shared runner (which runs launcher.launch() in a
        # background thread, exactly as before) so the built-in API also
        # knows this window is open.
        try:
            entry = self._runner.start(profile_path, source="gui", with_cdp=False, check_mode=check_mode)
        except Exception as e:
            return {"ok": False, "message": f"Couldn't launch {filename}: {e}"}
        if entry.get("already"):
            return {"ok": True, "message": f"{filename} is already open"}
        return {"ok": True, "message": f"Launching {filename}..."}

    def open_profiles(self, text):
        """The "Open by NO." box and the "Open selected" button: takes
        things like "14", "3-8", "1, 5, 20-25" or profile names and starts
        each one. Same numbering as the table's NO. column."""
        paths, problems = bulk_proxy.resolve_many(text, self._profile_files())
        if not paths:
            return {"ok": False, "message": problems[0] if problems else "Type a profile NO. first, like 14 or 3-8"}
        if len(paths) > 25:
            return {"ok": False, "message": f"That's {len(paths)} profiles - open up to 25 at a time so the computer doesn't choke."}
        opened, already, failed = [], [], []
        for path in paths:
            try:
                entry = self._runner.start(path, source="gui", with_cdp=False)
            except Exception as e:
                failed.append(f"{path.stem}: {e}")
                continue
            (already if entry.get("already") else opened).append(path.name)
        bits = []
        if opened:
            bits.append(f"Opening {len(opened)} profile(s)")
        if already:
            bits.append(f"{len(already)} already open")
        if problems:
            bits.append(f"skipped: {'; '.join(problems)}")
        if failed:
            bits.append(f"failed: {'; '.join(failed)}")
        return {"ok": bool(opened or already), "message": ", ".join(bits) + ".", "opened": opened}

    def open_files(self):
        """Profile files whose browser window is open right now."""
        return [e["file"] for e in self._runner.opened()]

    def close_profiles(self, filenames):
        """Closes the given profile files (the row Close button / Close selected)."""
        ids = []
        for e in self._runner.opened():
            if e["file"] in set(filenames or []):
                ids.append(e["profile_id"])
        if not ids:
            return {"ok": True, "message": "Nothing to close - none of those are open."}
        closed = self._runner.close_many(ids, wait=20.0)
        return {"ok": True, "message": f"Closed {len(closed)} profile(s)."}

    def close_all_profiles(self):
        closed = self._runner.close_all(wait=25.0)
        return {"ok": True, "message": f"Closed {len(closed)} profile(s)." if closed else "No profiles are open."}

    # --- Timed plans (open a profile on a website for N seconds, then close) ---

    def plan_run(self, steps, mode):
        return self._plan.run(steps, mode)

    def plan_status(self):
        return self._plan.status()

    def plan_stop(self):
        return self._plan.stop()

    def open_profiles_folder(self):
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            subprocess.run(["explorer", str(PROFILES_DIR)])
        elif sys.platform == "darwin":
            subprocess.run(["open", str(PROFILES_DIR)])
        else:
            subprocess.run(["xdg-open", str(PROFILES_DIR)])
        return {"ok": True}

    # --- Extension management ---
    # Deliberately add-only: there is no remove/uninstall method exposed
    # here at all, matching what was asked for — once an extension is
    # added, it's permanent from inside the app. (Someone could still
    # delete the folder by hand outside the app, on their own filesystem —
    # that's not something software running inside the app can prevent —
    # but the app itself never offers that action.)
    #
    # Every extension here loads into every profile, automatically,
    # including profiles that don't exist yet — this was already true from
    # the original extensions/ folder design (launcher.py discovers and
    # loads everything in there on every launch); this just adds a proper
    # interface on top instead of requiring manual file-copying.

    def list_extensions(self):
        EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
        extensions = []
        for sub in sorted(EXTENSIONS_DIR.iterdir()):
            manifest_path = sub / "manifest.json"
            if sub.is_dir() and manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text())
                except json.JSONDecodeError:
                    manifest = {}
                extensions.append({
                    "folder": sub.name,
                    "name": manifest.get("name", sub.name),
                    "version": manifest.get("version", "?"),
                })
        return extensions

    def _install_extension_from_dir(self, source_dir: Path):
        """Copies an extension folder into extensions/, finding manifest.json
        even if it's nested one level deep (common in exported/unzipped
        extensions, which often have a single version-numbered subfolder)."""
        manifest_path = source_dir / "manifest.json"
        if not manifest_path.exists():
            nested = list(source_dir.glob("*/manifest.json"))
            if not nested:
                return {"ok": False, "message": "No manifest.json found in that folder (not a valid unpacked extension)"}
            source_dir = nested[0].parent

        manifest = json.loads((source_dir / "manifest.json").read_text())
        raw_name = manifest.get("name", source_dir.name)
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw_name)

        dest = EXTENSIONS_DIR / safe_name
        if dest.exists():
            return {"ok": False, "message": f"An extension folder named '{safe_name}' already exists"}

        shutil.copytree(source_dir, dest)
        self._sync_extension_removal_policy()
        return {"ok": True, "message": f"Added extension: {manifest.get('name', safe_name)}"}

    def add_extension_from_folder(self):
        if self.window is None:
            return {"ok": False, "message": "Window not ready"}
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return {"ok": False, "message": "Cancelled"}
        selected = Path(result[0] if isinstance(result, (list, tuple)) else result)
        return self._install_extension_from_dir(selected)

    def add_extension_from_zip(self):
        if self.window is None:
            return {"ok": False, "message": "Window not ready"}
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG, file_types=("Zip files (*.zip)",)
        )
        if not result:
            return {"ok": False, "message": "Cancelled"}
        zip_path = Path(result[0] if isinstance(result, (list, tuple)) else result)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(tmp_path)
            except zipfile.BadZipFile:
                return {"ok": False, "message": "That doesn't look like a valid .zip file"}
            return self._install_extension_from_dir(tmp_path)

    def add_extension_from_webstore(self, url_or_id):
        """Downloads directly from Google's own extension update endpoint —
        the same URL scheme Chrome itself uses to fetch/update extensions,
        not a scrape of the store's web page. Accepts either a full
        chromewebstore.google.com URL or a bare 32-character extension ID."""
        ext_id = self._extract_webstore_id(url_or_id)
        if not ext_id:
            return {"ok": False, "message": "Couldn't find a valid extension ID in that — paste the full "
                                             "Chrome Web Store URL, or just the 32-letter ID from it."}

        # prodversion needs to look like a real, reasonably current Chrome
        # release or Google's update servers appear to quietly return an
        # empty 204 instead of the actual package — confirmed by testing:
        # a stale version (120.x, ~2 years old at the time) reliably 204'd
        # even for genuinely-published extensions. This value will need
        # bumping again periodically as real Chrome versions move on;
        # check https://chromereleases.googleblog.com if downloads start
        # silently failing with status=204 again in the future.
        crx_url = (
            "https://clients2.google.com/service/update2/crx"
            "?response=redirect&os=win&arch=x86-64&os_arch=x86_64&nacl_arch=x86-64"
            "&prod=chromecrx&prodchannel=unknown&prodversion=153.0.8010.36&acceptformat=crx2,crx3"
            f"&x=id%3D{ext_id}%26installsource%3Dondemand%26uc"
        )
        try:
            req = urllib.request.Request(crx_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                status, content_type, final_url = resp.status, resp.headers.get("Content-Type"), resp.geturl()
        except Exception as e:
            return {"ok": False, "message": f"Download failed: {e}"}

        # Pull the public key out of the CRX container itself before we
        # discard its header below — it's what lets this extension get the
        # same fully-robust, stable-ID monitoring/protection Cold Turkey
        # Blocker has, automatically, without anyone needing to dig a key
        # out of a manually-installed copy by hand (not something an end
        # user of the packaged app could do anyway).
        crx_public_key = self._extract_crx_public_key(data)

        # CRX files are a small header followed by a plain ZIP archive —
        # rather than parsing the CRX2/CRX3 header formats precisely (they
        # differ from each other), just find where the embedded ZIP starts
        # and treat everything from there on as a normal zip. Works for both.
        zip_start = data.find(b"PK\x03\x04")
        if zip_start == -1:
            snippet = data[:300]
            print(f"[webstore-add] download didn't contain a zip signature. ext_id={ext_id}, "
                  f"crx_url={crx_url}, status={status}, content_type={content_type}, "
                  f"final_url={final_url}, len={len(data)} bytes, first bytes: {snippet!r}")
            if status == 204:
                return {"ok": False, "message": "Google's server said there's nothing to install for this "
                                                 "extension ID (HTTP 204) — double check the Web Store URL/ID "
                                                 "is correct and the extension is still published."}
            return {"ok": False, "message": "Downloaded file doesn't look like a valid extension package "
                                             "(the ID might be wrong, or the store page might not be a real extension)"}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_bytes_path = tmp_path / "ext.zip"
            zip_bytes_path.write_bytes(data[zip_start:])
            try:
                with zipfile.ZipFile(zip_bytes_path) as zf:
                    extract_dir = tmp_path / "extracted"
                    zf.extractall(extract_dir)
            except zipfile.BadZipFile:
                return {"ok": False, "message": "Downloaded package couldn't be unpacked"}

            if crx_public_key and self._extension_id_for_key(crx_public_key) == ext_id:
                # Only pin it if it actually reproduces the ID we asked
                # for — a mismatch (unexpected CRX layout, wrong proof
                # picked out of the header, etc.) means don't trust it;
                # the extension still installs and works fine either way,
                # just without this stable-ID upgrade.
                manifest_path = extract_dir / "manifest.json"
                try:
                    manifest = json.loads(manifest_path.read_text())
                    manifest["key"] = crx_public_key
                    manifest_path.write_text(json.dumps(manifest, indent=2))
                    print(f"[webstore-add] pinned stable key for {ext_id} — same tamper "
                          "monitoring quality as a manually-keyed extension.")
                except (json.JSONDecodeError, OSError) as e:
                    print(f"[webstore-add] extracted a valid key for {ext_id} but couldn't "
                          f"write it into manifest.json: {e}")
            else:
                print(f"[webstore-add] couldn't confirm a matching key for {ext_id} from the "
                      "downloaded package — it'll still work, just monitored via the older "
                      "worker-sampling fallback instead of the stable-ID path.")

            return self._install_extension_from_dir(extract_dir)

    @staticmethod
    def _extract_webstore_id(text: str):
        text = text.strip()
        if re.fullmatch(r"[a-p]{32}", text):
            return text
        match = re.search(r"/([a-p]{32})(?:[/?]|$)", text)
        return match.group(1) if match else None

    # --- Extension removal lock ---
    # Extensions can't be removed at all by default (matches what was
    # originally asked for). Setting an unlock date/time here is the one
    # way to change that — removal only becomes possible once that moment
    # has actually passed, checked fresh on every attempt, not just once.
    #
    # get_extension_lock_status()/set_extension_unlock_time()/remove_extension()
    # below only gate *this app's own* Remove button and its close-on-
    # tampering monitor — they don't stop the real Remove button inside
    # chrome://extensions itself. _sync_extension_removal_policy() is what
    # closes that gap: while locked, it registers every Web-Store-sourced
    # extension (the ones with a real update_url, e.g. Cold Turkey Blocker)
    # with Chrome's own ExtensionInstallForcelist policy, which is what
    # actually greys out Remove/Disable inside Chrome's own UI. See
    # extension_policy.py for why this is Windows-account-wide rather than
    # scoped to just these profiles.

    def _sync_extension_removal_policy(self):
        """Keeps the real Chrome-level ExtensionInstallForcelist policy in
        sync with the app's own lock state — present (non-removable in
        chrome://extensions) while locked, cleared once genuinely unlocked.
        Called on startup and after anything that changes which extensions
        exist or whether they're locked."""
        status = self.get_extension_lock_status()
        if status["unlocked"]:
            extension_policy.clear_forcelist()
            return

        entries = []
        if EXTENSIONS_DIR.exists():
            for sub in sorted(EXTENSIONS_DIR.iterdir()):
                manifest_path = sub / "manifest.json"
                if not sub.is_dir() or not manifest_path.exists():
                    continue
                try:
                    manifest = json.loads(manifest_path.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                update_url = manifest.get("update_url")
                ext_id = self._extension_id_for_folder(sub)
                # Only extensions with both a real Web Store update_url and
                # a "key"-pinned (thus stable, matching) ID can actually be
                # force-installed/locked by ID this way — see
                # extension_policy.py's module docstring for why extensions
                # without one fall back to the close-on-removal monitor
                # instead.
                if update_url and ext_id:
                    entries.append((ext_id, update_url))

        if entries:
            extension_policy.apply_forcelist(entries)
        else:
            extension_policy.clear_forcelist()

    @staticmethod
    def _extension_id_for_key(key_b64: str):
        """The extension ID Chrome computes from a manifest "key" (or a
        CRX package's embedded public key, same value) — SHA256 of the
        DER public key, first 16 bytes, mapped to a-p. Same algorithm
        Chrome itself uses, so this matches the real ID regardless of
        install path."""
        try:
            der = base64.b64decode(key_b64)
            digest = hashlib.sha256(der).digest()[:16]
            return "".join(chr(ord("a") + (b >> 4)) + chr(ord("a") + (b & 0xF)) for b in digest)
        except Exception:
            return None

    @staticmethod
    def _extension_id_for_folder(folder: Path):
        """The extension ID Chrome will actually compute for this unpacked
        folder — from its manifest's "key" field if present (stable
        regardless of path, same algorithm Chrome itself uses), otherwise
        None, since a path-derived ID isn't something we can usefully hand
        to a Chrome policy (it'd only be correct for this exact folder
        path, and Chrome recomputes it fresh from --load-extension anyway)."""
        try:
            manifest = json.loads((folder / "manifest.json").read_text())
        except (json.JSONDecodeError, OSError):
            return None
        key_b64 = manifest.get("key")
        if not key_b64:
            return None
        return Api._extension_id_for_key(key_b64)

    @staticmethod
    def _read_protobuf_fields(data: bytes):
        """Minimal generic protobuf wire-format field iterator — yields
        (field_number, wire_type, value) for each top-level field. Just
        enough to walk a CRX3 header without needing the protobuf package
        as a dependency; skips fields it doesn't understand rather than
        guessing, since a wrong parse would be worse than no parse."""
        i, n = 0, len(data)
        while i < n:
            tag = 0
            shift = 0
            while True:
                b = data[i]
                i += 1
                tag |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            field_number, wire_type = tag >> 3, tag & 0x7
            if wire_type == 0:  # varint
                value, shift = 0, 0
                while True:
                    b = data[i]
                    i += 1
                    value |= (b & 0x7F) << shift
                    if not (b & 0x80):
                        break
                    shift += 7
            elif wire_type == 1:  # 64-bit fixed
                value, i = data[i:i + 8], i + 8
            elif wire_type == 2:  # length-delimited (bytes/submessage)
                length, shift, start = 0, 0, i
                while True:
                    b = data[start]
                    start += 1
                    length |= (b & 0x7F) << shift
                    if not (b & 0x80):
                        break
                    shift += 7
                value, i = data[start:start + length], start + length
            elif wire_type == 5:  # 32-bit fixed
                value, i = data[i:i + 4], i + 4
            else:
                return  # groups/unsupported — stop rather than misparse
            yield field_number, wire_type, value

    @staticmethod
    def _extract_crx_public_key(data: bytes):
        """Given the raw bytes downloaded from Google's CRX update
        endpoint (before the zip payload is sliced out), returns the
        base64 DER public key — the exact same value Chrome writes into
        manifest.json's "key" field when it installs an extension for
        real. Understands both the legacy CRX2 container (public key at a
        fixed header offset) and the current CRX3 container (public key
        embedded in a protobuf-encoded header, under the first
        sha256_with_rsa AsymmetricKeyProof). Returns None for anything
        else rather than guessing — a missing key just means this
        extension falls back to the older worker-sampling detection, not
        a broken install."""
        if data[:4] != b"Cr24":
            return None
        version = int.from_bytes(data[4:8], "little")
        if version == 2:
            pubkey_len = int.from_bytes(data[8:12], "little")
            pubkey = data[16:16 + pubkey_len]
            return base64.b64encode(pubkey).decode() if pubkey else None
        if version == 3:
            header_size = int.from_bytes(data[8:12], "little")
            header = data[12:12 + header_size]
            for field_num, wire_type, value in Api._read_protobuf_fields(header):
                if field_num != 2 or wire_type != 2:  # sha256_with_rsa proofs only
                    continue
                for sub_num, sub_wire, sub_value in Api._read_protobuf_fields(value):
                    if sub_num == 1 and sub_wire == 2:  # public_key
                        return base64.b64encode(sub_value).decode()
        return None

    def get_extension_lock_status(self):
        unlock_at = None
        if LOCK_CONFIG_PATH.exists():
            try:
                unlock_at = json.loads(LOCK_CONFIG_PATH.read_text()).get("unlock_at")
            except json.JSONDecodeError:
                pass

        unlocked = False
        if unlock_at:
            try:
                unlocked = datetime.now() >= datetime.fromisoformat(unlock_at)
            except ValueError:
                pass

        return {"unlock_at": unlock_at, "unlocked": unlocked}

    def set_extension_unlock_time(self, iso_datetime):
        try:
            datetime.fromisoformat(iso_datetime)
        except ValueError:
            return {"ok": False, "message": "Invalid date/time"}
        EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
        LOCK_CONFIG_PATH.write_text(json.dumps({"unlock_at": iso_datetime}))
        self._sync_extension_removal_policy()
        return {"ok": True, "message": f"Removal unlocks at {iso_datetime}"}

    def remove_extension(self, folder_name):
        status = self.get_extension_lock_status()
        if not status["unlocked"]:
            if status["unlock_at"]:
                return {"ok": False, "message": f"Still locked — unlocks at {status['unlock_at']}"}
            return {"ok": False, "message": "Extensions are locked — set an unlock date/time first"}

        target = EXTENSIONS_DIR / folder_name
        if not target.exists():
            return {"ok": False, "message": "Extension not found"}
        shutil.rmtree(target)
        self._sync_extension_removal_policy()
        return {"ok": True, "message": f"Removed {folder_name}"}

    def get_profile_proxy(self, filename):
        path = PROFILES_DIR / filename
        if not path.exists():
            return {"ok": False, "message": "Profile not found"}
        data = json.loads(path.read_text())
        proxy = data.get("proxy", {})
        return {
            "ok": True,
            "server": proxy.get("server", ""),
            "username": proxy.get("username", ""),
            "password": proxy.get("password", ""),
            "start_url": data.get("start_url", ""),
        }

    def save_profile_proxy(self, filename, server, username, password, start_url=""):
        path = PROFILES_DIR / filename
        if not path.exists():
            return {"ok": False, "message": "Profile not found"}
        data = json.loads(path.read_text())
        start_url = (start_url or "").strip()
        if start_url:
            clean = plan_runner.normalise_url(start_url)
            if not clean:
                return {"ok": False, "message": f"'{start_url}' isn't a website address (try e.g. ads.google.com)."}
            data["start_url"] = clean
        else:
            data.pop("start_url", None)
        data["proxy"] = {"server": server.strip(), "username": username.strip(), "password": password.strip()}
        path.write_text(json.dumps(data, indent=2))
        return {"ok": True, "message": self._auto_push(f"Saved settings for {filename}")}

    def rename_profile(self, filename, new_name):
        path = PROFILES_DIR / filename
        if not path.exists():
            return {"ok": False, "message": "Profile not found"}

        new_name = new_name.strip()
        if not new_name:
            return {"ok": False, "message": "Name can't be empty"}
        # Keep it filesystem-safe — same characters the generator already uses.
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", new_name)

        new_path = PROFILES_DIR / f"{safe_name}.json"
        if new_path.exists() and new_path != path:
            return {"ok": False, "message": f"A profile named '{safe_name}' already exists"}

        data = json.loads(path.read_text())
        old_profile_id = data.get("profile_id", path.stem)
        data["profile_id"] = safe_name
        data["storage_state_path"] = f"profiles/{safe_name}_state.json"

        new_path.write_text(json.dumps(data, indent=2))
        if new_path != path:
            path.unlink()

        # Carry over the browser's saved cookies/session (in user_data/<old_profile_id>)
        # to the new name, so renaming doesn't silently log you out of that profile.
        old_user_data = PROJECT_ROOT / "profiles" / "user_data" / old_profile_id
        new_user_data = PROJECT_ROOT / "profiles" / "user_data" / safe_name
        if old_user_data.exists() and not new_user_data.exists():
            old_user_data.rename(new_user_data)

        return {"ok": True, "message": self._auto_push(f"Renamed to {safe_name}"), "new_file": new_path.name}

    def bulk_assign_proxies(self, proxies_text):
        """Assigns proxies in bulk. All the parsing/matching lives in
        bulk_proxy.py (unit tested); this just applies the plan.

        Targeted lines ("14,host:port:user:pass") go to the profile in row
        NO. 14 of the table (also "14-16,..." for a range). "profile_014,..."
        targets by filename number instead (all variants). Untargeted proxy lines are
        spread round-robin over the profiles no line targeted. Lines that
        can't be understood or match no profile are skipped and reported,
        never silently saved as a bogus proxy.
        """
        proxies_text = (proxies_text or "").strip()
        if not proxies_text:
            return {"ok": False, "message": "No proxies provided", "details": []}

        profile_paths = self._profile_files()  # same order/numbering as the table's NO. column
        if not profile_paths:
            return {"ok": False, "message": "No profiles exist yet — generate some first", "details": []}

        targeted, pool, errors = bulk_proxy.plan_bulk_assign(proxies_text, profile_paths)
        skipped = [f"Line {n}: {why}  [{line}]" for n, line, why in errors]

        if not targeted and not pool:
            return {
                "ok": False,
                "message": "Nothing assigned — " + (skipped[0] if skipped else "no valid proxies found in input"),
                "details": skipped,
            }

        def write_proxy(path, proxy):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return False
            data["proxy"] = {
                "server": proxy.get("server", ""),
                "username": proxy.get("username", ""),
                "password": proxy.get("password", ""),
            }
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True

        details = []
        written = 0
        for path, proxy in targeted.items():
            if write_proxy(path, proxy):
                written += 1
                row = profile_paths.index(path) + 1
                details.append(f"NO. {row}  {path.stem}  ->  {proxy['server']}")
            else:
                skipped.append(f"{path.name}: couldn't read/write this profile file")

        rr_count = 0
        remaining_paths = [p for p in profile_paths if p not in targeted]
        if pool and remaining_paths:
            for i, path in enumerate(remaining_paths):
                if write_proxy(path, pool[i % len(pool)]):
                    rr_count += 1
            details.append(f"{rr_count} other profile(s) got proxies round-robin from {len(pool)} untargeted proxy line(s)")

        parts_msg = []
        if targeted:
            parts_msg.append(f"{written} profile(s) assigned")
        if rr_count:
            parts_msg.append(f"{rr_count} round-robin across {len(pool)} proxies")
        msg = "Assigned proxies: " + ", ".join(parts_msg)
        if skipped:
            msg += f" — {len(skipped)} line(s) skipped (see details)"
        return {"ok": True, "message": self._auto_push(msg), "details": details, "skipped": skipped}

    # --- Cloud sync (Supabase) ---

    def cloud_sign_in(self, email, password):
        try:
            self.cloud.sign_in(email, password)
            return {"ok": True, "message": f"Signed in as {email}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def cloud_sign_up(self, email, password):
        try:
            self.cloud.sign_up(email, password)
            return {"ok": True, "message": "Account created — check your email to confirm, then sign in."}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def cloud_status(self):
        return {"signed_in": self.cloud.is_signed_in()}

    def cloud_try_restore(self):
        restored = self.cloud.try_restore_session()
        return {"signed_in": restored, "email": self.cloud.user.email if restored else None}

    def cloud_sign_out(self):
        self.cloud.sign_out()
        return {"ok": True}

    def cloud_pull(self):
        try:
            count = self.cloud.pull_profiles(PROFILES_DIR)
            return {"ok": True, "message": f"Pulled {count} profiles from the cloud"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def cloud_push(self):
        try:
            count = self.cloud.push_profiles(PROFILES_DIR)
            return {"ok": True, "message": f"Pushed {count} profiles to the cloud"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    # --- Team management ---

    def cloud_get_role(self):
        return {"role": self.cloud.role}

    def cloud_list_members(self):
        try:
            return {"ok": True, "members": self.cloud.list_members()}
        except Exception as e:
            return {"ok": False, "message": str(e), "members": []}

    def cloud_create_invite(self, role):
        try:
            code = self.cloud.create_invite(role)
            return {"ok": True, "code": code, "message": f"Invite code created: {code}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def cloud_redeem_invite(self, code):
        try:
            result = self.cloud.redeem_invite(code)
            return result
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def cloud_update_member_role(self, user_id, role):
        try:
            self.cloud.update_member_role(user_id, role)
            return {"ok": True, "message": "Role updated"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def cloud_remove_member(self, user_id):
        try:
            self.cloud.remove_member(user_id)
            return {"ok": True, "message": "Member removed"}
        except Exception as e:
            return {"ok": False, "message": str(e)}


APP_TITLE = "Trickster - Antidetect application"
APP_USER_MODEL_ID = "Trickster.ProfileManager"


def _app_icon_path():
    """assets/icon.ico - bundled into the exe (build_exe.bat's --add-data) or
    sitting next to the sources in dev. Replace that file to use your own."""
    p = RESOURCE_DIR / "assets" / "icon.ico"
    return p if p.exists() else None


def _claim_taskbar_identity():
    """Without this, Windows groups the manager window under python.exe when
    run from source (so the taskbar/title bar show the Python logo). Giving the
    process its own AppUserModelID makes it a separate app with its own icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception as e:
        print(f"Couldn't set the taskbar app id: {e}")


def _apply_window_icon():
    """Puts the custom icon on the manager window's title bar and taskbar
    button (WM_SETICON), instead of whatever the host process's icon is."""
    if sys.platform != "win32":
        return
    ico = _app_icon_path()
    if not ico:
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = wintypes.HWND
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        hwnd = user32.FindWindowW(None, APP_TITLE)
        if not hwnd:
            return
        IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
        big_px = user32.GetSystemMetrics(11)    # SM_CXICON
        small_px = user32.GetSystemMetrics(49)  # SM_CXSMICON
        big = user32.LoadImageW(None, str(ico), IMAGE_ICON, big_px * 2, big_px * 2, LR_LOADFROMFILE)
        small = user32.LoadImageW(None, str(ico), IMAGE_ICON, small_px, small_px, LR_LOADFROMFILE)
        if big:
            user32.SendMessageW(hwnd, WM_SETICON, 1, big)    # ICON_BIG
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, 0, small)  # ICON_SMALL
    except Exception as e:
        print(f"Couldn't apply the window icon: {e}")


def main():
    _claim_taskbar_identity()
    api = Api()
    web_dir = RESOURCE_DIR / "gui" / "web" if getattr(sys, "frozen", False) else Path(__file__).parent / "web"
    window = webview.create_window(
        APP_TITLE,
        str(web_dir / "index.html"),
        js_api=api,
        width=1000,
        height=700,
        min_size=(700, 500),
    )
    api.window = window
    window.events.shown += _apply_window_icon
    window.events.loaded += _apply_window_icon
    # Explicit gui='edgechromium' — rules out any silent fallback to the
    # legacy WinForms/MSHTML renderer, which has a known bug in exactly the
    # area we're seeing crash (its AccessibleObject.Bounds implementation
    # recurses infinitely under some conditions). Requires the WebView2
    # Runtime, which should already be installed for this to work.
    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
