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
  const marker = 'data-trickster-next-target';
  const previous = document.querySelector('[' + marker + '="1"]');
  if (previous) previous.removeAttribute(marker);
  const url = new URL(location.href);
  const currentId = url.searchParams.get('v');
  const listId = url.searchParams.get('list');
  if (!currentId || !listId)
    return {found:false, why:'not a playlist watch URL'};
  const rowSelector = [
    'ytm-playlist-video-renderer', 'ytm-playlist-panel-video-renderer',
    'ytm-compact-playlist-video-renderer', 'ytm-compact-video-renderer',
    'ytm-playlist-panel-item', 'ytd-playlist-panel-video-renderer',
    '[class*="playlist-video-item"]'
  ].join(',');
  const rootSelector = [
    'ytm-playlist-panel-renderer', 'ytm-playlist-video-list-renderer',
    'ytm-playlist-renderer', 'ytm-playlist-panel',
    'ytd-playlist-panel-renderer', '[class*="playlist-panel"]',
    '[id*="playlist-panel"]', '[class*="playlist-video-list"]'
  ].join(',');
  // On newer mobile layouts the list rows may be under a list container
  // without a recognized "panel" ancestor.
  const roots = [...document.querySelectorAll(rootSelector)];
  for (const row of document.querySelectorAll(rowSelector)) {
    let parent = row.parentElement;
    while (parent && parent !== document.body) {
      if (parent.matches('ytm-playlist-video-list-renderer, ytm-playlist-renderer, ' +
                         'ytm-playlist-panel-renderer, [class*="playlist"]')) {
        if (!roots.includes(parent)) roots.push(parent);
        break;
      }
      parent = parent.parentElement;
    }
  }
  let reason = 'no playlist panel rows found';
  let observed = 0;
  for (const root of roots) {
    const rows = [...root.querySelectorAll(rowSelector)];
    // Only fall back to links when they live inside a recognized playlist
    // container; never choose items from generic recommendations.
    if (!rows.length) rows.push(...root.querySelectorAll('a[href*="/watch"]'));
    if (!rows.length) continue;
    observed = Math.max(observed, rows.length);
    const entries = rows.map(row => {
      const anchor = row.matches('a[href]') ? row :
        row.querySelector('a[href*="/watch"]');
      let vid = null;
      try {
        if (anchor) {
          const u = new URL(anchor.getAttribute('href'), location.href);
          const linkList = u.searchParams.get('list');
          if (!linkList || linkList === listId) vid = u.searchParams.get('v');
        }
      } catch (_) {}
      const selected = row.matches(
        '[selected], [aria-current="true"], [aria-selected="true"], ' +
        '[is-selected], [data-selected="true"], [class*="selected"], ' +
        '[class*="active"]'
      ) || !!row.querySelector(
        '[selected], [aria-current="true"], [aria-selected="true"], ' +
        '[is-selected], [data-selected="true"]'
      );
      const rowIndex = Number(row.getAttribute('data-index') || row.getAttribute('index') || 0);
      return {row, target:anchor || row, vid, selected, rowIndex};
    });
    let current = entries.findIndex(e => e.vid === currentId);
    if (current < 0) current = entries.findIndex(e => e.selected);
    let next = null;
    let method = '';
    if (current >= 0 && current + 1 < entries.length) {
      next = entries[current + 1];
      method = 'row after current video';
    } else if (current < 0) {
      // Some mobile playlist panels omit the current video from the displayed
      // row list. Only infer the first row when the header reliably says 1/N.
      const text = (root.innerText || '').slice(0, 500);
      const match = text.match(/(?:^|\s)(\d{1,6})\s*\/\s*(\d{1,6})(?:\s|$)/);
      const pos = match ? Number(match[1]) : 0;
      const total = match ? Number(match[2]) : 0;
      if (pos > 0 && pos < total) {
        next = entries.find(e => e.rowIndex === pos + 1) || null;
        if (next) {
          method = 'indexed playlist row';
        } else if (pos === 1 && entries[0].vid !== currentId &&
                   !entries[0].selected) {
          next = entries[0];
          method = 'first row after playlist position 1';
        }
      }
      if (!next) reason = 'no current row or unambiguous next playlist position';
    } else {
      reason = 'current video is last visible playlist row';
    }
    if (!next || next.vid === currentId) continue;
    next.target.setAttribute(marker, '1');
    return {found:true, method, rows:entries.length, roots:roots.length};
  }
  return {found:false, why:reason, rows:observed, roots:roots.length};
}
"""


def find_playlist_link(page):
    """Return the next visible playlist entry; no URL synthesis or direct goto."""
    try:
        outcome = page.evaluate(PLAYLIST_NEXT_JS)
        if outcome and outcome.get("found"):
            target = page.locator('[data-trickster-next-target="1"]').first
            if target.is_visible(timeout=800) and target.is_enabled(timeout=800):
                return target, "mobile playlist (" + outcome.get("method", "next row") + ")"
            return None, "playlist row found but not visible/enabled"
        if outcome:
            return None, ("playlist scan: " + str(outcome.get("why", "unknown")) +
                          f" (roots={outcome.get('roots', 0)}, rows={outcome.get('rows', 0)})")
    except Exception as exc:
        return None, "playlist DOM scan failed: " + str(exc)[:150]
    return None, "playlist scan unavailable"


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
    scan_diagnostic = ""
    if target is None:
        target, source = find_playlist_link(page)
        if target is None:
            scan_diagnostic = source or "playlist scan unavailable"
    if target is None:
        # Hover may reveal controls on Chromium even with a mobile fingerprint.
        try:
            page.locator("video").first.hover(timeout=900)
            target, source = find_next(page)
        except Exception:
            pass
    if target is None:
        return False, ("Playlist next: no usable Next control; " + scan_diagnostic)
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
