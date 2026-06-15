@echo off
REM ============================================================
REM  Photo Organizer - Run Script
REM  Usage: run.bat <command> [args...]
REM
REM  Examples:
REM    run.bat organize "C:\Photos" "D:\Organized"
REM    run.bat organize "E:\" "D:\Organized" --no-faces
REM    run.bat scan "C:\Photos"
REM    run.bat status "D:\Organized"
REM    run.bat duplicates "D:\Organized"
REM    run.bat label-faces "D:\Organized"
REM    run.bat rollback "D:\Organized" 20240101_120000_abc123
REM ============================================================

if not exist "app\.venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

setlocal
set "PYTHONPATH=%PYTHONPATH%;%~dp0app"
call app\.venv\Scripts\activate.bat
python -m src.cli %*
endlocal
