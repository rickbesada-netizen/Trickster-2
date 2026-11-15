"""Adaptive next-item navigation for timed browser tests.

Uses the active page layout rather than fingerprint labels. No direct URL
injection, arbitrary JS clicks or silent success claims.
"""
import re
import time
from urllib.parse import urlsplit, parse_qs

NEXT_NAME = re.compile(r"^(next|next video|next track|next song|skip to next)(?:\b.*)?$", re.I)
# Known desktop-player control + common accessible mobile controls.
# We deliberately do not guess unrelated playlist entries.
NEXT_SELECTORS = (
    "button.ytp-next-button",
    ".ytp-next-button",
    "button[aria-label='Next']",
    "button[aria-label='Next video']",
    "button[title='Next']",
    "[data-testid='next-button']",
    "[data-action='next']",
)


def media_identity(page):
    """Detect a different video even on sites with SPA navigation."""
    url = str(page.url)
    parsed = urlsplit(url)
    q = parse_qs(parsed.query)
    # For playlist navigation compare actual video IDs/index, not URL fragments.
    marker = (parsed.netloc, q.get("v", [""])[0], q.get("index", [""])[0])
    try:
        media = page.locator("video").first.evaluate(
            "(v) => v.currentSrc || v.src || ''", timeout=800)
    except Exception:
        media = ""
    return url, marker, media


def changed(before, after):
    old_url, old_marker, old_media = before
    new_url, new_marker, new_media = after
    if old_marker != new_marker and (old_marker[1] or old_marker[2] or new_marker[1] or new_marker[2]):
        return True
    if old_url != new_url:
        return True
    return bool(old_media and new_media and old_media != new_media)


def find_next(page):
    """Use accessibility first, then verified visible element candidates."""
    for role in ("button", "link"):
        try:
            target = page.get_by_role(role, name=NEXT_NAME).first
            if target.is_visible(timeout=400) and target.is_enabled(timeout=400):
                return target, "accessible " + role
        except Exception:
            pass
    for selector in NEXT_SELECTORS:
        try:
            target = page.locator(selector).first
            if target.is_visible(timeout=400) and target.is_enabled(timeout=400):
                return target, selector
        except Exception:
            pass
    return None, None


def video_ended(page):
    """Return None if there is no available video element."""
    try:
        return page.locator("video").first.evaluate(
            "(v) => ({ended: !!v.ended, ready: v.readyState > 0})",
            timeout=900)
    except Exception:
        return None


def advance(page, stop_event=None, confirmation_seconds=4):
    """Attempt one Next click and confirm a new item; return diagnostic text."""
    if stop_event is not None and stop_event.is_set():
        return False, "Playlist next: stopped"
    before = media_identity(page)
    target, source = find_next(page)
    if target is None:
        return False, "Playlist next: no visible enabled Next control found (mobile/desktop layout)"
    try:
        target.click(timeout=2500)
    except Exception as error:
        return False, "Playlist next: click failed on " + source + ": " + str(error)[:120]
    deadline = time.monotonic() + confirmation_seconds
    while time.monotonic() < deadline:
        if stop_event is not None and stop_event.is_set():
            return False, "Playlist next: stopped while checking navigation"
        try:
            if changed(before, media_identity(page)):
                return True, "Playlist next: confirmed item changed via " + source
        except Exception:
            pass
        time.sleep(0.2)
    return False, "Playlist next: clicked " + source + " but no item change was detected"
