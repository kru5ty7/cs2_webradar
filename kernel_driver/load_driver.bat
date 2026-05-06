@echo off
:: load_driver.bat — one-click driver load/unload for development
::
:: Run as Administrator (right-click → Run as administrator)
::
:: What this does:
::   sc create  — registers the .sys file as a kernel service in the registry
::   sc start   — tells the kernel to load the driver (calls DriverEntry)
::   sc stop    — unloads the driver (calls DriverUnload)
::   sc delete  — removes the registry entry (does NOT delete the .sys file)

setlocal
set SYS=%~dp0x64\Release\driver.sys

:: ── Check we're admin ────────────────────────────────────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [error] Must run as Administrator
    pause & exit /b 1
)

:: ── Enable test signing (needed to load unsigned drivers) ────────────────────
:: This persists across reboots.  Only needed once.
:: Remove this line and reboot when you have a properly signed driver.
bcdedit /set testsigning on >nul 2>&1

if "%1"=="stop" goto STOP

:: ── LOAD ─────────────────────────────────────────────────────────────────────
echo [1/3] Registering service...
sc create CS2Radar type= kernel binPath= "%SYS%" >nul 2>&1
:: sc create returns 1073 if the service already exists — that's fine
if %errorlevel% gtr 1073 (
    echo [warn] sc create returned %errorlevel% — trying anyway
)

echo [2/3] Loading driver (calls DriverEntry)...
sc start CS2Radar
if %errorlevel% neq 0 (
    echo [error] sc start failed — check DebugView for DbgPrint output
    echo         Common causes:
    echo           - Test signing not enabled  (bcdedit /set testsigning on + reboot)
    echo           - .sys not found at: %SYS%
    echo           - Driver bug (BSOD or STATUS_FAILED_DRIVER_ENTRY)
    pause & exit /b 1
)

echo [3/3] Driver loaded.  Python can now open \\.\CS2Radar
echo.
echo Run "load_driver.bat stop" to unload when done.
goto END

:STOP
:: ── UNLOAD ────────────────────────────────────────────────────────────────────
echo [1/2] Stopping driver (calls DriverUnload)...
sc stop CS2Radar

echo [2/2] Removing registry entry...
sc delete CS2Radar

echo Driver unloaded.

:END
pause
