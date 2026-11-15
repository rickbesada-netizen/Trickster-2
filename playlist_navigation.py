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
    ".player-controls-middle-core-buttons button[aria-label*='Next']",
    "button[class*='next-button']",
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



# Mobile player controls are often hidden while playlist entries stay visible.
# Match the current watch URL to a row in the actual playlist panel, and
# choose its immediately following row, not a recommendation.
PLAYLIST_NEXT_JS = r"""
() => {
  const previous = document.querySelector('[data-trickster-next-target="1"]');
  if (previous) previous.removeAttribute('data-trickster-next-target');
  const current = new URL(location.href);
  const playlistId = current.searchParams.get('list');
  const videoId = current.searchParams.get('v');
  if (!playlistId || !videoId) return {found: false, why: 'not a playlist video'};
  const roots = [...document.querySelectorAll(
    'ytm-playlist-panel-renderer, ytm-playlist-video-list-renderer, ' +
    'ytd-playlist-panel-renderer, ytm-playlist-panel, ' +
    '[class*="playlist-panel"], [id*="playlist-panel"]'
  )];
  let best = null;
  for (const root of roots) {
    const entries = [...root.querySelectorAll('a[href]')].filter(a => {
      try {
        const u = new URL(a.href, location.href);
        return (u.pathname.endsWith('/watch') &&
                u.searchParams.get('list') === playlistId &&
                u.searchParams.has('v'));
      } catch (_) { return false; }
    });
    if (!entries.length) continue;
    const unique = [];
    const seen = new Set();
    for (const a of entries) {
      const v = new URL(a.href, location.href).searchParams.get('v');
      if (!seen.has(v)) { unique.push(a); seen.add(v); }
    }
    const at = unique.findIndex(a =>
      new URL(a.href, location.href).searchParams.get('v') === videoId);
    if (at < 0 || at + 1 >= unique.length) continue;
    if (!best || unique.length > best.count) {
      best = {element: unique[at + 1], count: unique.length};
    }
  }
  if (!best) return {found: false, why: 'next playlist link not in current panel'};
  best.element.setAttribute('data-trickster-next-target', '1');
  return {found: true, count: best.count};
}
"""


def find_playlist_link(page):
    """Return the next visible playlist entry; no URL synthesis or direct goto."""
    try:
        outcome = page.evaluate(PLAYLIST_NEXT_JS)
        if outcome and outcome.get("found"):
            target = page.locator('[data-trickster-next-target="1"]').first
            if target.is_visible(timeout=500) and target.is_enabled(timeout=500):
                return target, "next item in playlist panel"
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
        target, source = find_playlist_link(page)
    if target is None:
        # Hover may reveal controls on Chromium even with a mobile fingerprint.
        try:
            page.locator("video").first.hover(timeout=900)
            target, source = find_next(page)
        except Exception:
            pass
    if target is None:
        return False, ("Playlist next: no usable Next control or next playlist row "
                       "found. This mobile layout may need a site-specific selector.")
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
