"""
Opens multiple profiles in sequence, each on its own URL for its own
duration — edit the TASKS list below to change what runs.

HOW TO USE:
1. Make sure the profile_id values in TASKS match real files in profiles/
   (without ".json").
2. Run this file directly — in VS Code, press F5 (or Run > Run Without
   Debugging), or from a terminal: python examples/simple_automation.py

NOTE on reading the real page title: page.title() will always return this
profile's branded label (e.g. "profile_003_windows_desktop"), not the
site's actual title — that's intentional (see build_branding_script in
launcher.py, which locks document.title for anti-detect/taskbar-identity
reasons). To read the SITE's real title instead, use:
    page.eval_on_selector("title", "el => el.textContent")
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # so "import launcher" works from here

from patchright.sync_api import sync_playwright
import launcher

# Map each profile to its URL and how long to keep it open (seconds)
TASKS = [
    {"profile_id": "profile_003_windows_desktop", "url": "https://youtube.com", "duration": 20},
    {"profile_id": "profile_004_windows_desktop", "url": "https://stan.com",    "duration": 10},
]


def run_task(p, task):
    profile_path = Path(__file__).parent.parent / "profiles" / f"{task['profile_id']}.json"
    if not profile_path.exists():
        print(f"[SKIP] No such profile: {task['profile_id']}")
        return

    profile = launcher.load_profile(str(profile_path))

    print(f"Opening {profile_path.stem} -> {task['url']} for {task['duration']}s...")
    context, page = launcher.build_context(p, profile, headless=False)
    launcher.navigate(page, profile)

    # --- Your automation goes here ---
    page.goto(task["url"])
    real_title = page.eval_on_selector("title", "el => el.textContent") if page.query_selector("title") else ""
    print("Page title:", real_title)

    # Keep it open for the requested duration
    time.sleep(task["duration"])
    # ----------------------------------

    print(f"Done with {profile_path.stem} — closing.")
    context.close()


def main():
    with sync_playwright() as p:
        for task in TASKS:
            run_task(p, task)
    print("All tasks complete.")


if __name__ == "__main__":
    main()
