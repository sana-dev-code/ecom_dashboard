@echo off
setlocal enabledelayedexpansion

REM eCommerce Operations Dashboard Launcher
REM Location of the Flask app (workspace): E:\ecom_dashboard\ecom_dashboard

set "APP_DIR=E:\ecom_dashboard\ecom_dashboard"

if not exist "%APP_DIR%\app.py" (
  echo [ERROR] app.py not found at: %APP_DIR%
  echo Please confirm the project folder path.
  exit /b 1
)

cd /d "%APP_DIR%"

REM Double-click behavior: start Desktop App immediately and close this window.
REM Optional: run web mode by passing --web
if /i "%~1"=="--web" (
  start "" python app.py --web
) else (
  start "" python app.py --desktop
)
exit /b 0

