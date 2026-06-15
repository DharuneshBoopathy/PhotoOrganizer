@echo off
REM ============================================================
REM  Photo Organizer - Windows Setup Script
REM  Run this ONCE to create the virtual environment and
REM  install all dependencies.
REM ============================================================

echo.
echo  Photo Organizer - Setup
echo  =======================

REM Check Python version
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [1/4] Creating virtual environment...
python -m venv app\.venv
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [2/4] Activating virtual environment...
call app\.venv\Scripts\activate.bat

echo [3/4] Upgrading pip...
python -m pip install --upgrade pip --quiet

echo [4/4] Installing dependencies...
pip install -r app\requirements.txt
if errorlevel 1 (
    echo.
    echo [WARNING] Some packages failed. Trying without InsightFace...
    pip install Pillow imagehash exifread opencv-python numpy scikit-learn tqdm reverse_geocoder
)

echo.
echo  Setup complete!
echo.
echo  To run the organizer:
echo    run.bat organize "C:\path\to\photos" "D:\organized_output"
echo.
echo  To use GPU acceleration (optional):
echo    pip install onnxruntime-gpu
echo.
pause
