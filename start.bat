@echo off
setlocal enabledelayedexpansion
title RWTS Research Platform
cd /d "%~dp0backend"

if "%RWTS_PORT%"=="" set RWTS_PORT=8000

echo ============================================================
echo  RWTS - Reliability-Weighted Task Scheduling
echo  Research simulation platform (CS427)
echo ============================================================
echo.

REM ====================================================================
REM 1. Find a REAL Python 3.10+.
REM    The "python.exe" in WindowsApps is a Microsoft Store placeholder
REM    that only prints an advertisement, so every candidate is verified
REM    by actually executing it.
REM ====================================================================
set "PYCMD="

call :try "py -3.13"
call :try "py -3.12"
call :try "py -3.11"
call :try "py -3"
call :try "python"
call :try "python3"
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :try "\"%%~fD\python.exe\""
for /d %%D in ("%ProgramFiles%\Python3*")                do call :try "\"%%~fD\python.exe\""
for /d %%D in ("C:\Python3*")                            do call :try "\"%%~fD\python.exe\""
call :try "\"%USERPROFILE%\anaconda3\python.exe\""
call :try "\"%USERPROFILE%\miniconda3\python.exe\""
call :try "\"%LOCALAPPDATA%\Programs\Microsoft VS Code\python.exe\""

if not defined PYCMD (
  echo [X] No working Python 3.10+ installation was found.
  echo.
  echo     What you almost certainly saw above is the Microsoft Store
  echo     placeholder: Windows ships a fake "python.exe" that only prints
  echo     an advertisement. It is not Python.
  echo.
  echo     Fix it in one of two ways:
  echo.
  echo     A^) RECOMMENDED - install real Python
  echo        1. Go to https://www.python.org/downloads/windows/
  echo        2. Download "Windows installer ^(64-bit^)" for Python 3.12 or 3.11
  echo        3. Run it and TICK "Add python.exe to PATH" on the first screen
  echo        4. Click "Install Now", then close and re-run this file
  echo.
  echo     B^) If you believe Python IS installed
  echo        Settings ^> Apps ^> Advanced app settings ^> App execution aliases
  echo        and turn OFF both "python.exe" and "python3.exe".
  echo        Then close and re-run this file.
  echo.
  echo     Already have Python somewhere unusual? Point this script at it:
  echo        set RWTS_PYTHON=C:\path\to\python.exe
  echo        start.bat
  echo.
  pause
  exit /b 1
)

echo [1/4] Python: %PYCMD%
%PYCMD% --version

REM ====================================================================
REM 2. Virtual environment
REM ====================================================================
if not exist ".venv\Scripts\python.exe" (
  echo [2/4] Creating virtual environment ^(first run only^)...
  %PYCMD% -m venv .venv
  if errorlevel 1 (
    echo.
    echo [X] Could not create the virtual environment.
    echo     If this is a managed university machine, try running this file
    echo     from a folder outside OneDrive, e.g. C:\CS427\Application.
    pause
    exit /b 1
  )
  call ".venv\Scripts\activate.bat"
  echo [3/4] Installing dependencies - this takes 1-3 minutes the first time...
  python -m pip install --upgrade pip --quiet
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [X] Dependency installation failed.
    echo     Usually a network or proxy issue. On a university network try:
    echo        .venv\Scripts\python -m pip install -r requirements.txt --proxy http://your.proxy:port
    pause
    exit /b 1
  )
) else (
  echo [2/4] Virtual environment found.
  call ".venv\Scripts\activate.bat"
  echo [3/4] Dependencies already installed.
)

REM ====================================================================
REM 3. Open the browser only once the port actually accepts connections
REM ====================================================================
start /min "" powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$p=%RWTS_PORT%; for($i=0;$i -lt 240;$i++){ try{ $c=New-Object Net.Sockets.TcpClient('127.0.0.1',$p); $c.Close(); Start-Process ('http://127.0.0.1:'+$p); break } catch { Start-Sleep -Milliseconds 500 } }"

REM ====================================================================
REM 4. Run the server
REM ====================================================================
echo [4/4] Starting server on http://127.0.0.1:%RWTS_PORT%
echo.
echo     The dashboard opens by itself once the server is ready.
echo     Leave this window OPEN while you work. Ctrl+C stops the server.
echo.
python run.py
echo.
echo Server stopped.
pause
exit /b 0

REM ====================================================================
REM :try  - accept a candidate interpreter only if it really runs and
REM         reports version 3.10 or newer. WindowsApps stubs are skipped.
REM ====================================================================
:try
if defined PYCMD exit /b 0
set "CAND=%~1"
if defined RWTS_PYTHON set "CAND=\"%RWTS_PYTHON%\""
echo %CAND% | findstr /i "WindowsApps" >nul && exit /b 0
%CAND% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
for /f "delims=" %%V in ('%CAND% -c "import sys; print(sys.executable)" 2^>nul') do (
  echo %%V | findstr /i "WindowsApps" >nul && exit /b 0
)
set "PYCMD=%CAND%"
exit /b 0
