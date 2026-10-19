// Injected via page.add_init_script() (main page) and worker.evaluate() (workers).
// patchright already patches the CDP-detection leaks that puppeteer-extra-stealth
// misses. This script layers on per-profile canvas/audio noise and hardware
// property overrides so each profile has a consistent-but-unique fingerprint.
//
// __PROFILE__ is replaced by launcher.py with the actual profile JSON before injection.
//
// This script must run safely in BOTH a page context (window/document exist)
// and a worker context (no window/document, only self/navigator) — DOM-only
// sections are guarded with typeof checks so they no-op cleanly in a worker.

(() => {
  const profile = __PROFILE__;
  const globalScope = typeof window !== 'undefined' ? window : self;
  // Checking typeof HTMLCanvasElement too, not just typeof document — a
  // real service worker (e.g. YouTube's sw.js) turned out to define its
  // own "document"-like stub for compatibility reasons, which made
  // isPageContext compute true even inside the worker and let the
  // canvas-patching code below run somewhere HTMLCanvasElement genuinely
  // doesn't exist, throwing a ReferenceError that also appears to have
  // left that worker's CDP session in a bad state — context.close()
  // crashing the whole driver process right afterward is consistent
  // with that. Checking the actual API being touched, not just a proxy
  // signal for "are we in a page", is the more direct fix either way.
  const isPageContext = typeof document !== 'undefined' && typeof HTMLCanvasElement !== 'undefined';

  // NOTE: an earlier version of this file also patched
  // Function.prototype.toString globally to mask overridden functions as
  // "[native code]". That was reverted — tools like CreepJS specifically
  // test for exactly that pattern (often via a pristine toString reference
  // pulled from a hidden iframe's separate JS realm, which bypasses the
  // masking entirely and exposes the override's real source as an even
  // stronger tampering signal than leaving toString alone). Confirmed by
  // testing: stealth score went from 20% to 40% after adding it. Closing
  // this class of leak reliably requires engine-level patches, not
  // JS overrides — see the project skill notes for the fuller writeup.
  function nativeize(fn, name) {
    if (name) Object.defineProperty(fn, 'name', { value: name, configurable: true });
    return fn;
  }

  // Seeded pseudo-random generator so the same profile always produces the
  // same noise (consistent fingerprint across sessions for that profile).
  function mulberry32(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const rand = mulberry32(profile.canvas_seed);

  // --- Navigator property overrides ---
  // Applies in both page and worker contexts — WorkerNavigator has its own
  // prototype separate from Navigator, so this is what fixes the worker
  // thread deviceMemory/hardwareConcurrency leak from the last test.
  const navProps = {
    hardwareConcurrency: profile.hardware_concurrency,
    deviceMemory: profile.device_memory,
    platform: profile.platform,
    languages: [profile.locale, profile.locale.split('-')[0]],
  };
  const navProto = Object.getPrototypeOf(globalScope.navigator);
  for (const [key, value] of Object.entries(navProps)) {
    if (!(key in globalScope.navigator)) continue; // property doesn't exist on this context's navigator
    Object.defineProperty(navProto, key, {
      get: nativeize(() => value, 'get ' + key),
      configurable: true,
    });
  }

  // Everything below this line touches DOM/canvas/WebGL/audio APIs that only
  // exist in a page context, not a worker's global scope.
  if (!isPageContext) return;

  // --- Screen resolution spoofing ---
  // Desktop/laptop profiles no longer force Chromium's real window to the
  // profile's assigned resolution (launcher.py uses no_viewport + a real
  // maximized window instead, so the window always fits the actual
  // monitor). That means window.screen now reports this machine's real
  // resolution unless overridden here — so we override it to match the
  // profile's fingerprint instead, the same way a real device with that
  // screen would report it. Mobile/tablet profiles keep their real (small)
  // viewport as the actual window size, so this just keeps them consistent
  // too.
  if (profile.viewport && globalScope.screen) {
    const screenProps = {
      width: profile.viewport.width,
      height: profile.viewport.height,
      availWidth: profile.viewport.width,
      availHeight: profile.viewport.height,
      availLeft: 0,
      availTop: 0,
      colorDepth: 24,
      pixelDepth: 24,
    };
    const screenProto = Object.getPrototypeOf(globalScope.screen);
    for (const [key, value] of Object.entries(screenProps)) {
      if (!(key in globalScope.screen)) continue;
      try {
        Object.defineProperty(screenProto, key, {
          get: nativeize(() => value, 'get ' + key),
          configurable: true,
        });
      } catch (e) { /* non-configurable on this engine — skip */ }
    }
  }

  // --- Canvas noise ---
  const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = nativeize(function (...args) {
    const ctx = this.getContext('2d');
    if (ctx) {
      const imageData = ctx.getImageData(0, 0, this.width, this.height);
      for (let i = 0; i < imageData.data.length; i += 4) {
        const noise = Math.floor(rand() * 3) - 1; // -1, 0, or 1
        imageData.data[i] = Math.min(255, Math.max(0, imageData.data[i] + noise));
      }
      ctx.putImageData(imageData, 0, 0);
    }
    return origToDataURL.apply(this, args);
  }, 'toDataURL');

  const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
  CanvasRenderingContext2D.prototype.getImageData = nativeize(function (...args) {
    const imageData = origGetImageData.apply(this, args);
    for (let i = 0; i < imageData.data.length; i += 4) {
      const noise = Math.floor(rand() * 3) - 1;
      imageData.data[i] = Math.min(255, Math.max(0, imageData.data[i] + noise));
    }
    return imageData;
  }, 'getImageData');

  // --- WebGL vendor/renderer spoofing ---
  // WebGL1 and WebGL2 have separate prototypes in Chromium (WebGL2 does NOT
  // inherit getParameter from WebGL1) — sites commonly query WebGL2 directly,
  // so both must be patched or the override silently does nothing for one of them.
  function patchGetParameter(proto) {
    if (!proto) return;
    const original = proto.getParameter;
    proto.getParameter = nativeize(function (param) {
      if (param === 37445) return profile.webgl_vendor;   // UNMASKED_VENDOR_WEBGL
      if (param === 37446) return profile.webgl_renderer;  // UNMASKED_RENDERER_WEBGL
      return original.apply(this, arguments);
    }, 'getParameter');
  }
  patchGetParameter(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
  patchGetParameter(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);

  // --- AudioContext noise ---
  const origGetChannelData = AudioBuffer.prototype.getChannelData;
  AudioBuffer.prototype.getChannelData = nativeize(function (...args) {
    const data = origGetChannelData.apply(this, args);
    for (let i = 0; i < data.length; i += 100) {
      data[i] += (rand() - 0.5) * 0.0001;
    }
    return data;
  }, 'getChannelData');

  // --- WebRTC local IP leak prevention ---
  // Blocks host-candidate gathering so the real local/public IP never appears
  // in ICE candidates, which would otherwise expose the machine behind the proxy.
  if (window.RTCPeerConnection) {
    const OrigRTCPeerConnection = window.RTCPeerConnection;
    window.RTCPeerConnection = nativeize(function (...args) {
      if (args[0] && args[0].iceServers) {
        args[0].iceServers = [];
      }
      return new OrigRTCPeerConnection(...args);
    }, 'RTCPeerConnection');
    window.RTCPeerConnection.prototype = OrigRTCPeerConnection.prototype;
  }

  // --- Font whitelist enforcement (canvas-based detection only) ---
  // This closes canvas.measureText()-based font probing: any font not in
  // the profile's whitelist gets silently swapped to a whitelisted font
  // before rendering, so measured text metrics match a machine that only
  // has these fonts installed. It does NOT close DOM-based font probing
  // (hidden <span> elements compared by offsetWidth with different
  // font-family CSS, or document.fonts.load() font-loading checks) — those
  // go through the real layout/font-loading engine, not a JS API that can
  // be overridden. Fixing that requires controlling which fonts are
  // actually installed at the OS level.
  const fontWhitelist = new Set((profile.fonts || []).map((f) => f.toLowerCase()));
  const genericFamilies = new Set(['serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui']);

  function extractFamilies(fontStr) {
    const match = fontStr.match(/(?:\d+(?:\.\d+)?)(?:px|pt|em|rem|%)\s*(?:\/\s*[\d.]+\s*)?(.+)$/i);
    const familyPart = match ? match[1] : fontStr;
    return familyPart.split(',').map((f) => f.trim().replace(/^["']|["']$/g, '').toLowerCase());
  }

  const fontDesc = Object.getOwnPropertyDescriptor(CanvasRenderingContext2D.prototype, 'font');
  if (fontDesc && fontDesc.set) {
    Object.defineProperty(CanvasRenderingContext2D.prototype, 'font', {
      configurable: true,
      get: nativeize(function () {
        return fontDesc.get.call(this);
      }, 'get font'),
      set: nativeize(function (value) {
        const families = extractFamilies(value);
        const allowed = families.some((f) => fontWhitelist.has(f) || genericFamilies.has(f));
        if (!allowed && fontWhitelist.size > 0) {
          const fallback = profile.fonts[0];
          value = value.replace(families[0], fallback);
        }
        fontDesc.set.call(this, value);
      }, 'set font'),
    });
  }

  if (window.FontFaceSet && FontFaceSet.prototype.check) {
    const origCheck = FontFaceSet.prototype.check;
    FontFaceSet.prototype.check = nativeize(function (font, text) {
      const families = extractFamilies(font);
      const allowed = families.some((f) => fontWhitelist.has(f) || genericFamilies.has(f));
      return allowed ? origCheck.apply(this, arguments) : false;
    }, 'check');
  }
})();
