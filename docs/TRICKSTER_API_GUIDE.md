# Trickster Local API - Complete Guide (for people and for AI assistants)

Version: matches Trickster Build 21 and later. Base URL, port and token are shown in Trickster under **API** in the left menu.

---
## 0. If you are an AI assistant reading this file

The user has given you this file so you can write scripts that control their Trickster antidetect browser. Follow these rules:

1. Only use the endpoints listed in section 6. Do not invent endpoints or parameters. If something is not listed, say it is not available.
2. Every call is `POST` with a JSON body to `http://127.0.0.1:<PORT>/api/v2/<action>` with the header `Authorization: Bearer <TOKEN>`.
3. Ask the user for two things if you do not have them: the **port** (default 53200) and the **token** (copy from Trickster > API > Copy token). Never invent a token. Put the token in a variable at the top of the script, never hard-code it in several places.
4. A success has `error.code == 0`. Always check it. Any other code is a failure, and `error.message` explains why in plain English.
5. Default to the Python helper in section 4 (`TricksterClient`) or the raw `requests` pattern in section 3, and drive the opened browser with Playwright / patchright over CDP (section 7).
6. Always close profiles you opened (use `try/finally`). Open at most a few profiles at a time unless the user asks otherwise (section 9).
7. The user is usually not a programmer. Give complete, copy-paste scripts, say exactly where to save them and the exact command to run, and explain errors in plain words.
8. Never ask the user to post their token in a public place. Never send the token anywhere except `127.0.0.1`.
9. This API automates browsers the user owns, for the user's own accounts and their clients' accounts with permission. Do not write scripts for spam, fake engagement, evading platform bans on accounts the user does not control, or anything illegal.

---
## 1. What the API is

Trickster runs a small web server **inside the app** on the user's own computer. Scripts talk to it to open and close browser profiles, change profile settings, and then control the open browser (click, type, scroll, read pages) with a normal automation library.

- Nothing to install or start. It runs while Trickster is open and "Enable the API" is ticked (the default).
- Reachable only from the same computer (`127.0.0.1`). Not reachable from the internet or other computers.
- The style is the same as ixBrowser's local API, so ixBrowser scripts need little change.

Check it is alive: in Trickster open **API** and click **Test it now**. Do NOT open the link in a normal web browser to test: a browser cannot send the token, so it only shows an "API is running" page.

---
## 2. Identifying a profile

Every endpoint that needs a profile accepts `profile_id` (also accepted: `no`, `name`) with any of:

| You send | Meaning |
|---|---|
| `14` or `"14"` | the profile in row **NO. 14** of the Profile List table |
| `"3-8"` | NO. 3 to 8 (only for batch endpoints, see 6) |
| `"profile_014_windows_desktop"` | the exact profile name |
| `"profile_014"` | a unique partial name (fails with code 2007 if it matches several) |

Single-profile endpoints require exactly one match. Batch endpoints take a list, e.g. `["1-5", 14, "profile_020_ios_phone"]`.

NO. is the row number in the table, so it can shift if profiles are deleted. The name is stable.

---
## 3. Request and response format

**Request**
```
POST http://127.0.0.1:53200/api/v2/<action>
Authorization: Bearer <TOKEN>          (or header X-API-Key: <TOKEN>)
Content-Type: application/json
{ ...parameters... }                    (empty body {} is fine when there are no parameters)
```
`GET` also works for simple calls (parameters in the query string).

**Response (always this shape)**
```json
{ "error": { "code": 0, "message": "success" }, "data": { ... } }
```
On failure `data` is `null` and `error.code` is not 0.

**Minimal Python without any helper**
```python
import requests
PORT = 53200
TOKEN = "PASTE_TOKEN_HERE"
BASE = f"http://127.0.0.1:{PORT}/api/v2/"
HEAD = {"Authorization": "Bearer " + TOKEN}

def call(action, **body):
    r = requests.post(BASE + action, json=body, headers=HEAD, timeout=120).json()
    if r["error"]["code"] != 0:
        raise RuntimeError(f'{action}: {r["error"]["message"]} (code {r["error"]["code"]})')
    return r["data"]

print(call("ping"))
```

**Error codes**

| Code | Meaning | What to do |
|---|---|---|
| 0 | success | - |
| 401 (HTTP 401) | missing or wrong token | copy the token again from Trickster > API; if you pressed "New token" the old one stopped working |
| 403 (HTTP 403) | request came from a web page or a non-local host | call it from a script, not from a website |
| 404 | unknown endpoint | check the action name in section 6 |
| 1000 | bad request (missing or invalid parameter) | read `message` |
| 1009 | process not found | that profile is not open |
| 2007 | profile does not exist / name is ambiguous | check NO. or name; use `profile-list` |
| 2008 | timed out waiting for the browser (90 s) | try again; close other heavy apps |
| 2009 | profile is open without an automation port, or must be opened first | see 6 (`profile-open`, cookies) |
| 413 | body larger than 2 MB | send less |
| 500 | internal error | read `message`, tell the user |

---
## 4. Python helper: `trickster_client.py`

The repository and downloads include `trickster_client.py`, a wrapper using the same method names as ixBrowser's Python client. Put it in the same folder as your script.

```python
from trickster_client import TricksterClient

c = TricksterClient(port=53200, token="PASTE_TOKEN_HERE")
profiles = c.get_profile_list(limit=20)        # list of dicts, or None on failure
if profiles is None:
    print(c.code, c.message)                   # why it failed
```
Every method returns the data on success, or `None` on failure (then `c.code` and `c.message` hold the reason). Methods that return nothing give `True`.

| Method | Calls |
|---|---|
| `ping()` | ping |
| `get_profile_list(name, group, page, limit)` | profile-list |
| `get_opened_profile_list()` | profile-opened-list |
| `get_native_opened_profile_list()` | native-client-profile-opened-list |
| `open_profile(profile_id, url=None, headless=False)` | profile-open |
| `open_profile_with_random_fingerprint(profile_id, url=None)` | profile-open-with-random-fingerprint |
| `open_profiles_in_batches(profiles, headless=False)` | profile-open-batch |
| `close_profile(profile_id)` | profile-close |
| `close_profile_in_batches(profile_id)` | profile-close-in-batches |
| `close_all_profiles()` | profile-close-all |
| `reset_profile_open_state(profile_id)` | profile-open-state-reset |
| `arrange_tile_opened_profile(columns=None)` | profile-opened-list-arrange-tile |
| `create_profile(count=1, group=None, url=None)` | profile-create |
| `create_profile_by_copying(profile_id, count=1)` | profile-copy |
| `update_profile(profile_id, **fields)` | profile-update |
| `delete_profile(profile_id)` / `empty_recycle_bin()` | profile-delete / empty-recycle-bin |
| `random_profile_fingerprint(profile_id)` | profile-random-fingerprint-configuration |
| `update_profile_groups_in_batches(profile_id, group)` | profile-update-groups-in-batches |
| `get_profile_cookie(profile_id)` / `update_profile_cookie(profile_id, cookie)` | profile-get-cookies / profile-update-cookies |
| `clear_profile_cache(...)`, `clear_profile_cache_and_cookies(...)`, `clear_profile_cache_keep_extensions(...)`, `clear_profile_saved_user_password(...)` | the matching clear actions |
| `update_profile_to_custom_proxy_mode(profile_id, proxy)` | profile-update-proxy |
| `bulk_assign_proxies(text)` | proxy-bulk-assign |
| `get_group_list()`, `create_group(name)`, `update_group(group, name)`, `delete_group(group)` | group actions |

---
## 5. Quick start (a complete first script)

1. Install Python from python.org (tick "Add Python to PATH").
2. Open a terminal (Windows key, type `cmd`, Enter) and run: `pip install patchright requests`
3. Save the script below as `test.py` on the Desktop (Save as type: All files).
4. In the terminal: `cd Desktop` then `python test.py`.

```python
import requests
from patchright.sync_api import sync_playwright

PORT = 53200
TOKEN = "PASTE_TOKEN_HERE"          # Trickster > API > Copy token
PROFILE = 14                        # a NO. from the Profile List table

BASE = f"http://127.0.0.1:{PORT}/api/v2/"
HEAD = {"Authorization": "Bearer " + TOKEN}

def call(action, **body):
    r = requests.post(BASE + action, json=body, headers=HEAD, timeout=120).json()
    if r["error"]["code"] != 0:
        raise RuntimeError(f'{action}: {r["error"]["message"]}')
    return r["data"]

info = call("profile-open", profile_id=PROFILE, url="https://example.com")
try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(info["ws"])
        page = browser.contexts[0].pages[0]
        print("Page title:", page.title())
finally:
    call("profile-close", profile_id=PROFILE)
```

---
## 6. Every endpoint

All are `POST /api/v2/<action>`. "Needs closed" means the profile must not be open.

### ping
No parameters. Returns `{"app":"Trickster","profiles":<count>,"open":<open count>}`. Use it to check the connection.

### profile-list
Parameters (all optional): `name` (substring of the profile name), `group` (exact group name), `page` (default 1), `limit` (default 50, max 1000).
Returns `{"list":[...],"total":N,"page":1,"limit":50}`. Each item:
`no`, `profile_id`, `name`, `file`, `group` (or null), `os` ("Windows"/"macOS"), `locale`, `timezone`, `proxy_configured` (true/false), `is_open` (true/false), `debugging_port` (number or null).

### profile-open
Parameters: `profile_id` (one profile, required), `url` (page to load first), `headless` (default false), `check` (default false).
Returns `{"profile_id","no","debugging_address":"127.0.0.1:<port>","debugging_port","ws":"ws://127.0.0.1:<port>/devtools/browser/<id>"}`.
Waits up to 90 s for the browser to start (error 2008 if not). If the profile is already open through the API it returns the existing connection. If it was opened with the app's own **Launch** button it has no automation port: error 2009; close that window first.
Use `ws` with Playwright/patchright `connect_over_cdp`, or `debugging_address` with Selenium (section 7).

### profile-open-batch (alias profile-open-in-batches)
Parameters: `profiles` (list, e.g. `["1-5", 14]`; also accepts `profile_id` or `no`), `headless`.
Returns `{"results":[{ok, profile_id, ws, ...} or {ok:false, code, message}],"opened":N,"failed":N}`. Opens one after another.

### profile-opened-list
Returns `{"list":[{profile_id,no,port,ws,source,...}]}` of every profile open right now.

### native-client-profile-opened-list
Same, but only profiles opened by the app's Launch button.

### profile-close
Parameter: `profile_id`. Closes it and saves its logins. Error 1009 if it was not open. Returns `data: null`.

### profile-close-in-batches
Parameter: `profile_id` (list or range). Returns `{"closed":[...],"not_found":[...],"failed":[...]}`.

### profile-close-all
No parameters. Returns `{"closed":[...],"failed":[]}`.

### profile-open-state-reset
Parameter: `profile_id`. Use when a profile is stuck as "open" after a crash. Returns true.

### profile-opened-list-arrange-tile
Windows only. Optional `columns`. Tiles every open browser window across the screen. Returns `{"arranged":N,"columns":N}`.

### profile-open-with-random-fingerprint
Needs closed. Same parameters as profile-open. Gives the profile a new random fingerprint (keeps its name, group, proxy, start page and logins), opens it, and returns the open data plus `fingerprint`.

### profile-random-fingerprint-configuration
Needs closed. Parameter: `profile_id`. New random fingerprint only (no opening). Returns `{profile_id,user_agent,platform,viewport,timezone,locale}`.

### profile-create
Parameters: `count` (1 to 5000, default 1), `group`, `url` (start page). New profiles get the next free numbers. Returns `{"created":[names],"count":N}`.

### profile-copy
Parameters: `profile_id`, `count` (1 to 500). Same device settings, new name and new canvas seed, no saved logins. Returns `{"created":[...],"count":N}`.

### profile-update
Parameter `profile_id` plus any of: `group`, `start_url` (or `url`), `locale`, `timezone_id`, `geolocation`, `proxy`. An empty string removes a field. `proxy` is a string in the formats in section 8 or an object `{"server","username","password"}`. Returns `{"profile_id","updated":[fields]}`. Error 1000 if nothing valid was sent.

### profile-delete
Needs closed. Parameter: `profile_id` (list ok). Moves to a recycle bin (recoverable by moving the file back). Returns `{"deleted":[...],"note":...}`.

### empty-recycle-bin
No parameters. Permanently deletes recycled profiles and their data. Returns `{"removed":N}`. Not undoable.

### group-list
Returns `{"list":[{"name","count"}],"total":N}`. A group exists only while at least one profile is in it.

### group-create
Parameter `name`. Informational: a group appears once a profile is added with profile-update-groups-in-batches.

### group-update
Parameters: `group` (current name), `name` (new name). Returns `{"renamed":N}`.

### group-delete
Parameter `group` (or `name`). Ungroups its profiles (profiles are not deleted). Returns `{"ungrouped":N}`.

### profile-update-groups-in-batches
Parameters: `profile_id` (list or range), `group` (name; empty string removes the group). Returns `{"updated":N,"group":name|null}`.

### profile-update-proxy
Parameters: `profile_id`, `proxy` (string or object, section 8). Returns `{"profile_id","server"}`. Error 1000 if the proxy text is not recognised.

### proxy-bulk-assign
Parameter `text` (or `lines`, a list): one line per profile, `NO.,proxy` e.g. `14,host:port:user:pass`. Returns `{"message","assigned":[...],"skipped":[...]}`.

### profile-get-cookies
The profile must be open (else 2009). Returns `{"cookies":[...]}` (Playwright cookie format).

### profile-update-cookies
The profile must be open. Parameter `cookie` (JSON string or list of cookie objects; `""` clears all cookies). Returns `{"added":N}` or `{"cleared":true}`.

### profile-clear-cache / profile-clear-cache-keep-extensions
Needs closed. Clears cache folders only (logins stay).

### profile-clear-cache-and-cookies
Needs closed. Clears cache and cookies (the profile is logged out of sites).

### profile-clear-saved-user-password
Needs closed. Removes browser-saved passwords.

### Not available
Proxy library endpoints (proxy-list, proxy-create, proxy-update, proxy-delete), tag endpoints, ixBrowser gateway / traffic-package / profile-transfer endpoints. Proxies are assigned per profile (profile-update-proxy) or in bulk (proxy-bulk-assign). Trickster's Timed Plan (visit pages, scroll, press keys, type) and cloud worker are used from the app, not this API.

---
## 7. Controlling the opened browser

**Playwright / patchright (recommended).** `profile-open` returns `ws`:
```python
browser = p.chromium.connect_over_cdp(info["ws"])
context = browser.contexts[0]          # the profile's own context: keep using it so logins and fingerprint stay
page = context.pages[0] if context.pages else context.new_page()
page.goto("https://example.com")
page.click("text=Sign in")
page.fill("input[name=email]", "name@example.com")
```
Use `browser.contexts[0]`. Do not create a new context: it would not have the profile's logins or fingerprint.
Install: `pip install patchright` (a Playwright that is harder to detect) or `pip install playwright`. You do not need to run `playwright install`; you are attaching to Trickster's own browser.

**Selenium 4.**
```python
from selenium import webdriver
opts = webdriver.ChromeOptions()
opts.debugger_address = info["debugging_address"]      # "127.0.0.1:<port>"
driver = webdriver.Chrome(options=opts)                # needs a chromedriver matching Trickster's Chromium version
```

**Puppeteer (Node).**
```js
const browser = await puppeteer.connect({ browserWSEndpoint: info.ws });
const page = (await browser.pages())[0];
```

**Raw DevTools protocol:** open `http://<debugging_address>/json/version` for the websocket URL.

---
## 8. Proxy formats accepted

`host:port` , `host:port:user:pass` , `user:pass@host:port` , `http://host:port,user,pass` , or an object `{"server":"http://host:port","username":"u","password":"p"}`.
SOCKS is accepted as `socks5://host:port`. Send the proxy with `profile-update-proxy`, `profile-update` (`proxy` field) or `proxy-bulk-assign`.

---
## 9. Good practice and limits

- **Open a few at a time.** Each profile is a full Chromium. A typical PC handles 5 to 20 open at once; more needs more RAM and CPU. Open, work, close, repeat.
- **Always close** in a `finally:` block so logins are saved and memory is freed. If a script crashes, call `profile-close-all` or `profile-open-state-reset`.
- **Videos play by themselves** (YouTube, Shorts, TikTok) in profiles opened by Trickster; no click is needed. To pause or skip, press `k` (play/pause) or use the page's own buttons.
- **Pace actions** like a person: random 1 to 5 second pauses, not instant bursts. Platforms flag inhuman speed regardless of fingerprints.
- **One proxy per profile**, kept for that profile permanently. Do not share one proxy across many accounts.
- **Timeouts:** opening can take up to 90 s the first time. Use `timeout=120` on HTTP calls.
- **The app must be open** and the user signed in to Trickster. If the API is off, tick "Enable the API" in the panel.
- **Port clash** (for example ixBrowser uses 53200 too): change the port in Trickster > API > Port > Save port, and use the new port in scripts.
- **Token:** treat it like a password. "New token" invalidates the old one.
- **Only this computer** can call the API. To control Trickster on a different computer, run the script on that computer.

---
## 10. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ConnectionRefusedError` / "couldn't reach Trickster" | Trickster is not open, the API is off, or the port is different. Open Trickster, check API panel says "Running". |
| HTTP 401 / "Missing or wrong API token" | Token is wrong or was regenerated. Copy it again. |
| Browser page says "Trickster API is running" | That is correct. Browsers are not meant to use it; use a script. |
| `2009 ... already open from the app's Launch button` | Close the window opened by Launch, then open through the API. |
| `2008 Timed out` | First start can be slow; retry once. Close other heavy programs. |
| `2007 Profile does not exist` | Wrong NO. or name. Call profile-list. |
| `pip` is not recognised | Python is not on PATH. Reinstall Python and tick "Add Python to PATH". |
| Script works but logins are missing | The script made a new context. Use `browser.contexts[0]`. |

---
## 11. Copy-paste prompt for another AI

Give an AI assistant this file and then paste:

> I use Trickster (an antidetect browser). Using ONLY the attached API guide, write me a complete Python script that does the following: **[describe the task, which profile NO. or group, which website, what to do]**. My port is **53200** and my token is stored in a variable `TOKEN` that I will fill in. Open the profiles through the API, drive them with patchright over CDP using `browser.contexts[0]`, pace actions with random 1 to 5 second pauses, wrap everything in try/finally so profiles are always closed, and print simple progress messages. Tell me exactly where to save the file and which command to run. Ask me before assuming anything the guide does not cover.

---
## 12. Changelog
- Build 21: this guide; "Test it now" button; friendly page when the address is opened in a browser.
- Build 19-20: ixBrowser-style endpoints (profiles, groups, cookies, cache, tiles), Python client, panel Copy link and Copy token.
