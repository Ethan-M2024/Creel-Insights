@echo off
REM Double-click to fetch the newest WDFW reports and rebuild the dashboard.
REM Everything this does lives in run.py, so the button and the command line
REM behave identically.
cd /d "%~dp0"
where py >nul 2>&1 && (py run.py --update & goto :eof)
where python >nul 2>&1 && (python run.py --update & goto :eof)
echo.
echo   Python was not found on this PC.
echo   Install it from https://www.python.org/downloads/ and try again,
echo   or just double-click "Open Dashboard (Windows).bat" to view the
echo   data already in this folder without updating it.
echo.
pause
