// Popup: shows whether the extension is talking to the AppBlocker app and what
// it's currently enforcing, so clicking the toolbar icon explains itself.
const BASE = 'http://127.0.0.1:47113';

function $(id) { return document.getElementById(id); }
function setV(id, text, on) {
  const el = $(id); el.textContent = text;
  el.classList.remove('on', 'off');
  if (on === true) el.classList.add('on'); else if (on === false) el.classList.add('off');
}

async function detectBrowser() {
  let id = 'Chrome';
  try {
    const ua = (navigator && navigator.userAgent) || '';
    if (/Firefox\//i.test(ua)) id = 'Firefox';
    else if (/Edg\//i.test(ua)) id = 'Edge';
    else if (/OPR\//i.test(ua) || /\bOpera\b/i.test(ua)) id = 'Opera';
    else if (/Vivaldi/i.test(ua)) id = 'Vivaldi';
    else if (navigator && navigator.brave && typeof navigator.brave.isBrave === 'function') {
      try { if (await navigator.brave.isBrave()) id = 'Brave'; } catch (e) {}
    }
  } catch (e) {}
  return id;
}

async function load() {
  $('browser').textContent = await detectBrowser();

  let cfg = null, live = false;
  try {
    const r = await fetch(BASE + '/config', { cache: 'no-store' });
    cfg = await r.json();
    live = true;
  } catch (e) {
    // App closed: fall back to the last config the background cached.
    try {
      const api = (typeof browser !== 'undefined') ? browser : chrome;
      const c = await api.storage.local.get('CONFIG');
      if (c && c.CONFIG) cfg = c.CONFIG;
    } catch (e2) {}
  }

  if (live) {
    $('dot').style.background = '#36c17a';
    $('stateText').textContent = 'Connected and enforcing';
  } else {
    $('dot').style.background = '#e5a53b';
    $('stateText').textContent = 'AppBlocker app not running';
  }

  cfg = cfg || {};
  const nBlocked = (cfg.blockDomains || []).length;
  const webOn = !!cfg.webFilterEnabled;
  const adultOn = !!cfg.adultEnabled;

  setV('blocked', nBlocked ? (nBlocked + ' site' + (nBlocked === 1 ? '' : 's')) : 'None', nBlocked > 0 ? true : false);
  setV('weblist', webOn ? 'On' : 'Off', webOn);
  setV('adult', adultOn ? 'On' : 'Off', adultOn);

  $('note').textContent = live
    ? 'This browser is protected. Removing this extension will close the browser until it is reinstalled.'
    : 'Showing the last known rules. Blocking stays on until the AppBlocker app is reopened.';
}

load();
