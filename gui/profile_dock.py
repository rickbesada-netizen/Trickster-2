"""
Per-profile taskbar identity — gives each open profile's browser window
its own separate Windows taskbar button with its own icon (background
color + number badge, matching the favicon each window already gets —
see launcher.py's seed_to_hex_color / build_branding_script), instead of
every profile being grouped under one shared chrome.exe icon.

Windows decides taskbar grouping by a window's AppUserModelID (AUMID).
Left unset, every chrome.exe window gets the same implicit AUMID (based
on the exe's path), so they all stack under one shared taskbar button.
Explicitly assigning a unique AUMID per window breaks it into its own
separate button, which can then get its own icon via WM_SETICON.

Windows-only. On any other platform, or if pywin32/Pillow aren't
installed, apply_taskbar_identity() is a safe no-op so launcher.py
doesn't need its own platform checks.

Earlier versions of this module also drew a floating "dock" panel (a
row of profile icons near the taskbar, ixBrowser-style) using a Tkinter
window running on a background thread. That's been removed: Tkinter's
own message loop on a non-main thread was colliding with pywebview's
main-thread message loop and intermittently hard-crashing the whole app
the moment this module actually became active (i.e. as soon as pywin32
was installed). Real taskbar icons don't need a second GUI toolkit at
all — everything below is plain Win32 API calls with no event loop of
its own, so it can't collide with pywebview like that.
"""

import sys
import tempfile
import threading
import time

_IS_WINDOWS = sys.platform == "win32"

_AVAILABLE = False
_AUMID_AVAILABLE = False
if _IS_WINDOWS:
    try:
        import win32gui
        import win32con
        from PIL import Image, ImageDraw
        _AVAILABLE = True
    except ImportError as e:
        # Was silently swallowed before — meant a missing dependency (e.g.
        # pip installed into a different Python than the one actually
        # running this app) looked identical to "nothing's wrong, this
        # feature just doesn't apply here." Printed now so it's visible
        # the moment the app starts instead of only showing up as "the
        # taskbar icon just isn't changing" with no clue why.
        print(f"[profile_dock] disabled — missing dependency: {e}. "
              f"Run: python -m pip install pywin32 Pillow "
              f"(using the SAME python that runs this app — check with 'where python' "
              f"if you have more than one Python installed).")
        _AVAILABLE = False
    try:
        from win32comext.propsys import propsys, pscon
        _AUMID_AVAILABLE = True
    except ImportError:
        _AUMID_AVAILABLE = False  # ships with standard pywin32, but guard anyway


def snapshot_chromium_hwnds() -> set:
    """Top-level Chromium window handles that exist right now — call this
    immediately BEFORE launching a new profile, so apply_taskbar_identity
    can later find the new window by diffing against this snapshot
    (whichever Chrome_WidgetWin_1 window appears that WASN'T here before)
    instead of guessing at Chromium's window-title format. Title matching
    turned out to be unreliable in practice — "window never appeared" was
    showing up far more than it should have. Safe no-op (empty set) on
    non-Windows or if pywin32 isn't available."""
    if not _AVAILABLE:
        return set()
    found = []

    def _enum(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1":
            found.append(hwnd)

    win32gui.EnumWindows(_enum, None)
    return set(found)


def apply_taskbar_identity(profile_id: str, color: str, badge: str, existing_hwnds: set = None):
    """Gives this profile's browser window its own real Windows taskbar
    button with its own icon. Runs in a background thread since the
    browser window may not exist yet the instant this is called — this
    thread does plain synchronous win32 calls and owns no message loop,
    so it's safe to run alongside pywebview's own main-thread loop.

    existing_hwnds: the result of snapshot_chromium_hwnds() taken right
    before this profile's browser process was launched — lets _find_hwnd
    identify the new window by elimination (present now, wasn't present
    before) instead of relying on title text, which proved unreliable."""
    if not _AVAILABLE:
        return

    def worker():
        # SHGetPropertyStoreForWindow below is a COM call, and COM requires
        # the calling thread to explicitly initialize itself first. Without
        # this, the call doesn't raise a normal Python exception on
        # failure — it can crash the entire process at the native level
        # with no traceback at all, which is exactly what "the whole app
        # just closes" looked like. CoInitialize/CoUninitialize bracket the
        # COM usage on this thread properly.
        com_initialized = False
        if _AUMID_AVAILABLE:
            try:
                import pythoncom
                pythoncom.CoInitialize()
                com_initialized = True
            except Exception as e:
                print(f"Taskbar identity: COM init failed for {profile_id}, skipping AUMID: {e}")

        try:
            _apply(profile_id, color, badge, existing_hwnds or set())
        finally:
            if com_initialized:
                import pythoncom
                pythoncom.CoUninitialize()

    threading.Thread(target=worker, daemon=True).start()


def _apply(profile_id: str, color: str, badge: str, existing_hwnds: set):
    hwnd = None
    for _ in range(40):  # ~6s of polling for the window to appear
        hwnd = _find_hwnd(profile_id, existing_hwnds)
        if hwnd:
            break
        time.sleep(0.15)
    if not hwnd:
        # Print every visible Chromium window title actually seen, so
        # if the title format changes again in some future Chromium
        # build, the mismatch is visible immediately instead of just
        # "never appeared" with no further clue.
        titles = []

        def _enum_debug(h, _):
            if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == "Chrome_WidgetWin_1":
                titles.append(win32gui.GetWindowText(h))

        win32gui.EnumWindows(_enum_debug, None)
        print(f"Taskbar identity skipped for {profile_id}: window never appeared "
              f"(visible Chromium window titles seen: {titles!r})")
        return

    if _AUMID_AVAILABLE:
        try:
            store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
            aumid = f"Trickster.Profile.{profile_id}"
            store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(aumid))
            store.Commit()
            print(f"Taskbar AUMID set for {profile_id}: {aumid}")
        except Exception as e:
            print(f"Taskbar AUMID skipped for {profile_id}: {e}")
    else:
        print(f"Taskbar AUMID skipped for {profile_id}: win32comext.propsys not available "
              f"(should ship with pywin32 — try 'pip install --upgrade pywin32')")

    # Chromium re-asserts its own window icon itself around window
    # creation and navigation events, which silently overwrites a
    # one-shot WM_SETICON call if we only set it once right after the
    # window appears. Reapplying repeatedly for the first ~20s (well
    # past startup + first navigation) outlasts that, instead of
    # racing it once and losing.
    for i in range(20):
        try:
            _set_window_icon(hwnd, color, badge)
            if i == 0:
                print(f"Taskbar icon set for {profile_id} (badge {badge!r})")
        except Exception as e:
            print(f"Taskbar icon skipped for {profile_id}: {e}")
            break
        time.sleep(1)


def _find_hwnd(profile_id: str, existing_hwnds: set):
    """Finds this profile's window primarily by elimination — whichever
    visible Chrome_WidgetWin_1 window(s) exist now that didn't exist in
    existing_hwnds (captured right before this profile's browser process
    was launched). Falls back to the old title-prefix match only to break
    a tie if multiple new windows appeared at once (e.g. an extension
    consent popup opening alongside the main window) — new-vs-title is
    the primary signal specifically because title matching alone had been
    unreliable (window title timing, exact suffix format, etc. all could
    cause a false miss even though the right window was right there).

    document.title gets locked to profile_id (see launcher.py's branding
    script), but the actual OS window title bar text is Chromium's own
    "{document.title} - {browser name}" — e.g. Chrome for Testing appends
    " - Chrome for Testing" onto whatever document.title says, which is
    why the tie-break below uses startswith() rather than exact equality."""
    current = []

    def _enum(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1":
            current.append(hwnd)

    win32gui.EnumWindows(_enum, None)
    new_windows = [h for h in current if h not in existing_hwnds]

    if len(new_windows) == 1:
        return new_windows[0]
    if len(new_windows) > 1:
        for hwnd in new_windows:
            title = win32gui.GetWindowText(hwnd)
            if title == profile_id or title.startswith(profile_id + " "):
                return hwnd
        return new_windows[0]  # no title matched — best guess: first new one

    # No new window detected at all yet (still loading) — fall back to a
    # plain title match against everything, in case existing_hwnds wasn't
    # available (e.g. called without a snapshot) or something reused a
    # pre-existing handle.
    for hwnd in current:
        title = win32gui.GetWindowText(hwnd)
        if title == profile_id or title.startswith(profile_id + " "):
            return hwnd
    return None


_font_cache = {}


def _font_for(text: str):
    from PIL import ImageFont
    key = 15 if len(text) <= 2 else 11
    if key not in _font_cache:
        try:
            _font_cache[key] = ImageFont.truetype("segoeuib.ttf", key)  # Segoe UI Bold, ships with Windows
        except Exception:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def _set_window_icon(hwnd, color: str, badge: str):
    """Builds a small square icon (background colour + number badge, same
    look as the favicon) and assigns it directly to this window via
    WM_SETICON — this is what the now-separated taskbar button, the
    title bar, and Alt+Tab all pick up. No chrome.exe file is touched."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, 31, 31], radius=7, fill=color)
    draw.text((16, 16), badge, fill="#0a1512", anchor="mm", font=_font_for(badge))

    tmp = tempfile.NamedTemporaryFile(suffix=".ico", delete=False)
    try:
        img.save(tmp.name, format="ICO", sizes=[(32, 32), (16, 16)])
        tmp.close()
        hicon_big = win32gui.LoadImage(0, tmp.name, win32con.IMAGE_ICON, 32, 32, win32con.LR_LOADFROMFILE)
        hicon_small = win32gui.LoadImage(0, tmp.name, win32con.IMAGE_ICON, 16, 16, win32con.LR_LOADFROMFILE)
        win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, hicon_big)
        win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, hicon_small)
    finally:
        # The .ico file only needs to exist long enough for LoadImage to
        # read it — safe to remove right after, the loaded HICON is
        # independent of the file from this point on.
        try:
            import os
            os.unlink(tmp.name)
        except OSError:
            pass
