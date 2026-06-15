@echo off
REM ====================================================================
REM Build Photo Organizer (.exe + installer)
REM
REM Prerequisites (one-time):
REM   1. Python 3.13 64-bit installed (we pin to 3.13 for stable wheels;
REM      `py -3.13` from the Python launcher must work).
REM   2. py -3.13 -m pip install -r requirements.txt
REM   3. py -3.13 -m pip install pyinstaller
REM   4. (Optional, for installer) Inno Setup 6 from https://jrsoftware.org/isinfo.php
REM
REM Usage:
REM   build.bat            -> builds .exe only
REM   build.bat installer  -> also runs Inno Setup
REM
REM Why `py -3.13`? The Python launcher (`py.exe`) lets us pin to 3.13
REM regardless of what `python` resolves to on PATH. Avoids the trap of
REM building against a 3.14 interpreter that doesn't have the wheels.
REM ====================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY=py -3.13"

echo.
echo === Photo Organizer build ===
echo.

REM --- 0. Sanity-check the interpreter ---
%PY% --version >nul 2>&1
if errorlevel 1 (
    echo [build] FAILED: Python 3.13 not found via `py -3.13`.
    echo [build]         Install Python 3.13 from python.org or the Microsoft Store.
    exit /b 1
)
%PY% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [build] FAILED: PyInstaller is not installed in Python 3.13.
    echo [build]         Run:  %PY% -m pip install pyinstaller
    exit /b 1
)

REM --- 1. Ensure assets/app_icon.ico exists ---
if not exist "app\assets\app_icon.ico" (
    echo [build] Generating default app icon...
    %PY% app\tools\make_app_icon.py
    if errorlevel 1 (
        echo [build] WARN: icon generation failed; continuing without icon
    )
)

REM --- 2. Wipe previous build artifacts ---
if exist "build"  rmdir /s /q "build"
if exist "dist"   rmdir /s /q "dist"

REM --- 3. PyInstaller ---
echo.
echo [build] Running PyInstaller...
echo.
%PY% -m PyInstaller PhotoOrganizer.spec --clean --noconfirm
if errorlevel 1 (
    echo [build] FAILED: PyInstaller errored out.
    exit /b 1
)

REM --- 4. Smoke-test the .exe ---
echo.
echo [build] Smoke-testing executable...
if not exist "dist\PhotoOrganizer\PhotoOrganizer.exe" (
    echo [build] FAILED: dist exe missing.
    exit /b 1
)
echo [build] OK: dist\PhotoOrganizer\PhotoOrganizer.exe

REM --- 5. Optional: build installer ---
if /i "%1"=="installer" (
    echo.
    echo [build] Running Inno Setup...
    set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    if not exist "!ISCC!" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
    if not exist "!ISCC!" (
        echo [build] WARN: ISCC.exe not found. Install Inno Setup 6 first.
        exit /b 0
    )
    "!ISCC!" app\installer.iss
    if errorlevel 1 (
        echo [build] FAILED: Inno Setup errored out.
        exit /b 1
    )
    echo [build] Installer created in installer\Output\
)

echo.
echo === Build complete ===
echo.
endlocal
