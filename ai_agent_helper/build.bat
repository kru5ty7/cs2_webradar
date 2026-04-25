@echo off
setlocal

echo [1/3] Building frontend...
cd /d "%~dp0\..\webapp"
call npm run build
if errorlevel 1 ( echo Frontend build FAILED & pause & exit /b 1 )

echo [2/3] Installing Python deps...
cd /d "%~dp0"
pip install pyinstaller websockets --quiet

echo [3/3] Compiling exe...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

pyinstaller radar.spec --noconfirm
if errorlevel 1 ( echo Compile FAILED & pause & exit /b 1 )

echo.
echo Done — dist\cs2_radar.exe
echo Copy config.json next to the exe before running.
pause
