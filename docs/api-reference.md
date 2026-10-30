# Trickster local API vs ixBrowser local API

Trickster listens on `http://127.0.0.1:53200/api/v2/` (the same address and style as ixBrowser).
Every call is a POST with a JSON body and a token from the app's API panel
(`Authorization: Bearer <token>`). A profile can be given by NO. (`14`), a range (`3-8`), or its name.
`trickster_client.py` wraps all of it in the same style as ixBrowser's Python client.

| ixBrowser action | Trickster | Notes |
|---|---|---|
| profile-list | yes | filters: name, group, page, limit |
| profile-opened-list | yes | |
| native-client-profile-opened-list | yes | profiles opened with the app's Launch button |
| profile-open | yes | returns `debugging_address` and `ws` for Playwright / Selenium; optional `url`, `headless` |
| profile-open-with-random-fingerprint | yes | new fingerprint, same name / group / proxy |
| profile-opened-list-arrange-tile | yes | Windows; optional `columns` |
| profile-close / profile-close-in-batches | yes | |
| profile-open-state-reset | yes | |
| profile-create | yes | `count`, `group`, `url` |
| profile-copy | yes | new name and canvas seed, same device settings |
| profile-update | yes | group, start_url, locale, timezone_id, geolocation, proxy |
| profile-delete / empty-recycle-bin | yes | delete goes to a recycle bin first |
| profile-random-fingerprint-configuration | yes | |
| profile-update-groups-in-batches | yes | group is a name |
| profile-get-cookies / profile-update-cookies | yes | the profile must be open |
| profile-clear-cache (+ keep-extensions) / -and-cookies / -saved-user-password | yes | the profile must be closed |
| group-list / create / update / delete | yes | a group exists once a profile is in it |
| profile-update-proxy-for-custom-proxy | yes (`profile-update-proxy`) | |
| proxy-list / create / update / delete, proxy-tag-*, tag-* | not yet | proxies are assigned per profile or in bulk (`proxy-bulk-assign`) |
| traffic-package / purchased / api-extraction proxy modes | n/a | ixBrowser's own proxy shop |
| gateway-list / gateway-switch | n/a | ixBrowser cloud gateway |
| profile-transfer-* | n/a | Trickster syncs profiles and logins through your cloud account |

Only in Trickster: `proxy-bulk-assign`, `profile-close-all`, `profile-open-batch`, the Timed Plan
(visit pages, scroll, press keys, type text) and the cloud worker queue.

## Example
```python
from trickster_client import TricksterClient
from playwright.sync_api import sync_playwright

with TricksterClient(token="...") as c, sync_playwright() as p:
    info = c.open_profile(14, url="https://example.com")
    browser = p.chromium.connect_over_cdp("http://" + info["debugging_address"])
    page = browser.contexts[0].pages[0]
    print(page.title())
    c.close_profile(14)
```
