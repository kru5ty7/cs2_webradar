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

echo.
echo  CS2 WebRadar — Mode Selection
echo  ==============================
echo  1. Normal   (browser tab, no overlay)
echo  2. Minimap  (small draggable overlay window)
echo  3. ESP      (full-screen transparent overlay)
echo.
set /p CHOICE="  Select mode [1-3]: "

if "%CHOICE%"=="1" set MODE=--normal
if "%CHOICE%"=="2" set MODE=--overlay
if "%CHOICE%"=="3" set MODE=--esp

if not defined MODE (
    echo [error] Invalid choice. Defaulting to Normal mode.
    set MODE=--normal
)

echo.
echo [1/2] Starting frontend dev server...
start "CS2Radar Frontend" cmd /c "cd /d "%~dp0\..\webapp" && npm run dev"

echo [2/2] Starting backend (mode: %MODE%)...
timeout /t 2 /nobreak >nul
python main.py %MODE%
pause
