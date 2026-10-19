"""
Example: open a profile via the automation API, drive it with your own
Playwright/patchright script over its CDP connection, then close it — the
full "open, do the task, close" loop for unattended automation, completely
separate from the GUI. Same shape as an ixBrowser bulk profile runner
(open by profile_id -> get a CDP endpoint -> connect -> automate -> close),
just pointed at this tool's API instead.

Before running this:
    1. Have at least one profile generated (via the GUI, or:
       python generate_profiles.py --count 1)
    2. In a separate terminal, start the API server and leave it running:
       python api_server.py

Then run this script:
    python examples/automation_example.py profile_001_windows_desktop
"""

import sys

import requests
from patchright.sync_api import sync_playwright

API_BASE = "http://localhost:53200"


def main():
    if len(sys.argv) < 2:
        print("Usage: python examples/automation_example.py <profile_id>")
        print("(profile_id is the filename without .json, e.g. profile_001_windows_desktop)")
        sys.exit(1)

    profile_id = sys.argv[1]

    print(f"Opening {profile_id}...")
    response = requests.post(f"{API_BASE}/api/v2/profile-open", json={"profile_id": profile_id})
    result = response.json()

    if result["error"]["code"] != 0:
        print(f"Open failed: {result['error']['message']}")
        sys.exit(1)

    ws = result["data"]["ws"]
    print(f"Open — connecting to {ws}")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ws)
        context = browser.contexts[0]
        page = context.pages[0]

        # --- Your automation goes here ---
        page.goto("https://example.com")
        title = page.title()
        print(f"Page title: {title}")
        page.reload()  # "refresh" — just a normal call over the same connection
        # ----------------------------------

        # connect_over_cdp() attaches to an existing browser rather than
        # owning its lifecycle, so browser.close() here would disconnect
        # this script but NOT actually close the profile's window — the
        # window is a separate OS process managed by api_server.py. To
        # actually close it, tell the API server to do so:

    print("Task done — closing the profile via the API...")
    close_response = requests.post(f"{API_BASE}/api/v2/profile-close", json={"profile_id": profile_id})
    close_result = close_response.json()
    print(close_result["error"]["message"])


if __name__ == "__main__":
    main()
