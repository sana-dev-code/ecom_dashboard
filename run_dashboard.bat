@echo off
setlocal EnableExtensions

REM Single launcher (ZIP-friendly). Prefers dist EXE; otherwise runs Python from source.
REM If double-click "does nothing", read: ecom_dashboard_launch.log (next to this file).
REM Niche/HTTP errors after the app starts are logged in the app (see README), not in this file.

set "ROOT=%~dp0"
set "DIST_EXE=%ROOT%dist\ecom_dashboard\ecom_dashboard.exe"
set "SRC_DIR=%ROOT%ecom_dashboard"
set "SRC_APP=%SRC_DIR%\app.py"
set "REQ=%SRC_DIR%\requirements.txt"
set "VENV_DIR=%ROOT%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"
set "LOG=%ROOT%ecom_dashboard_launch.log"

call :log "========"
call :log "START %DATE% %TIME%"
call :log "ROOT=%ROOT%"

REM --- Portable EXE (optional) ---
if exist "%DIST_EXE%" (
  if exist "%ROOT%Files" (
    set "ECOM_DASHBOARD_ROOT=%ROOT%"
  ) else (
    set "ECOM_DASHBOARD_ROOT=%ROOT%dist\"
  )
  if not exist "%ECOM_DASHBOARD_ROOT%Files" mkdir "%ECOM_DASHBOARD_ROOT%Files" >nul 2>&1
  call :log "Launching dist EXE: %DIST_EXE%"
  start "" "%DIST_EXE%"
  exit /b 0
)

REM --- Source mode needs Python ---
if not exist "%SRC_APP%" (
  call :log "ERROR: source app not found: %SRC_APP%"
  echo [ERROR] Source app not found:
  echo   %SRC_APP%
  echo.
  echo Your ZIP should contain: ecom_dashboard\app.py
  pause
  exit /b 1
)

if not exist "%REQ%" (
  call :log "ERROR: requirements not found: %REQ%"
  echo [ERROR] requirements.txt not found:
  echo   %REQ%
  echo.
  pause
  exit /b 1
)

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
  call :log "Python launcher found (py). Ensuring venv + deps..."
  if not exist "%VENV_PY%" (
    call :log "Creating venv: %VENV_DIR%"
    py -3 -m venv "%VENV_DIR%" >>"%LOG%" 2>&1
    if %ERRORLEVEL% neq 0 (
      call :log "ERROR: venv create failed (py -3 -m venv)."
      echo [ERROR] Failed to create virtual environment.
      echo See: %LOG%
      pause
      exit /b 1
    )
  )
  call :log "Installing dependencies..."
  "%VENV_PY%" -m pip install --upgrade pip >>"%LOG%" 2>&1
  "%VENV_PIP%" install -r "%REQ%" >>"%LOG%" 2>&1
  if %ERRORLEVEL% neq 0 (
    call :log "ERROR: pip install failed."
    echo [ERROR] Failed to install dependencies.
    echo See: %LOG%
    pause
    exit /b 1
  )
  call :log "Starting app using venv..."
  if /i "%~1"=="--web" (
    start "eCommerce Dashboard (web)" cmd /k ""%VENV_PY%" "%SRC_APP%" --web"
  ) else (
    start "eCommerce Dashboard" cmd /k ""%VENV_PY%" "%SRC_APP%" --desktop"
  )
  call :log "Started (new console window)."
  exit /b 0
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
  call :log "python found on PATH. Ensuring venv + deps..."
  if not exist "%VENV_PY%" (
    call :log "Creating venv: %VENV_DIR%"
    python -m venv "%VENV_DIR%" >>"%LOG%" 2>&1
    if %ERRORLEVEL% neq 0 (
      call :log "ERROR: venv create failed (python -m venv)."
      echo [ERROR] Failed to create virtual environment.
      echo See: %LOG%
      pause
      exit /b 1
    )
  )
  call :log "Installing dependencies..."
  "%VENV_PY%" -m pip install --upgrade pip >>"%LOG%" 2>&1
  "%VENV_PIP%" install -r "%REQ%" >>"%LOG%" 2>&1
  if %ERRORLEVEL% neq 0 (
    call :log "ERROR: pip install failed."
    echo [ERROR] Failed to install dependencies.
    echo See: %LOG%
    pause
    exit /b 1
  )
  call :log "Starting app using venv..."
  if /i "%~1"=="--web" (
    start "eCommerce Dashboard (web)" cmd /k ""%VENV_PY%" "%SRC_APP%" --web"
  ) else (
    start "eCommerce Dashboard" cmd /k ""%VENV_PY%" "%SRC_APP%" --desktop"
  )
  call :log "Started (new console window)."
  exit /b 0
)

call :log "ERROR: Python not found on PATH."
echo.
echo [ERROR] Python not found.
echo Your colleague must install Python 3 from https://www.python.org/downloads/
echo During setup, tick: "Add python.exe to PATH"
echo Then close terminal windows and double-click RUN_DASHBOARD.bat again.
echo.
echo Details were saved to: %LOG%
pause
exit /b 1


:log
>>"%LOG%" echo %~1
exit /b 0
