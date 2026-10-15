@echo off
setlocal
cd /d "%~dp0.."

echo Running ITR-2 Foreign Assets Automation CLI...

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m itr_assist.cli %*
) else (
    python -m itr_assist.cli %*
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Utility exited with error code %ERRORLEVEL%.
    pause
)
