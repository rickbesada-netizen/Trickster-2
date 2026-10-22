# Trickster - Antidetect application

A minimal, working profile-based browser launcher. One profile = one consistent
fingerprint + proxy + persistent cookies. This is step 1 of the plan: prove
the fingerprinting approach works before building anything else on top of it.

## Setup

```bash
pip install -r requirements.txt
patchright install chromium
```

`patchright` is a patched fork of Playwright specifically built to avoid the
CDP-level detection signals that trip up stock Playwright/Puppeteer + stealth
plugins.

## Usage

Edit `profiles/profile_example.json` with a real proxy (or remove the proxy
block to run without one), then:

```bash
python launcher.py profiles/profile_example.json
```

To check what the browser actually leaks, run it against CreepJS:

```bash
python launcher.py profiles/profile_example.json --check
```

CreepJS will score your fingerprint's consistency and flag anything that
looks spoofed or contradictory (e.g. timezone not matching geolocation, or a
canvas hash that doesn't match the claimed GPU). This is your feedback loop —
tweak the profile config and injection script, re-run, re-check.

## Generating many profiles at once

To generate 50 (or any number) of internally-consistent profiles at once
instead of hand-editing each one:

```bash
python generate_profiles.py --count 50
```

This picks an OS (Windows or macOS, weighted toward Windows since it's more
common) for each profile, then samples UA/platform/GPU/fonts/hardware/screen
all from *within that OS's pool* — so you never get a Windows UA paired with
a macOS GPU string, or a laptop-class CPU count with a desktop-class RAM
figure. Every profile also gets a unique `canvas_seed`.

By default every generated profile has the placeholder proxy block — either
fill each one in by hand, or if you have a list of proxies, generate with
them assigned automatically:

```bash
python generate_profiles.py --count 50 --proxies my_proxies.json
```

where `my_proxies.json` is a list like:
```json
[
  {"server": "http://host1:port", "username": "user1", "password": "pass1"},
  {"server": "http://host2:port", "username": "user2", "password": "pass2"}
]
```
Proxies are assigned round-robin across the batch.

**Important**: the generator does NOT know where your proxies actually
exit, so it can't match `timezone_id`/`locale`/`geolocation` to them
automatically — those are picked from a locale pool independent of
whichever proxy ends up assigned. After generating, spot-check a few
profiles' timezone against their assigned proxy's real exit location
(same mismatch check as with a single profile) and adjust by hand if
they don't line up. This matters — proxy country vs. spoofed
timezone/locale mismatch is one of the strongest detection signals, same
severity as the UA/Client-Hints issue from earlier testing.

Useful flags: `--seed 42` for reproducible output (same batch every time),
`--output-dir` to write somewhere other than `profiles/`.

## Device templates

`device_templates/` has three ready-made, internally-consistent device
profiles you can copy into `profiles/` and use directly, or as a starting
point for your own:

- `windows_desktop_nvidia.json` — desktop-class hardware, dedicated GPU
- `windows_laptop_intel.json` — laptop-class hardware, integrated GPU
- `macos_desktop.json` — macOS UA/platform/fonts/GPU strings (see the
  `_note` field in that file for an important caveat: the actual Chromium
  binary is still Windows underneath, so this only spoofs what's readable
  via JavaScript, not deeper OS-level behaviour)

When making your own, keep these three groups internally consistent —
mixing them is exactly the kind of contradiction CreepJS flags:
1. **OS + platform + GPU** — `user_agent`, `platform`, `webgl_vendor`/
   `webgl_renderer` all need to describe the same machine.
2. **CPU + RAM + screen size** — `hardware_concurrency`, `device_memory`,
   `viewport` should be proportionate to the device class (a "budget
   laptop" claiming 32 cores and 64GB RAM stands out).
3. **Fonts + locale + uniqueness** — `fonts` should match the claimed OS
   (Windows fonts on a macOS profile is an instant giveaway), `timezone_id`/
   `locale`/`geolocation` should match wherever the proxy exits, and
   `canvas_seed` should differ per profile so no two profiles render
   identically even on paper-identical hardware.

## How it works

- `launcher.py` reads a profile JSON and launches Chromium via patchright
  with that profile's user agent, viewport, locale, timezone, geolocation,
  and proxy.
- `fingerprint_injection.js` is injected into every page before any site JS
  runs. It adds seeded noise to canvas/audio output and overrides
  navigator/WebGL properties, so the same profile always produces the same
  fingerprint, but different profiles produce different ones.
- `context.storage_state()` persists cookies/localStorage per profile between
  runs, so a profile stays "logged in" like a real persistent browser
  profile would.

## Known remaining gaps (as of third CreepJS test)

**This section changed meaningfully this round — read it, not just the
headline "gaps" list.**

- **toString detection — attempted fix REVERTED, made things worse.**
  Globally overriding `Function.prototype.toString` to mask patched
  functions as `[native code]` is itself one of the most heavily-tested
  stealth signatures — tools like CreepJS commonly grab a pristine
  `toString` from a hidden iframe's separate JS realm, which bypasses the
  masking and exposes the override's real source as an even stronger
  tampering signal. Confirmed by testing: stealth score went from 20% to
  40% (plus a new 33% "headless-like" signal) after adding the masking.
  Reverted. **This class of leak cannot be reliably closed with a JS
  override** — it needs an engine-level (C++) patch, which is out of scope
  for this project (see the original scoping decision: solo/amateur build,
  Chromium fork ruled out).
- **Worker thread leak — fix applied, confirmed NOT working, root cause
  understood.** `worker.evaluate()` injects overrides into new workers, but
  only after Playwright detects the worker and round-trips a command to it
  — CreepJS's own worker script reads `navigator.deviceMemory` faster than
  that round-trip completes, so the real value gets read first. This is a
  timing/race condition inherent to script-injection-based approaches, not
  a bug to fix with more code. Same underlying wall as the toString issue:
  closing it needs the value spoofed before the worker's JS starts, which
  only an engine patch can guarantee.
- **Fonts — still open (DOM-based part).** Canvas-based font probing is
  fixed. DOM-based font probing (hidden `<span>` measurement,
  `document.fonts.load()`) is not, for the same reason as above — real
  layout/font-loading engine, not an overridable JS API.
- **Canvas noise trade-off**: CreepJS explicitly flags "rgba noise" as a
  detection signal in its own right — real browsers don't add per-pixel
  randomness, so heavy noise can itself be the tell. Worth testing lighter
  noise levels (or none, relying on other differentiators) and comparing
  CreepJS's trust score each way.

## Where this leaves the project

Three separate tests now point at the same wall: **worker-thread values and
function-provenance checks (toString, cross-realm inspection) are the
practical ceiling of what a pure JS-injection browser can spoof**, no
matter how much the injection script is refined. This isn't a sign the
approach failed — the UA/Client-Hints fix and WebGL fix from earlier rounds
both worked and hold up. It's a sign we've reached the boundary that was
flagged at the very start of this project: JS-injection is "good enough for
the vast majority of real use cases" but won't beat a tool built
specifically to catch it, like CreepJS is.

Worth deciding explicitly: is beating CreepJS itself the goal, or is it a
stand-in for realistic production anti-fraud checks (which are typically
less exhaustive)? If the latter, the current state — UA/Client Hints
consistent, WebGL/canvas/audio spoofed, WebRTC leak-blocked, timezone/geo
consistent — may already be enough for real targets, and chasing CreepJS's
last few percentage points may not be worth more time relative to moving on
to proxy testing and multi-profile work.

## Next steps once this works

1. Decide: keep chasing CreepJS's remaining signals, or treat current state
   as "good enough" and move on (see discussion above).
2. If moving on: plug in a real proxy and re-run `--check` to confirm
   geolocation/timezone stay consistent with wherever it actually exits.
3. Canvas noise tuning (lighter or none) — the one remaining tunable that
   doesn't require an engine patch.
4. Add more profiles, confirm each gets a distinct-but-consistent
   fingerprint, with no version/Client-Hints contradictions.
5. Build a simple CLI or JSON-driven batch launcher for multiple profiles at
   once (you've already done similar batch work with your ixBrowser tool).
6. Only once this is solid: wrap it in the Electron shell + cloud backend
   from the architecture diagram.

## GUI

`gui/app.py` wraps the CLI in an actual window — a profile grid with a
"fingerprint" glyph per card, generate/launch buttons, no terminal or JSON
editing required for day-to-day use.

```bash
python gui/app.py
```

It calls the same `launcher.py`/`generate_profiles.py` you'd run manually —
the GUI is a thin layer on top, not a separate implementation. Editing
proxies still means editing the profile JSON directly for now (a proper
proxy-editing form is a reasonable next addition, not yet built).

## Packaging as an EXE

**This must be built on Windows** — PyInstaller doesn't cross-compile, so
running it from Linux/macOS produces a Linux/macOS binary, not a `.exe`.

```powershell
pip install -r requirements.txt
build_exe.bat
```

That script runs:
```powershell
pyinstaller --name Trickster --onefile --windowed --noconfirm ^
  --add-data "gui/web;gui/web" ^
  --add-data "fingerprint_injection.js;." ^
  --add-data "gui/cloud_config.json;gui" ^
  --add-data "gui/profile_dock.py;gui" ^
  --add-data "extensions;extensions" ^
  --hidden-import win32gui ^
  --hidden-import win32con ^
  --hidden-import win32comext.propsys.propsys ^
  --hidden-import win32comext.propsys.pscon ^
  --hidden-import pythoncom ^
  --hidden-import pywintypes ^
  --hidden-import PIL.Image ^
  --hidden-import PIL.ImageDraw ^
  --collect-all patchright ^
  gui/app.py
```

Produces a single `Trickster.exe` in `dist/`. Two structural things
were fixed to make this actually work once frozen, not just in development:

- **Generate/Launch no longer spawn a separate Python process.** They used
  to call `subprocess.run([sys.executable, ...])`, which works fine when
  you're running `python gui/app.py` directly (a real Python interpreter),
  but once frozen, `sys.executable` points at the `.exe` itself — those
  buttons would have silently failed for actual customers. They now import
  and call the underlying functions directly instead.
- **Bundled vs. persistent file locations are now separated.** Things
  baked into the `.exe` (the web UI files, the fingerprint script) extract
  to a temp folder that's wiped after each run — fine, since they're
  read-only. Things that need to survive between runs (`profiles/`,
  `extensions/`, session tokens) now live in the folder the `.exe` itself
  sits in, so it behaves like a normal portable app: unzip once, run it
  from wherever, everything stays put.

Two things still worth knowing before handing this to real customers:

- **It will very likely trigger a Windows SmartScreen warning** ("Windows
  protected your PC") the first time it's run, and may get flagged by
  antivirus software. This isn't a bug in the build — it's what happens to
  any unsigned executable, and it's *especially* likely here because this
  tool's actual behavior (automation + fingerprint spoofing + proxy
  routing) resembles patterns antivirus heuristics are built to catch.
  Fixing this properly requires a code signing certificate (an EV
  certificate specifically, to avoid SmartScreen's reputation checks),
  which costs money annually and needs a verifiable registered business —
  not something PyInstaller or any build step can route around.
- **Chromium downloads automatically on first run now** — the app shows a
  "Setting up the browser engine..." screen before anything else loads and
  runs the same install patchright's own CLI would (a ~300MB download the
  first time only; near-instant on every run after that, since it's a
  no-op once already present). No manual `patchright install chromium`
  step needed for people running the built exe. It calls into patchright's
  bundled installer directly rather than shelling out to `patchright
  install` as a subprocess of the app's own exe — `sys.executable` points
  at `Trickster.exe` itself once frozen, not a real Python
  interpreter, which is exactly the class of bug the Generate/Launch note
  above already had to work around.
- **Bundled extensions (AppBlocker Web Filter etc) seed themselves into
  place on first run** — `extensions/` is bundled into the exe as data
  (`--add-data "extensions;extensions"` in `build_exe.bat`) and copied
  into the writable/persistent `extensions/` folder next to the exe the
  first time the app runs, same pattern as the Chromium download above.
  A real customer never needs to manually copy an extensions folder into
  a `dist/` build themselves — that was only ever a dev-testing gotcha
  (rebuilding into a fresh `dist/` folder doesn't carry over anything
  that isn't actually bundled as data, which `extensions/`, like
  `profiles/`, wasn't before this). Extensions added later via the app's
  own Extension Management screen are never touched by this — it only
  ever seeds a folder that's missing, never overwrites one that exists.

For internal/personal testing this EXE is genuinely fine as-is — click
"More info" → "Run anyway" past the SmartScreen warning once. For public
distribution to people who won't know to do that, code signing stops being
optional.

## Cloud sync (Supabase)

Profiles can sync through a Supabase project so the same profiles are
visible whenever you sign in, from any machine. Local JSON files stay the
source of truth for actually *launching* a profile — sync is a manual
pull/push, not automatic, and `launcher.py` itself is unchanged.

### One-time setup

`gui/cloud_config.json` already ships with your real Supabase project URL
and anon key pre-filled — no manual setup step needed for this project
specifically. (`cloud_config.example.json` is still there as a template if
you ever point this at a different Supabase project — the anon key is
designed to be public/client-safe, that's what Row Level Security is for,
so there's no secret being exposed by shipping it filled in.)

The one thing that *is* still one-time-only: **run the schema.** In your
Supabase project: Dashboard → SQL Editor → New query → paste the contents
of `supabase/schema.sql` → Run. This creates the tables, Row Level Security
policies, and a trigger that automatically gives every new signup their own
private organization. Already done for this project as of this delivery,
but worth knowing if you ever spin up a fresh Supabase project.

`pip install supabase` is already in `requirements.txt`.

### Using it

In the GUI sidebar's "Cloud Sync" panel: **Sign up** once with an
email/password, confirm the email Supabase sends, then **Sign in**.
**Pull** downloads every profile in your organization and writes them as
local JSON files (overwriting any local file with the same name — pull
before you push if you're not sure which side is newer). **Push** uploads
your current local profiles up, upserted by profile ID.

### How access is scoped

Every profile belongs to an organization, not directly to a user:

- **Just you across devices**: sign in with the same account everywhere —
  you automatically got a personal organization on signup.
- **A small team sharing profiles**: everyone needs to belong to the same
  organization. There's no invite UI yet — for now, add a row to the
  `memberships` table in Supabase's Table Editor linking a teammate's
  `user_id` (from `auth.users`) to your `org_id`. A proper invite flow is a
  reasonable next addition, not yet built.
- **Multiple separate customers**: each person who signs up gets their own
  organization automatically — Row Level Security means they can never see
  each other's profiles, enforced by the database itself, not by app code.

### What I couldn't test from here

I don't have network access to an actual Supabase project from this
environment, so `cloud.py` and the sign-in/pull/push flow are
syntax-checked and logically reviewed, but not tested against a live
database. Test sign-up → sign-in → pull → push yourself and let me know
if anything errors — the error messages are written to be specific enough
to point at what's wrong (missing config, no org found, etc.), but real
API responses may surface something I haven't accounted for.

## Session persistence (cloud sign-in)

Signing in now sticks across app restarts — after a successful sign-in, the
session tokens are saved to `gui/.cloud_session.json` (gitignored, local
only) and automatically restored the next time you launch the GUI, so you
don't need to re-enter your email/password every time. Click "Sign out" in
the sidebar to clear it and require signing in again.

## Shared extensions across all profiles

Drop unpacked extension folders into `extensions/` (see
`extensions/README.md`) and every profile will load the same set, every
launch. This required a real architecture change: Chromium only loads
extensions in a **persistent context** (not the old ephemeral
browser + fresh context per launch), so `launcher.py` now uses
`launch_persistent_context()`.

Side effects of this change, both positive:
- **Profile data now persists automatically** in `profiles/user_data/<profile_id>/`
  — the old explicit `storage_state_path` save/load step is no longer
  needed (the field is still read from profile JSON for backward
  compatibility, but ignored).
- Extensions need a visible window — if any are configured, `launcher.py`
  automatically forces `--headless` off and prints a note explaining why.

## Automation API — driving profiles from your own scripts

`api_server.py` exposes a small local HTTP API mirroring ixBrowser's own
local API shape (same `/api/v2/...` endpoint paths, same default port
53200, same `{"error": {...}, "data": {...}}` response envelope) — a
script already written against ixBrowser's API needs only a `profile_id`
change, not a rewrite, to target this instead.

```bash
pip install -r requirements-api.txt
python api_server.py
```

Then, from a separate script:
```python
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
    page.reload()  # "refresh" — just a normal call over the same connection

# when done:
requests.post("http://localhost:53200/api/v2/profile-close",
               json={"profile_id": "profile_001_windows_desktop"})
```

A complete working version of this is in `examples/automation_example.py` —
run it with `python examples/automation_example.py profile_001_windows_desktop`
while `api_server.py` is running in another terminal.

**Endpoints**: `POST /api/v2/profile-list`, `POST /api/v2/profile-open`
(returns `data.ws`/`data.debugging_port`, does not block), `POST
/api/v2/profile-opened-list`, `POST /api/v2/profile-close`, `POST
/api/v2/profile-close-in-batches`, plus `POST /profiles/generate` (not
part of ixBrowser's API — its profiles come from its own UI/fingerprint
marketplace instead — but this project's equivalent for scripted profile
creation).

Two real differences from ixBrowser's actual API, worth knowing before
treating this as a drop-in replacement: `profile_id` here is this
project's own string identifier (e.g. `"profile_001_windows_desktop"`,
the filename stem already used everywhere else in this codebase), not
ixBrowser's integer one — remapping the whole profile system to numeric
IDs would be a much bigger, unrelated change. And there's no `pid` or
`webdriver` path in the response — patchright's persistent-context API
doesn't expose an OS process handle the way ixBrowser's closed-source
implementation apparently does, and this project doesn't bundle a
separate chromedriver binary per Chromium version the way ixBrowser
does; connect via the `ws` CDP endpoint instead.

**Important constraint**: Playwright's sync API must be called from the
single thread that started it, so `api_server.py` deliberately runs
single-threaded (Flask's dev server, not a production WSGI server). Don't
wrap it in gunicorn or similar without redesigning around that — it would
break in ways that are annoying to debug.

## Login-gated app + persistence (how it actually works)

The GUI now requires signing in before showing anything — no profile table,
no sidebar, nothing, until you're authenticated. This also fixed a real bug
(a CSS specificity issue where `hidden` elements could show anyway).

**What persists where:**
- **Local JSON files** (`profiles/*.json`) persist on disk regardless of
  cloud sign-in — closing and reopening the app, without touching cloud at
  all, still shows whatever's in that folder. This has always been true.
- **Cloud (Supabase)** persists profiles *to your account* — sign in on a
  different machine (or after wiping the local `profiles/` folder) and
  clicking Pull brings them back. This is what makes "my profiles follow me
  across devices" actually true, not just "files happen to still be on this
  one machine."
- On sign-in, the app **automatically pulls** your cloud profiles once —
  you don't need to click Pull manually just to see what you already have.
  Push still stays manual (a new batch you generate locally isn't uploaded
  until you click Push), so you're always in control of what leaves your
  machine.

## Editing a single profile's fingerprint from the GUI

Click the ⚙ button on any profile's row to open its full fingerprint
config — UA, platform, viewport, locale/timezone, CPU/RAM, canvas seed,
WebGL vendor/renderer, and fonts — and edit any of it directly, no manual
JSON editing required. This calls the same underlying fields
`generate_profiles.py` sets, so the same consistency rules apply: keep
OS/platform/GPU describing the same machine, and CPU/RAM/screen
proportionate to the device class you're going for.

## Mobile fingerprints (Android / iOS) + expanded pools

`profile_pools.py` now covers far more than 100 combinations: 37 Windows
GPUs, 11 macOS GPUs, 34 world locations, plus real Android and iOS device
bundles. Desktop platforms still mix GPU and hardware/screen independently
(any GPU legitimately pairs with any monitor on a real PC). Mobile
platforms use whole real-device bundles instead — a phone's chip, GPU, and
screen are fixed together in real life, so `generate_profiles.py` and the
GUI's fingerprint editor pick a complete device (e.g. "Pixel 8 Pro" or
"iPhone 15 Pro") rather than mixing mobile parts that would never
co-occur on a real phone.

**Important honesty note on iOS**: real Chrome on iPhone/iPad is a WebKit
wrapper, not Chromium (Apple requires every iOS browser to use WebKit
under the hood). Since this tool can only launch real Chromium, an iOS
profile is claiming a UA that inherently contradicts the engine actually
running underneath it — a structural mismatch that no amount of tuning
fixes, unlike every other platform here (Windows, macOS, and Android are
all genuinely Chromium, so those are structurally sound spoofs). iOS is
included since it was asked for, and the GUI flags it with a visible
warning when selected, but it's meaningfully weaker than the others.

The fingerprint editor (⚙ per profile) reflects this: pick Platform, and if
it's Android/iOS the separate GPU dropdown disappears — "Hardware/screen"
becomes "Device" and lists real phone/tablet models instead, each one a
complete atomic bundle.

## Cloud auto-sync on every change

Profiles now auto-push to the cloud after generate, rename, proxy edits
(single or bulk), and fingerprint edits — if you're signed in. This was a
real bug fix: Push was previously manual-only, so anything generated but
not explicitly pushed before closing the app was invisible next session,
especially when working from a fresh extracted folder each time. Pull is
still manual (you choose when to overwrite local with cloud state), but
nothing you create locally should silently vanish anymore as long as
you're signed in when you create it.

## Team Management

One migration to run once, then it's all in the GUI.

**Setup**: Supabase Dashboard → SQL Editor → New query → paste
`supabase/team_management.sql` → Run. This is additive on top of
`schema.sql` (which you should have already run) — broadens roles, adds a
member directory, and adds an invite system.

**Roles**: owner (created your org, can't be removed), admin (manage
members + profiles), staff (use profiles only, can't manage members).

**Using it**: sidebar → "Members & Invites" (only visible once signed in).
- **Members list**: shows everyone in your org. Owners/admins can change a
  member's role or remove them (not themselves, not the owner).
- **Create invite**: owners/admins pick a role and generate a one-time
  code to share with a teammate.
- **Join a team**: paste a code to join — this replaces your current
  organization with theirs (push/back up anything you want to keep
  separately before joining, since it's a genuine re-parenting, not an
  addition).

Email lookups for the member list go through a small `user_directory`
table populated by the signup trigger, scoped by Row Level Security so you
can only ever see emails of people who share an org with you — not a
general user lookup.

## Extension Management (GUI)

Sidebar → "Extension Management" replaces manually copying folders into
`extensions/` — same underlying mechanism (every extension there loads
into every profile automatically, on every launch, including profiles
that don't exist yet), just with a proper interface:

- **Add from folder**: picks an already-unpacked extension (manifest.json
  at the root, or one level inside — handles the common "Load unpacked"
  or unzipped-.crx shape automatically).
- **Add from .zip**: extracts and installs the same way.
- **No remove button, by design** — once added from inside the app, an
  extension stays. (Someone could still delete the folder by hand outside
  the app — no software can prevent direct filesystem access — but the
  app itself never offers that action.)

Chrome Web Store links aren't supported directly — there's no scraping or
downloading from the store built in, you need the extension already
downloaded/exported as a folder or .zip first.

## Chrome Web Store extension installs + removal lock

**Add from Chrome Web Store**: paste a full Web Store URL or just the
32-letter extension ID into the Extension Management modal. This downloads
directly from Google's own extension update endpoint (the same one Chrome
itself uses to fetch/update extensions) — not a scrape of the store's web
page — then unpacks and installs it the same way as the folder/.zip paths.

**Removal lock**: extensions still can't be removed by default. Setting an
unlock date/time in the modal is the one way to change that — a "Remove"
button only appears next to each extension once that moment has actually
passed (checked fresh every time you open the modal, not just once when
you set it).

## Automation API — full open → task → close loop

`examples/automation_example.py` now demonstrates the complete cycle:
request a launch, connect via CDP, run your automation, then explicitly
tell the API server to close the profile when done — suited to unattended/
scheduled runs across many profiles, not just one-off manual launches.

## Live enforcement of required extensions

Required extensions were already guaranteed to reload fresh on every *new*
launch (the launch flags force this every time, regardless of what
happened last session). The remaining gap — someone disabling or removing
an extension via `chrome://extensions` **while a profile is already
open** — is now covered too: a background check runs every few seconds
for the life of the session, and if any required extension's background
process disappears, the profile closes immediately. Reopening it reloads
every extension fresh, same as always — this only affects live tampering
during an already-open session, not anything about the extension staying
gone permanently, since it can't.

## Branding robustness fix + an honest limit

The tab title/favicon locking got hardened: it now runs as an init script
(before any page script, on every navigation) that locks `document.title`
via a property override, instead of setting it reactively after the page
loads. The old approach could lose a race if a page changed its own title
later — this can't be overridden by page scripts at all now.

**What this can't fix**: the actual taskbar icon graphic (the Chrome logo
itself) and anything Windows displays from the Chromium binary's own
embedded identity ("Chrome for Testing") are outside what our code can
change — same category of limit as "can Chrome's own color be changed"
from the very start of this project. That requires an actual custom-
compiled Chromium build, which was ruled out from day one as unrealistic
for a solo build. What we do control — the browser window's own title bar
text and tab favicon — should now be locked in reliably.

## Authenticated proxies now route through a local relay

Fixes the 407 "Proxy Authentication Required" error that could occur even
with correct proxy credentials. Root cause: Playwright's automatic proxy
authentication handling has a known limitation with `launch_persistent_context()`
(the mode this whole project uses, for extension support) — the exact same
proxy works fine in a normal browser or a non-persistent Playwright context.

The fix (`local_proxy_relay.py`): whenever a profile's proxy has a
username/password, launcher.py now starts a tiny local proxy on
`127.0.0.1` that Chromium connects to with **no** authentication at all.
That local relay does the real authentication to your actual proxy
provider itself, injecting the `Proxy-Authorization` header before
relaying traffic through. Chromium never has to handle a proxy login
challenge, so the buggy code path never triggers. This is a standard,
well-established workaround for this exact class of problem.

Nothing changes in how you configure proxies — same fields, same UI. This
is purely internal to how `launcher.py` hands the proxy to Chromium.


## Opening and closing profiles (new)

On the main screen: type a NO. in **Open by NO.** (`14`, a range `3-8`, or a list `1,5,20-25`) and
press Enter. Every row shows **Launch** (or **Close** while open), the checkbox bar has
**Open selected / Close selected**, and **Close all** shuts everything. No limit on how many.

## Timed plan

**Browser Profile > Timed Plan.** Each row = Profile NO. + website + seconds (+ optional **Scroll down**).
- One profile, one site: row `14` / `example.com` / `30`.
- **Several sites for one profile:** use the SAME Profile NO. on more than one row, e.g. `14` / `a.com` / `20`,
  `14` / `b.com` / `30`, `14` / `c.com` / `15`. Profile 14 visits them in order in one window, then closes.
- **Scroll down:** the page glides to the bottom at an even pace over that row's time (plain scrolling only).
- **Actions (keyboard):** click **Actions** on a row, then **+ Add action**. Each action is "At N seconds" +
  either **press a key** (Down arrow, Page Down, Space, Enter, Tab, ... and how many times) or **type text**
  (one line, up to 300 characters). Seconds count from when the page finished loading, must be inside the row's
  time, and fire at exactly that second (same every run). Typing goes to whatever box is focused on the page.
  No mouse movement or clicking is done.
- Choose **One after another** or **All at the same time**, then **Run plan**. The clock for each page starts
  once it has loaded; the profile closes (session saved as normal) after its last page. **Stop** closes everything.
- **Paste a script** (fast for many profiles): click **Paste a script**, paste one line per step as
  `profiles | website | seconds | options`, then **Fill the table** or **Fill and run**. Options are separated
  by `;`: `scroll`, `at 10 press Down x3`, `at 30 type hello`. Lines starting with `#` are ignored. Example:
  ```
  1-20 | instagram.com | 60 | scroll
  1-20 | facebook.com | 45 | scroll; at 10 press Down x3; at 30 type hello
  21 | google.com | 30
  ```
- A NO. range (`3-5`) in a row sends all of them to that site for that time. No limit on profiles; up to 20 sites each.

## Built-in API (optional, for scripts)

Only needed if you want your own scripts to control profiles. **System > API** shows the port
(53200), token and a ready-made example. Profiles are addressed by the same NO., a range, or a
name. `profile-open` (optional `"url": "https://..."` to choose the start page) returns `data.ws` for Playwright / patchright / Puppeteer / Selenium 4 (CDP).
Endpoints: `profile-open`, `profile-open-batch`, `profile-opened-list`, `profile-close`,
`profile-close-in-batches`, `profile-close-all`, `profile-list`, `profile-update-proxy`,
`proxy-bulk-assign`. Needs `Authorization: Bearer <token>`; only this computer can connect;
requests from web pages are refused.

## Bulk assign proxies

A number at the start of a line is the profile's **NO.** (row number in the table):
`14,host:port:user:pass`, a range `14-16,host:port:user:pass`, or by file name
`profile_014,...` / `profile_014_windows_desktop,...`. Lines that match nothing are skipped and
listed instead of being saved wrong.

## Icon

`assets/icon.ico` is the app/taskbar icon. Replace it with your own multi-size .ico and
rebuild with build_exe.bat. (`assets/make_icon.py` regenerates the default one.)

## Tests

`python tests/test_bulk_proxy.py`, `python tests/test_app_api.py`, `python tests/test_gui_open_close.py`, `python tests/test_plan_runner.py`, `python tests/test_plan_pages.py`

## Browser engine and start page

- **Own Chromium (no "Chrome for Testing" bar / Test icon):** on first run Trickster also downloads a plain
  Chromium build into `browsers/trickster-chromium/` (Windows only). Profiles use it automatically. If it
  isn't there or fails to start, profiles fall back to the standard browser, so nothing breaks.
  Look for "Using Trickster's own Chromium" in `trickster.log`.
- **Start page per profile:** the gear button on a profile has a **Start page** box (e.g. `ads.google.com`).
  Empty = Google. Timed plans and the API's `"url"` still override it for that launch.

## One-click build on your own PC

Install Python 3.12 (tick "Add python.exe to PATH"), then double-click **Build Trickster.bat** in this folder.
It installs what's needed, builds the app and puts **Trickster.exe** in your Downloads folder.
