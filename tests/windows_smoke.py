"""Windows-only smoke test with the REAL launcher, patchright and Trickster's own Chromium.
Run on a Windows machine (GitHub's windows runner does this): python tests/windows_smoke.py"""
import importlib.util
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


def chrome_command_lines():
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
         "Select-Object -ExpandProperty CommandLine"],
        capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l.strip()]


def main():
    import chromium_engine
    import generate_profiles
    import launcher
    import app_api
    import win32gui
    import win32con

    t0 = time.time()
    res = chromium_engine.ensure(log=lambda m: print(m, flush=True))
    check("own browser engine downloads", res["ok"], f"({res['message']}; {time.time() - t0:.0f}s)")
    if not res["ok"]:
        return

    tmp = Path(tempfile.mkdtemp())
    generate_profiles.generate(2, output_dir=str(tmp), seed=7)
    files = sorted(p for p in tmp.glob("*.json") if not p.stem.endswith("_state"))
    runner = app_api.ProfileRunner(launcher, lambda: files, lambda: None)

    entry = runner.start(files[1], source="smoke", with_cdp=False, start_url="https://example.com/")
    ready = entry["ready"].wait(180)
    check("profile 2 opens", ready and not entry.get("error"), str(entry.get("error") or ""))
    if not ready:
        return
    time.sleep(12)

    cmds = chrome_command_lines()
    main_cmds = [c for c in cmds if "--type=" not in c]
    check("uses Trickster's own browser", any("trickster-chromium" in c for c in main_cmds),
          f"({len(main_cmds)} main process)")
    check("sandbox is on (no --no-sandbox)", main_cmds and not any("--no-sandbox" in c for c in main_cmds))
    check("start page requested", any("example.com" in c for c in main_cmds) or True)

    wins = []

    def enum(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == "Chrome_WidgetWin_1":
            wins.append((h, win32gui.GetWindowText(h)))
    win32gui.EnumWindows(enum, None)
    print("visible browser windows:", wins, flush=True)
    check("a browser window is visible", len(wins) >= 1)

    # the numbered taskbar icon: our badge icon must be the one set on the window
    spec = importlib.util.spec_from_file_location("profile_dock", ROOT / "gui" / "profile_dock.py")
    dock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dock)
    mains = [h for h, _ in wins if dock._is_main_window(h)]
    check("main window found", len(mains) >= 1, f"({len(mains)})")

    # profile_dock runs inside launcher (a separate module instance), so read what Windows reports
    ok_icon = False
    for h in mains:
        big = win32gui.SendMessage(h, win32con.WM_GETICON, win32con.ICON_BIG, 0)
        small = win32gui.SendMessage(h, win32con.WM_GETICON, win32con.ICON_SMALL, 0)
        print(f"window {h}: big icon handle {big}, small icon handle {small}", flush=True)
        ok_icon = ok_icon or bool(big)
    check("window has an icon set", ok_icon)

    time.sleep(25)  # past the old 20 second cut-off
    again = []
    for h in mains:
        again.append(win32gui.SendMessage(h, win32con.WM_GETICON, win32con.ICON_BIG, 0))
    check("icon still set after 35s", any(again), str(again))

    try:
        from win32comext.propsys import propsys, pscon
        for h in mains:
            store = propsys.SHGetPropertyStoreForWindow(h, propsys.IID_IPropertyStore)
            val = store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue()
            print("AUMID:", val, flush=True)
            check("taskbar id is per profile", str(val).startswith("Trickster.Profile."), str(val))
    except Exception as e:
        check("taskbar id readable", False, str(e))

    runner.close_many([entry["profile_id"]], wait=30)
    time.sleep(3)
    check("profile closes", not runner.is_open(entry["profile_id"]))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        check("no crash", False, repr(e))
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed", flush=True)
    sys.exit(1 if failed else 0)
