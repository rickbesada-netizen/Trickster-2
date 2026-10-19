@echo off
REM Builds Trickster.exe. Run this from the project root on Windows
REM (PyInstaller does not cross-compile — this must run ON Windows to
REM produce a Windows .exe, not from this Linux sandbox).
REM
REM Usage:
REM   pip install -r requirements.txt
REM   build_exe.bat

python -m PyInstaller --name Trickster --onefile --windowed --noconfirm ^
  --icon "assets\icon.ico" ^
  --add-data "assets;assets" ^
  --add-data "gui/web;gui/web" ^
  --add-data "fingerprint_injection.js;." ^
  --add-data "gui/cloud_config.json;gui" ^
  --add-data "gui/profile_dock.py;gui" ^
  --add-data "extensions;extensions" ^
  --hidden-import win32gui ^
  --hidden-import win32con ^
  --hidden-import win32comext.propsys.propsys ^
  --hidden-import win32comext.propsys.pscon ^
  --hidden-import pythoncom ^
  --hidden-import pywintypes ^
  --hidden-import chromium_engine ^
  --hidden-import PIL.Image ^
  --hidden-import PIL.ImageDraw ^
  --collect-all patchright ^
  gui/app.py

REM The --hidden-import lines above exist because gui/profile_dock.py is
REM loaded dynamically at runtime (by raw file path, not a normal "import
REM profile_dock" anywhere else) so it also works from standalone scripts
REM that don't have gui/ on sys.path. The cost: PyInstaller's automatic
REM dependency scanner works by statically reading "import X" statements
REM in the code it analyzes, and never actually opens a file that's only
REM referenced by path at runtime — so it has no way to know profile_dock.py
REM needs win32gui/pywintypes/PIL etc, and silently leaves them out. Confirmed
REM by testing: the file loaded fine, then failed with "No module named
REM 'win32gui'" the moment it tried to import that. If profile_dock.py's own
REM imports ever change, this list needs to match.

echo.
echo Build finished. Find Trickster.exe in the dist/ folder.
echo Chromium itself is downloaded automatically on first run now (see the
echo "Setting up the browser engine..." screen) — no manual
echo "patchright install chromium" step needed for people running the exe.
echo Extensions (AppBlocker Web Filter etc) are bundled into the exe and
echo seed themselves into place on first run too — no manual copying
echo needed for a real customer running this, either.
