@echo off
REM ============================================================
REM  Build DiagramLabelFormatter.exe  (standalone, fully local)
REM  Run this whenever app.py / convert.py / index.html change.
REM  Output: dist\DiagramLabelFormatter.exe
REM ============================================================
cd /d "%~dp0"

echo Installing/updating build dependencies...
py -m pip install --upgrade pyinstaller -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Building the executable (this takes a minute)...
py -m PyInstaller --noconfirm --onefile --name DiagramLabelFormatter ^
    --add-data "templates;templates" ^
    --collect-all pymupdf ^
    app.py
if errorlevel 1 goto :error

echo.
echo ============================================================
echo  Done. Your program is:
echo     %~dp0dist\DiagramLabelFormatter.exe
echo  Copy that one file anywhere (Desktop, USB stick) and
echo  double-click it. No Python or internet needed.
echo ============================================================
pause
exit /b 0

:error
echo.
echo Build FAILED. Scroll up to see the error.
pause
exit /b 1
