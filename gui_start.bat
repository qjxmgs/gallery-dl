@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0gui_start.py" %*
) else (
    python "%~dp0gui_start.py" %*
)
if errorlevel 1 pause
endlocal
