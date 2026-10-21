@echo off
title AlphaZero Autonomous Trading System
color 0A

echo =======================================================================
echo          AlphaZero Capital - 24/7 Autonomous Trading Engine
echo =======================================================================
echo.
echo [1/3] Checking environment...
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if exist "venv\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment (venv)...
    call venv\Scripts\activate.bat
    set PYTHON_EXE=venv\Scripts\python.exe
) else (
    set PYTHON_EXE=python
)

%PYTHON_EXE% --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found. Please install Python 3.11+.
    pause
    exit /b 1
)

echo [2/3] Verifying dependencies and models...
if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "models" mkdir models

echo [3/3] Starting Autonomous Supervisor Watchdog...
%PYTHON_EXE% scripts\watchdog.py

pause
