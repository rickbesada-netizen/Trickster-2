@echo off
setlocal
cd /d "%~dp0"
title Building Trickster
echo.
echo ===== Building Trickster.exe (this takes about 5-10 minutes) =====
echo.

set "PY="
py -3.12 --version >nul 2>nul && set "PY=py -3.12"
if not defined PY ( python --version >nul 2>nul && set "PY=python" )
if not defined PY (
  echo Python is not installed yet.
  echo 1. Go to https://www.python.org/downloads/release/python-3129/
  echo 2. Download "Windows installer ^(64-bit^)" and run it.
  echo 3. TICK the box "Add python.exe to PATH" on the first screen, then Install.
  echo 4. Close this window and double-click Build Trickster.bat again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating a private Python folder...
  %PY% -m venv .venv
  if errorlevel 1 ( echo Could not create the Python folder. & pause & exit /b 1 )
)
call ".venv\Scripts\activate.bat"

echo Installing what Trickster needs...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 ( echo Installing failed - check your internet and try again. & pause & exit /b 1 )

echo Building the app...
call build_exe.bat

if not exist "dist\Trickster.exe" (
  echo.
  echo The build did not produce Trickster.exe. Scroll up for the error and send me a screenshot.
  pause
  exit /b 1
)

copy /Y "dist\Trickster.exe" "%USERPROFILE%\Downloads\Trickster.exe" >nul
echo.
echo ===== DONE =====
echo Trickster.exe is now in your Downloads folder.
echo ^(Windows may show "Windows protected your PC" the first time: click More info, then Run anyway.^)
pause
