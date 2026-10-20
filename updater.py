"""
Automatic updates and one-time data move for the installed Trickster.

- Update: on start, compares this build's number (version.txt, written by the
  GitHub build) with the "latest" release. If a newer TricksterSetup.exe
  exists it is downloaded and installed silently, then Trickster reopens.
- Move: if this install has no profiles yet, looks in Downloads/Desktop/
  Documents for an older Trickster's `profiles` folder and copies it here
  (logins included). The old folder is left untouched.

Everything is best-effort: any problem is logged and Trickster just starts.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

REPO = "rickbesada-netizen/Trickster-2"
API = f"https://api.github.com/repos/{REPO}/releases/tags/latest"


def local_build(resource_dir):
    try:
        return int((Path(resource_dir) / "version.txt").read_text().strip())
    except Exception:
        return 0


def _json(url, timeout=15):
    import json
    req = urllib.request.Request(url, headers={"User-Agent": "Trickster", "Accept": "application/vnd.github+json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())


def check(resource_dir):
    """Returns {"available": bool, "build": int, "url": str|None}."""
    mine = local_build(resource_dir)
    if mine <= 0:
        return {"available": False, "build": 0, "url": None}
    rel = _json(API)
    m = re.search(r"Build\s+(\d+)", rel.get("body") or "")
    theirs = int(m.group(1)) if m else 0
    url = next((a["browser_download_url"] for a in rel.get("assets", []) if a["name"] == "TricksterSetup.exe"), None)
    return {"available": bool(url and theirs > mine), "build": theirs, "url": url}


def install(url, installed_exe, log=print):
    """Downloads the installer and runs it silently; Trickster reopens afterwards."""
    fd, path = tempfile.mkstemp(suffix=".exe", prefix="TricksterSetup_")
    os.close(fd)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Trickster"}), timeout=60) as r, open(path, "wb") as out:
        shutil.copyfileobj(r, out)
    log(f"[update] downloaded {path}")
    cmd = f'"{path}" /SILENT /CLOSEAPPLICATIONS /NORESTART && start "" "{installed_exe}"'
    subprocess.Popen(["cmd", "/c", cmd], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Timer(1.0, os._exit, [0]).start()


def installed_exe_path():
    return str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Trickster" / "Trickster.exe")


def _real_profiles(d: Path):
    try:
        return any(p.suffix == ".json" and not p.stem.endswith("_state") for p in d.iterdir())
    except OSError:
        return False


def migrate_old_data(profiles_dir: Path, log=print):
    """Copy an older Trickster's profiles (+ logins) here if this one has none."""
    profiles_dir = Path(profiles_dir)
    if _real_profiles(profiles_dir):
        return False
    home = Path.home()
    roots = [home / "Downloads", home / "Desktop", home / "Documents"]
    found = []
    for root in roots:
        if not root.exists():
            continue
        for depth_dir in [root] + [p for p in root.iterdir() if p.is_dir()][:200]:
            cand = depth_dir / "profiles"
            try:
                if cand.is_dir() and cand.resolve() != profiles_dir.resolve() and _real_profiles(cand):
                    found.append(cand)
            except OSError:
                continue
    if not found:
        return False
    best = max(found, key=lambda p: p.stat().st_mtime)
    log(f"[migrate] copying old profiles from {best}")
    profiles_dir.mkdir(parents=True, exist_ok=True)
    for item in best.iterdir():
        dest = profiles_dir / item.name
        try:
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        except Exception as e:
            log(f"[migrate] skipped {item.name}: {e}")
    return True
