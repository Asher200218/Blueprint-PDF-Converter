@echo off
REM ============================================================
REM  Diagram Label Formatter - one-click launcher (Windows)
REM ============================================================
cd /d "%~dp0"

echo Checking Python dependencies...
py -m pip install --quiet --disable-pip-version-check -r requirements.txt

echo.
echo Starting the web app...
echo Open your browser at:  http://127.0.0.1:5000
echo (Press Ctrl+C in this window to stop the server.)
echo.

REM Open the browser shortly after the server starts.
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:5000"

py app.py
pause
