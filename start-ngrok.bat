@echo off
echo ============================================
echo   CS2 WebRadar - Ngrok Setup
echo ============================================
echo.
echo This script will expose your webapp to the internet via ngrok.
echo.
echo STEP 1: Start two ngrok tunnels
echo    - One for the webapp (port 5173)
echo    - One for the WebSocket server (port 22006)
echo.
echo INSTRUCTIONS:
echo   1. Open a NEW terminal and run:
echo        ngrok http 22006
echo   2. Copy the "Forwarding" URL (e.g. https://xxxx.ngrok-free.app)
echo   3. Come back here and paste it when prompted.
echo.

set /p WS_NGROK_URL="Paste your ngrok WebSocket URL (from step 2): "

echo.
echo Setting VITE_WS_URL...

REM Convert https:// to wss:// for WebSocket
set "WS_URL=%WS_NGROK_URL%"
set "WS_URL=%WS_URL:https://=wss://%"
set "WS_URL=%WS_URL:http://=ws://%"

REM Append the WebSocket path
set "WS_URL=%WS_URL%/cs2_webradar"

echo WebSocket URL: %WS_URL%
echo.

REM Write the .env file for Vite
echo VITE_WS_URL=%WS_URL%> "webapp\.env"

echo Starting the webapp...
echo.
echo STEP 2: Open ANOTHER new terminal and run:
echo        ngrok http 5173
echo.
echo Share THAT ngrok URL with your friends to access the radar!
echo.

start "cs2_webradar - webapp" cmd /k "cd webapp && npm run dev"

pause
