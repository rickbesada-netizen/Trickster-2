"""
Antidetect browser launcher.

Reads a profile JSON, launches a patchright-driven Chromium instance with
that profile's fingerprint, proxy, and persistent profile data (cookies,
local storage — and now shared extensions).

Usage:
    python launcher.py profiles/profile_example.json
    python launcher.py profiles/profile_example.json --check   # opens a fingerprint-check site
    python launcher.py profiles/profile_example.json --debug-port 9222

Setup (run once):
    pip install patchright
    patchright install chromium

Extensions: drop unpacked extension folders (each containing a manifest.json)
into extensions/ at the project root. Every profile loads every extension in
there — same set, every time, so behaviour is consistent across profiles.
"""

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

from patchright.sync_api import sync_playwright

from local_proxy_relay import start_local_proxy_relay

# Bundled resources (fingerprint_injection.js) vs. writable/persistent data
# (extensions/, profiles/user_data/) need different base paths once this is
# a frozen .exe: PyInstaller extracts bundled files to a temp folder
# (sys._MEIPASS) that's wiped after the app closes, so anything that needs
# to persist across runs — or that a customer needs to actually put files
# into, like the extensions folder — has to live somewhere real instead:
# the folder the .exe itself sits in, keeping this feeling like a normal
# portable app.
if getattr(sys, "frozen", False):
    RESOURCE_DIR = Path(sys._MEIPASS)
    WRITABLE_DIR = Path(sys.executable).parent
else:
    RESOURCE_DIR = Path(__file__).parent
    WRITABLE_DIR = Path(__file__).parent

PROJECT_ROOT = WRITABLE_DIR
INJECTION_TEMPLATE_PATH = RESOURCE_DIR / "fingerprint_injection.js"
EXTENSIONS_DIR = WRITABLE_DIR / "extensions"
USER_DATA_ROOT = WRITABLE_DIR / "profiles" / "user_data"


def load_profile(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def build_injection_script(profile: dict) -> str:
    template = INJECTION_TEMPLATE_PATH.read_text()
    return template.replace("__PROFILE__", json.dumps(profile))


def seed_to_hex_color(seed: int) -> str:
    """Deterministic colour from a profile's canvas_seed, so the same
    profile always gets the same colour across runs."""
    h = (int(seed) * 2654435761) & 0xFFFFFF
    r = 90 + (h & 0x3F)          # keep colours mid-bright, not too dark/pale
    g = 90 + ((h >> 6) & 0x3F)
    b = 90 + ((h >> 12) & 0x3F)
    return f"#{r:02x}{g:02x}{b:02x}"


def build_branding_script(profile: dict, display_number: int | None = None) -> str:
    """Runs as an init script (before ANY page script, on every navigation)
    rather than reactively after the fact — this is what makes it robust:
    it locks document.title via a property override so no page script can
    ever overwrite it afterward, instead of racing against one. The old
    approach (setting title reactively after 'load') could lose that race
    if a page changed its own title later (some do, via setTimeout etc.)."""
    color = seed_to_hex_color(profile.get("canvas_seed", 1))
    label = profile.get("profile_id", "profile")
    # Badge shows the profile's position number (matching the GUI table's
    # "NO." column exactly, e.g. row 3 -> a "3" badge) when known — falls
    # back to initials for CLI-only usage where no table position exists.
    badge_text = str(display_number) if display_number is not None else (
        "".join(w[0] for w in label.replace("_", " ").split()[:2]).upper() or "P"
    )

    return f"""
    (function() {{
      const LABEL = {json.dumps(label)};
      const COLOR = {json.dumps(color)};
      const INITIALS = {json.dumps(badge_text)};

      try {{
        Object.defineProperty(document, 'title', {{
          configurable: true,
          get() {{ return LABEL; }},
          set(v) {{
            // Page scripts can't change what document.title itself
            // reports (stays LABEL always, for anti-detect/taskbar
            // consistency) — but real dynamic title changes (SPAs like
            // YouTube setting a per-video title) still get written to
            // the actual <title> DOM element, so automation can still
            // read the true title directly from the DOM if it needs to:
            //   page.eval_on_selector("title", "el => el.textContent")
            // instead of page.title() (which reads this property and
            // will always return the branded LABEL, by design).
            try {{
              let titleEl = document.querySelector('title');
              if (!titleEl) {{
                titleEl = document.createElement('title');
                (document.head || document.documentElement).appendChild(titleEl);
              }}
              titleEl.textContent = v;
            }} catch (e) {{ /* best effort */ }}
          }},
        }});
      }} catch (e) {{ /* some pages may already have a non-configurable title descriptor — skip, not fatal */ }}

      function setFavicon() {{
        try {{
          let link = document.querySelector("link[rel~='icon']");
          if (!link) {{
            link = document.createElement('link');
            link.rel = 'icon';
            (document.head || document.documentElement).appendChild(link);
          }}
          const canvas = document.createElement('canvas');
          canvas.width = 32; canvas.height = 32;
          const ctx = canvas.getContext('2d');
          ctx.fillStyle = COLOR;
          ctx.fillRect(0, 0, 32, 32);
          ctx.fillStyle = '#0a1512';
          ctx.font = 'bold 13px sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(INITIALS, 16, 17);
          link.href = canvas.toDataURL('image/png');
        }} catch (e) {{ /* cosmetic only, safe to skip if it fails */ }}
      }}

      if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', setFavicon);
      }} else {{
        setFavicon();
      }}
    }})();
    """


def apply_branding(page, profile: dict, display_number: int | None = None):
    """Kept as a belt-and-suspenders extra call right after navigation —
    the init script above (build_branding_script) is the real, robust fix
    since it runs before page scripts on every navigation and locks the
    title against being overwritten later; this just re-applies the
    favicon in case the very first paint happened before the init script
    finished (rare, but cheap to guard against)."""
    color = seed_to_hex_color(profile.get("canvas_seed", 1))
    label = profile.get("profile_id", "profile")
    badge_text = str(display_number) if display_number is not None else (
        "".join(w[0] for w in label.replace("_", " ").split()[:2]).upper() or "P"
    )

    script = f"""
    document.title = {json.dumps(label)};
    (function() {{
      let link = document.querySelector("link[rel~='icon']");
      if (!link) {{
        link = document.createElement('link');
        link.rel = 'icon';
        document.head.appendChild(link);
      }}
      const canvas = document.createElement('canvas');
      canvas.width = 32; canvas.height = 32;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = {json.dumps(color)};
      ctx.fillRect(0, 0, 32, 32);
      ctx.fillStyle = '#0a1512';
      ctx.font = 'bold 13px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText({json.dumps(badge_text)}, 16, 17);
      link.href = canvas.toDataURL('image/png');
    }})();
    """
    try:
        page.evaluate(script)
    except Exception as e:
        print(f"Branding re-apply skipped: {e}")  # visible now instead of silently swallowed


def get_chromium_version(p, exe_override: str | None = None) -> str | None:
    """Queries the installed Chromium binary's real version directly,
    without needing to launch a browser first. Used to correct the
    profile's UA string so it never falls out of sync with reality
    (a UA/Client-Hints version mismatch is a strong fingerprinting tell)."""
    try:
        exe = exe_override or p.chromium.executable_path
        result = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout + result.stderr)
        return match.group(1) if match else None
    except Exception:
        return None


def _known_extension_id(folder_path: str):
    """The extension ID Chrome will compute for this unpacked folder, from
    its manifest's "key" field — same algorithm Chrome itself uses, so
    it's the real, stable ID regardless of the folder's path. Returns None
    if the manifest has no "key" (an ID would then only be derivable from
    the path hash, which isn't worth replicating ourselves — see
    _worker_extension_ids, used as a fallback for exactly that case)."""
    manifest_path = Path(folder_path) / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    key_b64 = manifest.get("key")
    if not key_b64:
        return None
    try:
        der = base64.b64decode(key_b64)
        digest = hashlib.sha256(der).digest()[:16]
        return "".join(chr(ord("a") + (b >> 4)) + chr(ord("a") + (b & 0xF)) for b in digest)
    except Exception:
        return None


def discover_extensions() -> list[str]:
    """Every subfolder of extensions/ containing a manifest.json gets loaded
    into every profile — the same set, every time, so extension behaviour
    stays consistent across all profiles rather than varying per-profile."""
    if not EXTENSIONS_DIR.exists():
        return []
    paths = []
    for sub in sorted(EXTENSIONS_DIR.iterdir()):
        if sub.is_dir() and (sub / "manifest.json").exists():
            paths.append(str(sub.resolve()))
    return paths


def ensure_extensions_enabled(context, ext_ids: list[str]):
    """Chrome persists a per-extension "user disabled this" override
    inside the profile itself, separate from --load-extension reloading
    the extension's files fresh every launch — so an extension toggled
    off via chrome://extensions comes back disabled on the next launch
    even though its files are right there again. Required extensions are
    meant to always come back ON after a tamper-triggered relaunch, not
    stay in whatever state they were left in, so this drives the real
    chrome://extensions UI (same as a person clicking the toggle) to flip
    any disabled required extension back on, right after launch and
    before monitoring starts."""
    if not ext_ids:
        return
    try:
        ext_page = context.new_page()
        ext_page.goto("chrome://extensions/", timeout=5000)
        for ext_id in ext_ids:
            try:
                item = ext_page.locator(f'extensions-item[id="{ext_id}"]')
                if item.count() == 0:
                    print(f"ensure_extensions_enabled: {ext_id} not found on chrome://extensions "
                          "— may not have loaded.")
                    continue
                toggle = item.locator("#enableToggle")
                if toggle.count() == 0:
                    print(f"ensure_extensions_enabled: {ext_id} found but no #enableToggle — "
                          "Chrome version may use different markup.")
                    continue
                if toggle.get_attribute("aria-pressed") == "false":
                    toggle.click()
                    print(f"Re-enabled required extension {ext_id} (was left disabled from last session).")
            except Exception as e:
                print(f"ensure_extensions_enabled: couldn't check/re-enable {ext_id}: {e}")
        ext_page.close()
    except Exception as e:
        print(f"ensure_extensions_enabled: couldn't open chrome://extensions ({e})")


def ensure_extensions_incognito_allowed(context, ext_ids: list[str]):
    """Same idea as ensure_extensions_enabled, for the separate "Allow in
    Incognito" permission on each extension's details page
    (chrome://extensions/?id=<id>) — Chrome persists this per-extension
    too, so it needs the same treatment: drive the real toggle back on
    for any required extension that's had it turned off, right after
    launch and before monitoring starts."""
    if not ext_ids:
        return
    for ext_id in ext_ids:
        try:
            detail_page = context.new_page()
            detail_page.goto(f"chrome://extensions/?id={ext_id}", timeout=5000)
            row = detail_page.locator("extensions-toggle-row#allow-incognito")
            if row.count() == 0:
                print(f"ensure_extensions_incognito_allowed: {ext_id} has no allow-incognito row "
                      "— may not have loaded, or Chrome version uses different markup.")
                detail_page.close()
                continue
            toggle = row.locator("cr-toggle")
            if toggle.count() == 0:
                print(f"ensure_extensions_incognito_allowed: {ext_id} allow-incognito row found but "
                      "no cr-toggle inside it — Chrome version may use different markup.")
                detail_page.close()
                continue
            if toggle.get_attribute("aria-pressed") == "false":
                toggle.click()
                print(f"Re-enabled 'Allow in Incognito' for required extension {ext_id} "
                      "(was left off from last session).")
            detail_page.close()
        except Exception as e:
            print(f"ensure_extensions_incognito_allowed: couldn't check/re-enable {ext_id}: {e}")


def ensure_developer_mode_enabled(context):
    """chrome://extensions has one global "Developer mode" toggle (not
    per-extension, unlike the two functions above it) — Chrome restricts
    some capabilities for extensions not installed from the Web Store
    unless it's on (seen in testing: Cold Turkey Blocker's native-
    messaging-dependent features requiring it). Flips it on if it's off,
    right after launch and before monitoring starts, same as the
    enabled/incognito fixes above."""
    try:
        page = context.new_page()
        page.goto("chrome://extensions/", timeout=5000)
        toggle = page.locator("#devMode")
        if toggle.count() == 0:
            print("ensure_developer_mode_enabled: #devMode toggle not found on chrome://extensions "
                  "— may not have loaded, or Chrome version uses different markup.")
            page.close()
            return
        if toggle.get_attribute("aria-pressed") == "false":
            toggle.click()
            print("Enabled 'Developer mode' (was off from last session).")
        page.close()
    except Exception as e:
        print(f"ensure_developer_mode_enabled: couldn't check/enable: {e}")


def _developer_mode_enabled(probe_page):
    """True/False if we could positively determine Developer mode's
    state, or None if we couldn't tell (page/selector failure) — same
    "don't act on an unknown reading" caution as _extension_incognito_allowed,
    so a broken selector can't trigger a false tamper-close."""
    try:
        probe_page.goto("chrome://extensions/", timeout=3000)
        toggle = probe_page.locator("#devMode")
        if toggle.count() == 0:
            return None
        return toggle.get_attribute("aria-pressed") == "true"
    except Exception:
        return None


def _extension_incognito_allowed(probe_page, ext_id: str):
    """True/False if we could positively determine the "Allow in
    Incognito" toggle's state on this extension's details page, or None
    if we couldn't tell (page/selector failure) — callers should treat
    None as "don't know, don't act on it" rather than assuming either
    way, since a broken selector shouldn't be able to trigger a false
    tamper-close."""
    try:
        probe_page.goto(f"chrome://extensions/?id={ext_id}", timeout=3000)
        row = probe_page.locator("extensions-toggle-row#allow-incognito")
        if row.count() == 0:
            return None
        toggle = row.locator("cr-toggle")
        if toggle.count() == 0:
            return None
        return toggle.get_attribute("aria-pressed") == "true"
    except Exception:
        return None


def _worker_extension_ids(context) -> set:
    """Extension IDs with a currently-live MV3 service worker or MV2
    background page — used only to discover which extension IDs actually
    got loaded at startup (Chrome assigns the real ID; for extensions
    without a manifest "key" this is the only reliable way to learn it, no
    replicating Chrome's own path-hash algorithm ourselves). NOT used for
    ongoing removal detection — an idle, unloaded MV3 worker looks
    identical to a removed extension here, which is exactly what caused
    false-positive closes before."""
    ids = set()
    try:
        for w in context.service_workers:
            m = re.match(r"chrome-extension://([a-z]{32})/", w.url)
            if m:
                ids.add(m.group(1))
    except Exception:
        pass
    try:
        for bp in context.background_pages:
            m = re.match(r"chrome-extension://([a-z]{32})/", bp.url)
            if m:
                ids.add(m.group(1))
    except Exception:
        pass
    return ids


def _extension_reachable(probe_page, ext_id: str) -> bool:
    """True if chrome-extension://<id>/manifest.json still loads. Chrome
    always serves an installed extension's own manifest.json this way,
    regardless of web_accessible_resources and regardless of whether its
    background service worker happens to be awake right now — so this
    fails immediately and unambiguously the moment an extension is
    actually disabled/removed, without the idle-worker false positives
    that plagued the earlier approach. It's also unaffected by the
    Secure Preferences problem found in testing: extensions loaded via
    --load-extension never get written there at all, which is why that
    approach couldn't detect anything (baseline was always empty).

    IMPORTANT: chrome-extension:// isn't a real network-backed navigation,
    so Playwright's page.goto() returns None for the Response object here
    even on a completely successful load — checking response.ok (as a
    previous version of this did) treated every navigation, including
    working ones, as a failure and closed the profile on the very first
    poll regardless of whether anything was actually touched. The only
    two real failure signals are: goto() raising (net::ERR_FAILED etc,
    thrown when the extension truly isn't there), or landing on Chrome's
    own internal error page instead of the extension's origin."""
    try:
        probe_page.goto(f"chrome-extension://{ext_id}/manifest.json", timeout=3000)
    except Exception as e:
        # ERR_BLOCKED_BY_CLIENT specifically means something intercepted
        # the request — an extension (e.g. a content/site blocker like
        # Cold Turkey Blocker, if it happens to have a rule broad enough
        # to catch chrome-extension:// URLs) or Chrome's own policy layer.
        # That's a DIFFERENT thing from the extension genuinely not being
        # there — treating it as a miss caused exactly the false-positive
        # relaunch loop this comment is now warning about: the required
        # extension itself was blocking our own health check of it,
        # closing/reopening the profile over and over for no real reason.
        # Only an actual failure to reach the resource (ERR_FAILED, the
        # extension not found, etc.) should count against it — an
        # inconclusive "something blocked this probe" should not.
        if "ERR_BLOCKED_BY_CLIENT" in str(e):
            print(f"  [extension probe] {ext_id}: request blocked by something (not necessarily the "
                  "extension itself missing) — not counting this as a miss.")
            return True
        print(f"  [extension probe] {ext_id}: goto raised {e.__class__.__name__}: {e}")
        return False
    if probe_page.url.startswith("chrome-error://"):
        print(f"  [extension probe] {ext_id}: landed on {probe_page.url} — extension not there")
        return False
    return True


def _drain_commands(page, commands, stop_event):
    """Runs any queued page commands (go to a URL, scroll...) on THIS thread -
    the one that owns Playwright, so it's the only one allowed to touch the
    page. Each queued item is (fn, done) where done is a dict with an
    "event" that gets set when fn finishes (and "error" if it raised)."""
    if commands is None:
        return
    import queue as _queue
    while True:
        try:
            fn, done = commands.get_nowait()
        except _queue.Empty:
            return
        try:
            fn(page, stop_event)
        except Exception as e:  # noqa: BLE001 - reported back to whoever queued it
            done["error"] = str(e)
        finally:
            done["event"].set()


def _wait_until_closed(page, stop_event=None, commands=None, tick=None, tick_every=20.0):
    """Blocks until the page's window closes - or, if a stop_event is given,
    until something (the app's Close button / the local API) sets it. While
    waiting it also runs queued page commands. Must run on the thread that
    owns Playwright, which is why "close" is a flag this thread notices
    rather than a call made from another thread."""
    if stop_event is None and commands is None and tick is None:
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        return
    last_tick = time.time()
    while stop_event is None or not stop_event.is_set():
        try:
            _drain_commands(page, commands, stop_event)
            page.wait_for_timeout(300)
            if page.is_closed():
                return
            if tick is not None and time.time() - last_tick >= tick_every:
                last_tick = time.time()
                tick()
        except Exception:
            return


def _close_stray_tabs(context, keep_page):
    """Closes every tab except the profile's main one. Chromium restores the
    previous session's tabs into a persistent profile, so old test tabs
    (History, Settings...) kept coming back on every launch."""
    try:
        for pg in list(context.pages):
            if pg is keep_page:
                continue
            try:
                pg.close()
            except Exception:
                pass
    except Exception:
        pass


def run_extension_monitor_loop(context, page, known_ids: list[str] = None, stop_event=None, commands=None) -> bool:
    """Runs the extension-tampering check as a polling loop on the CALLING
    thread — deliberately NOT its own background thread. An earlier
    version used threading.Thread for this, and every call that needed an
    actual round-trip to the browser (like context.new_page()) failed with
    a greenlet "cannot switch to a different thread" error — Patchright/
    Playwright's sync API is bound to whichever thread created it, and
    that's the thread running launch()'s `with sync_playwright()` block,
    not some other background thread. Cheap property reads
    (service_workers/background_pages) happened to work cross-thread,
    which is what made the baseline detection look fine while the probe
    page silently failed right after — everything here runs on the same
    thread specifically to avoid that whole class of bug.

    Blocks until either the window is closed normally or tampering is
    detected and closes it. Returns True if it closed the profile because
    of tampering (caller should relaunch), False for a normal close or if
    there was nothing to monitor (caller should just exit).

    known_ids (from each extension's manifest "key" field, computed by
    build_context) is used as the baseline directly when available —
    deliberately NOT worker/background-page sampling for these, since that
    only shows extensions that are actually running, and a required
    extension that launched disabled (e.g. left that way from a previous
    session, before ensure_extensions_enabled() re-enables it) never spins
    one up, which is exactly why baseline used to come back empty right
    when it mattered most. Extensions without a manifest "key" (no
    known_ids entry) still fall back to that sampling, since there's no
    other reliable way to learn their path-derived ID.

    Once a baseline ID is established, ongoing monitoring is the same
    either way: directly trying to load each one's own manifest.json from
    its chrome-extension:// origin — something Chrome only serves for an
    extension that's genuinely still installed and enabled, regardless of
    worker idle state. Requires miss_threshold consecutive failures (not
    just one) before closing, as a small safety margin against a single
    transient navigation hiccup.

    Two things this deliberately does NOT use for ongoing checks, both
    tried and found wanting:
    - context.service_workers/background_pages presence, checked directly
      at each poll: MV3 service workers are event-driven and Chromium
      unloads an idle one after a short stretch of no activity — a
      perfectly normal, frequent occurrence that looks identical to
      removal if you're only checking "is a worker running right now".
    - Secure Preferences/Preferences on disk: confirmed in testing that
      extensions loaded via --load-extension are never written there at
      all (baseline always comes back empty), so it can't detect
      anything."""
    poll_interval_ms = 1500
    # (queued page commands from timed plans are also run inside every _sleep below)
    miss_threshold = 2

    def _sleep(ms):
        """True if still open after sleeping, False if the window closed
        during the wait."""
        if stop_event is not None and stop_event.is_set():
            return False
        try:
            _drain_commands(page, commands, stop_event)
            page.wait_for_timeout(ms)
            return not page.is_closed() and not (stop_event is not None and stop_event.is_set())
        except Exception:
            return False

    if not _sleep(2000):  # let extensions finish initializing after launch
        return False

    baseline = set(known_ids or [])
    if baseline:
        print(f"Extension monitor baseline (from manifest key): {sorted(baseline)}")
    else:
        for _ in range(4):  # sample over ~4s so a transiently-idle worker still gets seen
            baseline |= _worker_extension_ids(context)
            if not _sleep(1000):
                return False
        print(f"Extension monitor baseline (from running workers): {sorted(baseline) or '(none detected)'}")
    if not baseline:
        print("Extension monitor: no required extensions detected — nothing to monitor.")
        _wait_until_closed(page, stop_event, commands)
        return False

    try:
        probe_page = context.new_page()
    except Exception as e:
        print(f"Extension monitor: couldn't open probe page ({e}) — falling back to just "
              "waiting for the window to close normally, with no tampering protection.")
        _wait_until_closed(page, stop_event, commands)
        return False

    misses = {ext_id: 0 for ext_id in baseline}
    incognito_misses = {ext_id: 0 for ext_id in baseline}
    incognito_check_every = 4  # heavier check (full page nav) — every ~6s at 1.5s polls, not every poll
    miss_threshold_incognito = 2
    dev_mode_misses = 0
    miss_threshold_dev_mode = 2
    poll_num = 0
    while True:
        if page.is_closed() or (stop_event is not None and stop_event.is_set()):
            return False

        still_missing = set()
        for ext_id in baseline:
            if _extension_reachable(probe_page, ext_id):
                misses[ext_id] = 0
            else:
                misses[ext_id] += 1
                if misses[ext_id] >= miss_threshold:
                    still_missing.add(ext_id)

        poll_num += 1

        incognito_off = set()
        dev_mode_off = False
        if poll_num % incognito_check_every == 0:  # same reduced cadence — both are full page navigations
            for ext_id in baseline:
                allowed = _extension_incognito_allowed(probe_page, ext_id)
                if allowed is None:
                    continue  # couldn't tell — don't act on an unknown reading
                if allowed:
                    incognito_misses[ext_id] = 0
                else:
                    incognito_misses[ext_id] += 1
                    if incognito_misses[ext_id] >= miss_threshold_incognito:
                        incognito_off.add(ext_id)

            dev_mode_enabled = _developer_mode_enabled(probe_page)
            if dev_mode_enabled is None:
                pass  # couldn't tell — don't act on an unknown reading
            elif dev_mode_enabled:
                dev_mode_misses = 0
            else:
                dev_mode_misses += 1
                if dev_mode_misses >= miss_threshold_dev_mode:
                    dev_mode_off = True

        if poll_num % 5 == 0:  # heartbeat every ~5 polls so it's visible without spamming
            print(f"Extension monitor heartbeat: misses so far = {misses}, "
                  f"incognito misses so far = {incognito_misses}, dev mode misses = {dev_mode_misses}")

        if still_missing:
            print(f"Required extension(s) unreachable for {miss_threshold} consecutive checks "
                  f"({sorted(still_missing)}) — closing profile. Relaunching this profile will "
                  "reload it fresh.")
            try:
                context.close()
            except Exception:
                pass
            return True

        if incognito_off:
            print(f"Required extension(s) had 'Allow in Incognito' turned off "
                  f"({sorted(incognito_off)}) — closing profile. Relaunching this profile will "
                  "turn it back on.")
            try:
                context.close()
            except Exception:
                pass
            return True

        if dev_mode_off:
            print("'Developer mode' was turned off — closing profile. Relaunching this profile "
                  "will turn it back on.")
            try:
                context.close()
            except Exception:
                pass
            return True

        if not _sleep(poll_interval_ms):
            return False


def build_context(p, profile: dict, headless: bool = False, debug_port: int | None = None, display_number: int | None = None):
    """Launches a persistent Chromium context for this profile and returns
    (context, page). Persistent context (not the old ephemeral browser +
    context.new_context()) is what's required for Chromium to load
    extensions at all — as a side effect, profile data (cookies, local
    storage) now persists automatically in its own user_data_dir instead of
    needing an explicit storage_state save/load step.

    debug_port, if given, exposes Chromium's remote debugging port so an
    external script can connect_over_cdp() into this exact browser instance
    and drive it independently — this is the automation API's hook."""
    profile_id = profile.get("profile_id", "profile")
    user_data_dir = USER_DATA_ROOT / profile_id
    user_data_dir.mkdir(parents=True, exist_ok=True)

    # Prefer Trickster's own Chromium (no "Chrome for Testing" bar or Test icon).
    # If it isn't installed, or fails to start, the patchright browser is used.
    own_exe = None
    try:
        import chromium_engine
        own_exe = chromium_engine.installed_exe() if sys.platform == "win32" else None
    except Exception as e:
        print(f"Own browser engine unavailable ({e}) - using the standard one.")
    real_version = get_chromium_version(p, own_exe)
    user_agent = profile["user_agent"]
    if real_version:
        corrected = re.sub(r"Chrome/[\d.]+", f"Chrome/{real_version}", user_agent)
        if corrected != user_agent:
            print(f"Note: corrected UA Chrome version to match installed Chromium ({real_version})")
        user_agent = corrected
    else:
        print("Note: could not detect installed Chromium version — UA left as configured in profile.")

    is_mobile = profile.get("is_mobile", False)

    args = []
    if debug_port:
        args.append(f"--remote-debugging-port={debug_port}")
    if not is_mobile:
        # Desktop/laptop profiles: don't force Chromium's real window to a
        # fixed content viewport. Some profiles are assigned spoofed
        # resolutions (e.g. 2560x1440) larger than the physical monitor —
        # launch_persistent_context(viewport=...) makes Chromium create a
        # real OS window exactly that size no matter the screen, so on a
        # smaller monitor the window extends off the right/bottom edge
        # with buttons unreachable (there's no "un-maximize"/drag fix,
        # since Playwright pins the content area itself). Instead let the
        # window behave like a normal maximized browser sized to the real
        # screen, and spoof screen.width/height in the injection script
        # (fingerprint_injection.js) so the fingerprint still reports the
        # profile's assigned resolution.
        args.append("--start-maximized")

    # Never offer to "restore pages" / reopen last session's tabs.
    args += ["--hide-crash-restore-bubble", "--disable-session-crashed-bubble", "--no-first-run"]

    extension_paths = discover_extensions()
    if extension_paths:
        joined = ",".join(extension_paths)
        args.append(f"--disable-extensions-except={joined}")
        args.append(f"--load-extension={joined}")
        if headless:
            print(f"Note: {len(extension_paths)} extension(s) configured — extensions generally "
                  "don't load in headless mode, forcing a visible window.")
            headless = False

    launch_kwargs = {
        "user_data_dir": str(user_data_dir),
        "headless": headless,
        "user_agent": user_agent,
        "locale": profile["locale"],
        "timezone_id": profile["timezone_id"],
        "geolocation": profile.get("geolocation"),
        "permissions": ["geolocation"] if profile.get("geolocation") else [],
        "args": args,
    }

    if is_mobile:
        # Mobile/tablet profiles are legitimately small (phones/tablets),
        # so forcing this exact viewport never puts the window off-screen
        # — and a fixed viewport is what makes touch/meta-viewport
        # emulation behave correctly in the first place. deviceScaleFactor
        # / isMobile / hasTouch are only valid alongside a real viewport
        # (Playwright rejects them outright when viewport is null), so
        # they're only ever added in this branch.
        launch_kwargs["viewport"] = profile["viewport"]
        launch_kwargs["is_mobile"] = True
        launch_kwargs["has_touch"] = profile.get("has_touch", False)
        launch_kwargs["device_scale_factor"] = profile.get("device_scale_factor", 1)
    else:
        # Real window size, driven by --start-maximized above, not a
        # forced content-area size. See the args-building comment above.
        launch_kwargs["no_viewport"] = True

    proxy = profile.get("proxy")
    if proxy and proxy.get("server") and "your-proxy-host" not in proxy["server"]:
        if proxy.get("username") and proxy.get("password"):
            # Route through a local relay that authenticates to the real
            # proxy on Chromium's behalf, instead of handing Chromium the
            # authenticated proxy directly — works around a known
            # limitation where Playwright's automatic proxy-auth handling
            # doesn't reliably work with launch_persistent_context, even
            # though the exact same proxy works fine in a normal browser.
            # See local_proxy_relay.py for the full explanation.
            parsed = urllib.parse.urlparse(proxy["server"])
            upstream_host = parsed.hostname
            upstream_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            local_port = start_local_proxy_relay(upstream_host, upstream_port, proxy["username"], proxy["password"])
            launch_kwargs["proxy"] = {"server": f"http://127.0.0.1:{local_port}"}
        else:
            launch_kwargs["proxy"] = {"server": proxy["server"]}

    # Snapshot existing Chromium windows right before actually launching —
    # apply_taskbar_identity() below uses this to find the new window by
    # elimination (present after, wasn't present before) rather than
    # guessing at title text, which proved unreliable on its own. Has to
    # happen here, immediately pre-launch, not later near where
    # apply_taskbar_identity is actually called — by then other windows
    # may already have appeared and been missed by the snapshot.
    #
    # profile_dock.py lives in gui/, not next to launcher.py — a plain
    # "import profile_dock" only works when gui/ happens to already be on
    # sys.path, which was true when launched via gui/app.py (it inserts
    # its own directory) but NOT true for a standalone script that just
    # does "import launcher" from anywhere else (examples/*.py, a custom
    # automation script, etc.) — it would silently skip taskbar branding
    # there instead. Locating it by a path relative to this file instead
    # of relying on the caller's sys.path fixes that for every caller,
    # not just gui/app.py. Imported once here (not again later) and reused.
    profile_dock = None
    _pre_launch_hwnds = set()
    try:
        import importlib.util
        _profile_dock_path = Path(__file__).parent / "gui" / "profile_dock.py"
        if not _profile_dock_path.exists():
            raise FileNotFoundError(
                f"{_profile_dock_path} doesn't exist — if this is a frozen exe, it needs "
                '--add-data "gui/profile_dock.py;gui" in build_exe.bat (PyInstaller compiles '
                "imported modules into its own bundle by default; this file is loaded by raw "
                "path instead, on purpose, so it works from standalone scripts too — which "
                "means it has to be bundled as loose data explicitly, or it just isn't there.")
        _spec = importlib.util.spec_from_file_location("profile_dock", _profile_dock_path)
        profile_dock = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(profile_dock)
        _pre_launch_hwnds = profile_dock.snapshot_chromium_hwnds()
    except Exception as e:
        # Previously silent — meant a real cause (e.g. this file missing
        # from a frozen build) looked identical to "nothing's wrong,
        # taskbar branding just doesn't apply here," and only showed up
        # later as a confusing AttributeError when actually calling
        # apply_taskbar_identity below. Printed now so the real reason is
        # visible immediately instead.
        print(f"Taskbar identity setup skipped: {e}")
        profile_dock = None  # explicit — a partially-run exec_module could leave a broken module object otherwise

    context = None
    if own_exe:
        try:
            context = p.chromium.launch_persistent_context(executable_path=own_exe, **launch_kwargs)
            print(f"Using Trickster's own Chromium: {own_exe}")
        except Exception as e:
            print(f"Own Chromium failed to start ({e}) - falling back to the standard browser.")
            context = None
    if context is None:
        context = p.chromium.launch_persistent_context(**launch_kwargs)

    injection_script = build_injection_script(profile)
    context.add_init_script(injection_script)
    context.add_init_script(build_branding_script(profile, display_number))

    # Dedicated and service workers run in a separate JS realm that
    # add_init_script doesn't reach. Inject into each worker as soon as
    # it's created — note this runs AFTER the worker's own code has already
    # started, so it won't catch a value read synchronously at worker
    # startup, only values read later (a known, documented limitation).
    def inject_into_worker(worker):
        try:
            worker.evaluate(injection_script)
        except Exception as e:
            print(f"Worker injection skipped ({worker.url}): {e}")

    page = context.pages[0] if context.pages else context.new_page()
    _close_stray_tabs(context, page)  # tabs restored from the last session (History, Settings...)
    page.on("worker", inject_into_worker)
    context.on("serviceworker", inject_into_worker)
    page.on("load", lambda: apply_branding(page, profile, display_number))

    # The context's very first page (about:blank) already exists by the
    # time add_init_script() above runs, so that init script never reaches
    # it — init scripts only apply to documents created afterward. Normally
    # this is invisible because the first real navigation replaces that
    # page's document almost immediately. But if the proxy is broken and
    # every navigation attempt fails (aborts before committing a new
    # document), the browser stays on that original unbranded about:blank
    # forever — no 'load' event ever fires, so apply_branding() above never
    # runs either, and the window is stuck with Chromium's default title
    # and icon no matter how long anything waits on it. Branding this page
    # directly, right now, means the title/favicon/taskbar identity are
    # correct immediately and don't depend on the proxy or navigation
    # working at all.
    try:
        page.evaluate(build_branding_script(profile, display_number))
    except Exception as e:
        print(f"Initial branding skipped: {e}")

    # Per-profile taskbar identity (separate taskbar button + colored/
    # numbered icon per profile, ixBrowser-style) — safe no-op on
    # non-Windows or if pywin32/Pillow aren't installed. profile_dock was
    # already imported above (before launch, for the pre-launch window
    # snapshot) — reused here rather than importing it a second time.
    try:
        if profile_dock is None:
            raise RuntimeError("profile_dock failed to import earlier — see prior message")
        profile_id = profile.get("profile_id", "profile")
        color = seed_to_hex_color(profile.get("canvas_seed", 1))
        badge = str(display_number) if display_number is not None else (
            "".join(w[0] for w in profile_id.replace("_", " ").split()[:2]).upper() or "P"
        )
        profile_dock.apply_taskbar_identity(profile_id, color, badge, existing_hwnds=_pre_launch_hwnds)
    except Exception as e:
        print(f"Taskbar identity skipped: {e}")

    # Extension-tampering monitoring itself now happens in launch()'s
    # main loop via run_extension_monitor_loop() — not spawned as a
    # background thread here. Patchright/Playwright's sync API is bound to
    # whichever thread created it; a background thread trying to call
    # context.new_page() hit "cannot switch to a different thread" greenlet
    # errors. This just records what there is to monitor.
    context._required_extension_count = len(extension_paths)
    # Extensions with a manifest "key" have a real, known, stable ID we can
    # compute ourselves — no need to wait for a service worker to show up
    # (which never happens if the extension launched disabled, e.g. left
    # that way from a previous session). Extensions without one fall back
    # to worker/background-page sampling inside run_extension_monitor_loop.
    context._required_extension_known_ids = [
        eid for eid in (_known_extension_id(p) for p in extension_paths) if eid
    ]

    return context, page


def navigate(page, profile: dict, check_mode: bool = False, display_number: int | None = None, start_url: str | None = None):
    """Navigates to the starting page with retries — proxy connections
    occasionally fail on the first attempt (auth handshake hiccup, brief
    connectivity blip), which isn't usually a sign of misconfiguration, just
    something worth retrying rather than crashing on."""
    target_url = "https://abrahamjuliot.github.io/creepjs/" if check_mode else (
        start_url or profile.get("start_url") or "https://www.google.com/")
    if check_mode:
        print("Opening fingerprint check site...")

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            page.goto(target_url, timeout=30000)
            break
        except Exception as e:
            if attempt == max_attempts:
                print(f"Navigation failed after {max_attempts} attempts: {e}")
                print("Leaving the browser window open — try navigating manually, "
                      "or double-check the proxy's server/username/password are correct "
                      "and that this proxy endpoint is actually reachable right now.")
            else:
                print(f"Navigation attempt {attempt} failed, retrying in 2s... ({e.__class__.__name__})")
                time.sleep(2)
    apply_branding(page, profile, display_number)


def launch(profile: dict, headless: bool = False, check_mode: bool = False, debug_port: int | None = None, display_number: int | None = None, cloud=None, stop_event=None,
           start_url: str | None = None, ready_event=None, commands=None):
    """CLI entry point: launches a profile and blocks until its window is
    closed. For non-blocking launches (external automation), see
    api_server.py, which reuses build_context()/navigate() directly instead
    of this function.

    If a required extension gets disabled/removed mid-session
    (run_extension_monitor_loop detects it and force-closes the profile),
    this automatically relaunches the same profile fresh right away, so it
    comes straight back with the extension reinstalled rather than just
    staying closed. A normal, manual window close does NOT trigger this —
    only a close caused by tampering does.

    cloud: an optional CloudSync instance (see gui/cloud.py) — when given
    and signed in, this profile's session (cookies/logins, not its
    fingerprint config) is pulled from Supabase Storage right before
    launch and pushed back right after close, so a login made on one
    device is there the next time this same profile opens on any device
    signed into the same org. Both directions are best-effort: a sync
    problem never blocks the profile from actually launching or closing —
    see push_session/pull_session in cloud.py. Left as None (the default)
    for any caller that doesn't have a signed-in CloudSync to hand it
    (examples/*.py, api_server.py) — session sync is simply skipped."""
    profile_id = profile["profile_id"]
    user_data_dir = USER_DATA_ROOT / profile_id
    while True:
        if cloud is not None:
            cloud.pull_session(profile_id, user_data_dir)

        with sync_playwright() as p:
            context, page = build_context(p, profile, headless=headless, debug_port=debug_port, display_number=display_number)
            snapshot = {"state": None}
            if cloud is not None:
                # Load the logins saved by another computer (cookies) before the first page opens.
                try:
                    cookies = cloud.pull_state(profile_id, user_data_dir)
                    if cookies:
                        context.add_cookies(cookies)
                        print(f"Loaded {len(cookies)} saved login cookies for '{profile_id}'.")
                except Exception as e:
                    print(f"Couldn't load saved logins for '{profile_id}': {e}")

            def _take_snapshot():
                try:
                    snapshot["state"] = context.storage_state()
                except Exception:
                    pass

            navigate(page, profile, check_mode=check_mode, display_number=display_number, start_url=start_url)
            if ready_event is not None:
                ready_event.set()  # the window is up and has loaded its page (timed plans start their clock here)

            print(f"Profile '{profile_id}' launched. Close the browser window to exit.")
            if getattr(context, "_required_extension_count", 0):
                known_ids = getattr(context, "_required_extension_known_ids", [])
                ensure_extensions_enabled(context, known_ids)
                ensure_extensions_incognito_allowed(context, known_ids)
                ensure_developer_mode_enabled(context)
                # No more background "is the extension still there?" polling that
                # closed and relaunched the window - it caused profiles to keep
                # closing/reopening by themselves. The extensions are checked once
                # at launch (above) and then the window is simply left alone.
                _close_stray_tabs(context, page)
                _wait_until_closed(page, stop_event, commands, tick=_take_snapshot if cloud is not None else None)
                tampered = False
            else:
                _wait_until_closed(page, stop_event, commands, tick=_take_snapshot if cloud is not None else None)
                tampered = False
            if cloud is not None:
                _take_snapshot()  # last look, if the window is still open (e.g. Close button)

            try:
                context.close()
            except Exception:
                pass  # already closed, e.g. by the tamper monitor itself

        if cloud is not None:
            cloud.push_session(profile_id, user_data_dir)
            cloud.push_state(profile_id, user_data_dir, snapshot.get("state"))

        if tampered and not (stop_event is not None and stop_event.is_set()):
            print(f"Profile '{profile_id}' was closed because a required extension was "
                  "tampered with — relaunching fresh with it reinstalled.")
            # A longer pause than before — Windows can still be holding a
            # file lock on something in this profile's Default/ dir for a
            # moment after Chromium closes (this is what caused the
            # "[Errno 22] Invalid argument" / "already in use" failures
            # seen in testing: pull_session's restore and the relaunch
            # itself both landed while the previous process was still
            # finishing its shutdown). 3s gives it more room to fully let
            # go before the next pull_session + launch attempt.
            time.sleep(3)
            continue
        return


def main():
    parser = argparse.ArgumentParser(description="Launch a fingerprinted browser profile")
    parser.add_argument("profile_path", help="Path to profile JSON config")
    parser.add_argument("--headless", action="store_true", help="Run without a visible window")
    parser.add_argument("--check", action="store_true", help="Open CreepJS to test the fingerprint")
    parser.add_argument("--debug-port", type=int, default=None,
                         help="Expose Chromium's remote debugging port for external automation scripts")
    args = parser.parse_args()

    if not Path(args.profile_path).exists():
        print(f"Profile not found: {args.profile_path}", file=sys.stderr)
        sys.exit(1)

    profile = load_profile(args.profile_path)
    launch(profile, headless=args.headless, check_mode=args.check, debug_port=args.debug_port)


if __name__ == "__main__":
    main()
