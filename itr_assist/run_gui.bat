@echo off
setlocal
cd /d "%~dp0.."

echo Launching ITR-2 Foreign Assets Assistant GUI...

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m itr_assist.gui
) else (
    python -m itr_assist.gui
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Application exited with error code %ERRORLEVEL%.
    pause
)
