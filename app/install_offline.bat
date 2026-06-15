@echo off
REM ============================================================
REM  OFFLINE INSTALL — for air-gapped or no-internet machines
REM
REM  STEP 1 (on a machine WITH internet):
REM    pip download -r requirements.txt -d ./offline_packages
REM    (then copy the entire project folder to the target machine)
REM
REM  STEP 2 (on the target machine, run this script):
REM ============================================================

echo  Offline Install - Photo Organizer
echo  ===================================

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ offline installer from python.org
    pause
    exit /b 1
)

if not exist "offline_packages" (
    echo [ERROR] offline_packages\ folder not found.
    echo         Run on an internet-connected machine first:
    echo           pip download -r requirements.txt -d offline_packages
    pause
    exit /b 1
)

echo Creating virtual environment...
python -m venv .venv
call .venv\Scripts\activate.bat

echo Installing from local packages...
pip install --no-index --find-links=offline_packages -r requirements.txt

echo.
echo  Offline install complete!
echo  Run: run.bat organize "C:\YourPhotos" "D:\Output"
pause
