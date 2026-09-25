@echo off
REM Copyright (c) 2026 Duncan McCalla
REM SPDX-License-Identifier: MIT
REM
REM Master Class Diagnostics Workbench
REM See the LICENSE and NOTICE files in the project root for license text and attribution.

REM ===================================================================
REM  Master Class Diagnostics Workbench - one-click launcher (Windows)
REM
REM  Double-click this file. It will:
REM    1. Find Python (3.11 or newer is required)
REM    2. Create a PRIVATE environment (.venv) for this tool and install
REM       its packages there. Your own Python install is left untouched.
REM    3. Open the Workbench
REM
REM  If anything goes wrong the window stays open so you can read the
REM  message.
REM ===================================================================
setlocal
title Master Class Diagnostics Workbench
cd /d "%~dp0.."

set "UI=App\diagnostics_workbench_ui.py"
if not exist "%UI%" goto :no_ui

set "VENV=.venv"
set "VENV_PY=%VENV%\Scripts\python.exe"
set "VENV_PYW=%VENV%\Scripts\pythonw.exe"
set "BROKEN_VENV="

REM --- If Python was upgraded or removed, an existing venv can point at a
REM --- dead interpreter. Detect that before deciding the environment is usable.
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; sys.exit(0)" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo  The existing private environment is not runnable and will be rebuilt:
        echo      "%CD%\%VENV%"
        echo.
        set "BROKEN_VENV=1"
    )
)

REM --- Find a Python launcher (only needed to create the .venv) ---------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)

REM --- First-run notice (only when the private env does not exist yet) --
if not exist "%VENV_PY%" (
    echo.
    echo  This tool keeps its packages in its OWN private environment:
    echo      "%CD%\%VENV%"
    echo  Your existing Python installation and packages are NOT changed,
    echo  upgraded, or removed.
    echo.
    pause
)

if exist "%VENV_PY%" if not defined BROKEN_VENV goto :launch
if not defined PY goto :no_python
if defined BROKEN_VENV (
    echo Removing the broken private environment...
    rmdir /s /q "%VENV%"
    if exist "%VENV%" goto :venv_failed
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
if errorlevel 1 goto :old_python
echo Creating the private environment ^(.venv^)...
%PY% -m venv "%VENV%"
if errorlevel 1 goto :venv_failed
echo Installing packages into the private environment. The first run can take a minute.
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install -r "requirements.txt"
if errorlevel 1 goto :pip_failed

:launch
if not exist "%VENV_PY%" goto :venv_missing
echo.
echo Launching the Workbench...
if exist "%VENV_PYW%" (
    start "" "%VENV_PYW%" "%UI%"
    REM Give the window a moment before the console closes so any status
    REM text printed above can be read.
    ping -n 3 127.0.0.1 >nul
    endlocal
    exit /b 0
)
"%VENV_PY%" "%UI%"
set "RC=%errorlevel%"
if not "%RC%"=="0" goto :app_failed
endlocal
exit /b 0

REM --- Error handlers (keep the window open) ---------------------------
:no_ui
echo [ERROR] Could not find "%UI%".
echo Keep this launcher in the Launchers folder.
goto :fail
:no_python
echo [ERROR] Python was not found on this PC.
echo Install Python 3.11 or newer from https://www.python.org/downloads/
echo and tick "Add Python to PATH" during setup, then try again.
goto :fail
:old_python
echo [ERROR] Python 3.11 or newer is required, but an older version was found.
echo Install Python 3.11 or newer from https://www.python.org/downloads/
goto :fail
:venv_failed
echo [ERROR] Could not create the private environment (.venv).
goto :fail
:venv_missing
echo [ERROR] The private environment is missing its Python (%VENV_PY%).
echo Delete the .venv folder and run this launcher again.
goto :fail
:pip_failed
echo [ERROR] Installing packages failed. See the messages above.
echo Tip: delete the .venv folder and run this launcher again.
goto :fail
:app_failed
echo.
echo [ERROR] The Workbench closed with error code %RC%.
:fail
echo.
echo Press any key to close this window.
pause >nul
endlocal
exit /b 1
