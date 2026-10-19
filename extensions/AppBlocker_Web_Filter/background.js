// AppBlocker Web Filter - companion extension service worker.
//
// Talks to the AppBlocker app's localhost control server:
//   - GET  /config     -> { webFilterEnabled, allowedSites, adultEnabled }
//   - POST /heartbeat  -> lets the app know the extension is alive
// and enforces the website allow-list by redirecting any non-allowed top-level
// navigation to a bundled "blocked" page.
//
// If the app is closed, the last fetched config stays in effect (fail-safe:
// the allow-list keeps blocking). If the extension is removed/disabled, the
// heartbeats stop and the app closes the browser (then the force-install policy
// reinstalls it on next launch).
const BASE = 'http://127.0.0.1:47113';

let CONFIG = { webFilterEnabled: false, allowedSites: [], blockDomains: [], blockExceptions: [], adultEnabled: false };

const ALWAYS_ALLOW_HOSTS = ['localhost', '127.0.0.1', '::1'];

function hostOf(url) {
  try { return new URL(url).hostname.toLowerCase(); } catch { return ''; }
}

function cleanDom(dom) {
  return String(dom).trim().toLowerCase().replace(/^https?:\/\//, '').replace(/\/.*$/, '').replace(/:\d+$/, '');
}
function hostMatches(host, dom) {
  const d = cleanDom(dom);
  return d && (host === d || host.endsWith('.' + d));
}

function isAllowedHost(host) {
  if (!host) return true;
  if (ALWAYS_ALLOW_HOSTS.includes(host)) return true;
  return (CONFIG.allowedSites || []).some(dom => hostMatches(host, dom));
}

// Is this host on an active block list? (Works regardless of DNS / DoH.)
function isBlockListed(host) {
  return (CONFIG.blockDomains || []).some(dom => hostMatches(host, dom));
}

// Website exceptions: allow a specific page/channel/profile even though its
// site is blocked (e.g. block youtube.com but allow youtube.com/@SomeChannel).
// An exception is a host+path prefix; the URL is allowed if it starts with it.
function normKey(url) {
  try {
    const u = new URL(url);
    return (u.hostname.replace(/^www\./, '') + u.pathname).toLowerCase().replace(/\/+$/, '');
  } catch (e) { return ''; }
}
function cleanExc(ex) {
  return String(ex).trim().toLowerCase()
    .replace(/^[a-z]+:\/\//, '').replace(/^www\./, '').replace(/\/+$/, '');
}
function isExcepted(url) {
  const key = normKey(url);
  if (!key) return false;
  for (const ex of (CONFIG.blockExceptions || [])) {
    const e = cleanExc(ex);
    if (!e) continue;
    if (key === e || key.startsWith(e + '/') || key.startsWith(e + '?') || key.startsWith(e)) return true;
  }
  return false;
}

// Only http/https top-level pages are governed; extension/chrome/about pages pass.
function shouldBlock(url) {
  if (!/^https?:\/\//i.test(url)) return false;
  const host = hostOf(url);
  if (ALWAYS_ALLOW_HOSTS.includes(host)) return false;
  // 1) Block-list sites are blocked, UNLESS this exact page is an exception.
  if (isBlockListed(host)) return !isExcepted(url);
  // 2) Web allow-list: block everything not explicitly allowed.
  if (CONFIG.webFilterEnabled && !isAllowedHost(host)) return true;
  return false;
}

async function refreshConfig() {
  try {
    const r = await fetch(BASE + '/config', { cache: 'no-store' });
    CONFIG = await r.json();
    await chrome.storage.local.set({ CONFIG });
  } catch (e) {
    // App not reachable: keep enforcing the last known config.
    try { const c = await chrome.storage.local.get('CONFIG'); if (c.CONFIG) CONFIG = c.CONFIG; } catch {}
  }
}

// Identify which browser we're in, so the app tracks liveness PER browser.
// (Removing the extension from Brave must stop only Brave's heartbeats, even if
// Chrome still has it.) Brave hides itself from the UA, so use navigator.brave.
let BROWSER_ID = null;
async function detectBrowser() {
  if (BROWSER_ID) return BROWSER_ID;
  let id = 'chrome';
  try {
    const ua = (navigator && navigator.userAgent) || '';
    if (/Firefox\//i.test(ua)) id = 'firefox';
    else if (/Edg\//i.test(ua)) id = 'edge';
    else if (/OPR\//i.test(ua) || /\bOpera\b/i.test(ua)) id = 'opera';
    else if (/Vivaldi/i.test(ua)) id = 'vivaldi';
    else if (navigator && navigator.brave && typeof navigator.brave.isBrave === 'function') {
      try { if (await navigator.brave.isBrave()) id = 'brave'; } catch (e) {}
    }
  } catch (e) {}
  BROWSER_ID = id;
  return id;
}

async function heartbeat() {
  try {
    const b = await detectBrowser();
    await fetch(BASE + '/heartbeat?b=' + encodeURIComponent(b), { method: 'POST', cache: 'no-store' });
  } catch (e) {}
}

async function pulse() { await refreshConfig(); await heartbeat(); }

function blockedUrl(host) {
  return chrome.runtime.getURL('blocked.html') + '?host=' + encodeURIComponent(host || '');
}

// Enforce on navigation (main frame only).
chrome.webNavigation.onBeforeNavigate.addListener((d) => {
  if (d.frameId !== 0) return;
  if (shouldBlock(d.url)) {
    chrome.tabs.update(d.tabId, { url: blockedUrl(hostOf(d.url)) }).catch(() => {});
  }
  heartbeat(); // navigation = activity = liveness
});

// Catch client-side redirects / address-bar edits that don't fire onBeforeNavigate.
chrome.webNavigation.onCommitted.addListener((d) => {
  if (d.frameId !== 0) return;
  if (shouldBlock(d.url)) {
    chrome.tabs.update(d.tabId, { url: blockedUrl(hostOf(d.url)) }).catch(() => {});
  }
});

// Keep alive / regular heartbeat even when idle (alarms wake the worker).
chrome.alarms.create('pulse', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === 'pulse') pulse(); });

chrome.runtime.onStartup.addListener(() => pulse());
chrome.runtime.onInstalled.addListener(() => pulse());

// Beat on ANY browser activity, so a browser the user is actually using is never
// mistaken for one without the extension and closed. (MV3 service workers sleep
// when idle; these events wake them and prove liveness the moment you do anything.)
try {
  chrome.tabs.onActivated.addListener(() => heartbeat());
  chrome.tabs.onUpdated.addListener((id, info) => { if (info.status) heartbeat(); });
  chrome.webNavigation.onCompleted.addListener((d) => { if (d.frameId === 0) heartbeat(); });
  chrome.webNavigation.onHistoryStateUpdated.addListener((d) => { if (d.frameId === 0) heartbeat(); });
  if (chrome.windows && chrome.windows.onFocusChanged) {
    chrome.windows.onFocusChanged.addListener(() => heartbeat());
  }
} catch (e) {}

// Firefox (persistent background) keeps this running; in Chrome MV3 the worker
// may sleep, but the alarm above covers it.
try { setInterval(pulse, 15000); } catch (e) {}

// Initial load (also runs when the service worker wakes).
pulse();
