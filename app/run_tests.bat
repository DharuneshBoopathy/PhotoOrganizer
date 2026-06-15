@echo off
REM Run all safety and duplicate tests
call .venv\Scripts\activate.bat
echo Running safety tests...
python -m pytest tests/test_safety.py -v
echo.
echo Running duplicate detection tests...
python -m pytest tests/test_duplicates.py -v
echo.
echo Creating test dataset...
python tests/create_test_media.py
pause
