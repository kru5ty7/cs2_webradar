@echo off
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [error] Python not found. Install from https://python.org
    pause
    exit /b 1
)

pip show websocket-client >nul 2>&1
if errorlevel 1 (
    echo [info] installing dependencies...
    pip install -r requirements.txt
)

echo [info] starting ai_agent_helper...
python main.py
pause
