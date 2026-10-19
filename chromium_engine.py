"""
Trickster's own browser engine (Windows).

The browser that patchright downloads is "Chrome for Testing". It always shows a
grey "only for automated testing" bar and puts a "Test" badge on the icon, and
Chrome offers no way to hide either. A plain Chromium build (the open-source
browser Chrome is made from) has neither and still allows our bundled
extensions, so Trickster downloads one once, next to the exe, and uses it.

Everything here is best-effort: if the download or the browser fails for any
reason, launcher.py quietly falls back to the patchright browser and profiles
open exactly as before.
"""
import os
import sys
import time
import shutil
import tempfile
import zipfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

DEFAULT_BASE = "https://storage.googleapis.com/chromium-browser-snapshots/Win_x64"
EXE_RELATIVE = Path("chrome-win") / "chrome.exe"
MAX_REVISIONS_TO_TRY = 40  # some snapshot numbers have no Windows build; walk back to one that does


def engine_root() -> Path:
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    base = Path(env) if env else Path(__file__).resolve().parent / "browsers"
    return base / "trickster-chromium"


def installed_exe(root: Optional[Path] = None) -> Optional[str]:
    """Path to our Chromium's chrome.exe if it is installed, else None."""
    root = Path(root) if root else engine_root()
    marker = root / "current.txt"
    try:
        rev = marker.read_text().strip()
    except OSError:
        return None
    exe = root / rev / EXE_RELATIVE
    return str(exe) if exe.exists() else None


def _get(url: str, timeout: float = 30):
    req = urllib.request.Request(url, headers={"User-Agent": "Trickster/1.0"})
    return urllib.request.urlopen(req, timeout=timeout)


def ensure(root: Optional[Path] = None, base: Optional[str] = None,
           log: Callable[[str], None] = print, windows_only: bool = True) -> dict:
    """Downloads and unpacks Chromium once. Returns {"ok": bool, "exe": path|None, "message": str}."""
    if windows_only and sys.platform != "win32":
        return {"ok": False, "exe": None, "message": "Own engine is Windows-only."}
    root = Path(root) if root else engine_root()
    base = (base or os.environ.get("TRICKSTER_SNAPSHOT_BASE") or DEFAULT_BASE).rstrip("/")

    have = installed_exe(root)
    if have:
        return {"ok": True, "exe": have, "message": "Browser engine already installed."}

    try:
        latest = int(_get(f"{base}/LAST_CHANGE").read().decode().strip())
    except Exception as e:
        return {"ok": False, "exe": None, "message": f"Couldn't look up the latest browser build: {e}"}

    root.mkdir(parents=True, exist_ok=True)
    for rev in range(latest, latest - MAX_REVISIONS_TO_TRY, -1):
        url = f"{base}/{rev}/chrome-win.zip"
        tmp_zip = None
        try:
            resp = _get(url, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                continue  # no Windows build for this number, try the one before
            return {"ok": False, "exe": None, "message": f"Download failed ({e.code}) for {url}"}
        except Exception as e:
            return {"ok": False, "exe": None, "message": f"Download failed: {e}"}

        try:
            total = int(resp.headers.get("Content-Length") or 0)
            log(f"[engine] downloading Chromium build {rev} ({total / 1048576:.0f} MB)...")
            fd, tmp_zip = tempfile.mkstemp(suffix=".zip", dir=str(root))
            done = 0
            next_report = 25 * 1048576
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = resp.read(1048576)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if done >= next_report:
                        log(f"[engine] ...{done / 1048576:.0f} MB")
                        next_report += 25 * 1048576
            if total and done != total:
                raise IOError(f"download cut short ({done} of {total} bytes)")

            target = root / str(rev)
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            staging = root / f"{rev}.partial"
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            with zipfile.ZipFile(tmp_zip) as zf:
                zf.extractall(staging)
            if not (staging / EXE_RELATIVE).exists():
                raise IOError("downloaded file didn't contain chrome.exe")
            staging.rename(target)
            (root / "current.txt").write_text(str(rev))
            # tidy up older builds
            for old in root.iterdir():
                if old.is_dir() and old.name != str(rev):
                    shutil.rmtree(old, ignore_errors=True)
            log(f"[engine] Chromium {rev} ready.")
            return {"ok": True, "exe": str(target / EXE_RELATIVE), "message": f"Installed Chromium build {rev}."}
        except Exception as e:
            return {"ok": False, "exe": None, "message": f"Couldn't install the browser engine: {e}"}
        finally:
            if tmp_zip:
                try:
                    os.remove(tmp_zip)
                except OSError:
                    pass

    return {"ok": False, "exe": None, "message": "No Windows browser build found near the latest number."}
