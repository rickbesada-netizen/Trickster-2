# Shared extensions

Drop unpacked Chrome extension folders in here — each one its own subfolder
containing a `manifest.json` at its root (this is what you get from
unzipping a `.crx`, or from "Load unpacked" in Chrome's own extensions
page). Every profile loads every extension found here, the same set, every
time — so extension behaviour stays consistent across all your profiles
rather than varying per-profile.

Example layout:
```
extensions/
  ublock-origin/
    manifest.json
    ...
  my-custom-extension/
    manifest.json
    ...
```

Notes:
- Extensions require a visible (non-headless) browser window — `launcher.py`
  will automatically force `--headless` off if any extensions are configured
  here, and print a note when it does.
- Getting an unpacked folder from the Chrome Web Store: the simplest route
  is usually installing the extension in a normal (non-automated) Chrome
  profile first, then locating its folder under Chrome's own
  `Extensions/<id>/<version>/` directory and copying that folder here. CRX
  files can also be unzipped directly if you have one.
