"""
Makes locked extensions genuinely non-removable through chrome://extensions
itself, using Chromium's real enterprise policy mechanism — instead of only
reacting after the fact (run_extension_monitor_loop in launcher.py closes
the profile once an extension is already gone, which doesn't stop someone
from clicking Remove in the first place).

Chromium reads extension policy from the Windows registry, under a fixed
path tied to the "Google Chrome" product identity — this applies to every
Chromium-family build that identifies as Google Chrome on this Windows
account, which includes "Chrome for Testing" (the build patchright downloads
and launches; it's deliberately built to read the same policies as regular
Chrome, since that's what makes it useful for enterprise policy testing in
the first place). There is no way to scope this to only one --user-data-dir
— it's an OS-account-level setting, not a per-launch one. If a real,
everyday Google Chrome install also exists on this Windows account, this
same policy applies there too.

ExtensionInstallForcelist entries are "<extension_id>;<update_url>" — the
same shape used for the "Add from Chrome Web Store" flow in gui/app.py, and
only extensions installed *that* way (i.e. ones with a genuine Chrome Web
Store update_url in their manifest.json, like Cold Turkey Blocker) have a
real update_url to put here. Extensions added as a bare unpacked folder/zip
with no such URL are skipped — there's nothing Chrome could fetch to
force-install them from, so forcelist can't enforce those the same way; they
still fall back to the existing close-on-removal monitoring in launcher.py.

Windows-only. Safe no-op (returns False) on any other platform or if the
registry write fails for any reason (e.g. run without the permissions
needed to write HKCU — this key doesn't require admin, but errs safe).
"""

import sys

_IS_WINDOWS = sys.platform == "win32"

_POLICY_PATH = r"Software\Policies\Google\Chrome\ExtensionInstallForcelist"


def _enum_value_names(key):
    import winreg
    names = []
    i = 0
    while True:
        try:
            name, _, _ = winreg.EnumValue(key, i)
            names.append(name)
            i += 1
        except OSError:
            break
    return names


def apply_forcelist(entries: list[tuple[str, str]]) -> bool:
    """entries: [(extension_id, update_url), ...]. Replaces the entire
    forcelist with exactly this set every time (clears old numbered values
    first) so removed/renamed extensions don't linger as stale policy
    entries. Returns True if the registry write succeeded."""
    if not _IS_WINDOWS:
        return False
    import winreg
    try:
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, _POLICY_PATH, 0, winreg.KEY_ALL_ACCESS
        )
    except OSError as e:
        print(f"[extension_policy] couldn't open/create ExtensionInstallForcelist: {e}")
        return False
    try:
        for name in _enum_value_names(key):
            try:
                winreg.DeleteValue(key, name)
            except OSError:
                pass
        for idx, (ext_id, update_url) in enumerate(entries, start=1):
            winreg.SetValueEx(key, str(idx), 0, winreg.REG_SZ, f"{ext_id};{update_url}")
        print(f"[extension_policy] ExtensionInstallForcelist set: {len(entries)} extension(s) "
              "now non-removable through chrome://extensions.")
        return True
    except OSError as e:
        print(f"[extension_policy] couldn't write ExtensionInstallForcelist values: {e}")
        return False
    finally:
        winreg.CloseKey(key)


def clear_forcelist() -> bool:
    """Removes every entry — used once extensions are actually unlocked, so
    Remove becomes clickable again as intended."""
    if not _IS_WINDOWS:
        return False
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _POLICY_PATH, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return True  # nothing to clear
    except OSError as e:
        print(f"[extension_policy] couldn't open ExtensionInstallForcelist to clear it: {e}")
        return False
    try:
        for name in _enum_value_names(key):
            try:
                winreg.DeleteValue(key, name)
            except OSError:
                pass
        print("[extension_policy] ExtensionInstallForcelist cleared — extensions removable again.")
        return True
    finally:
        winreg.CloseKey(key)
