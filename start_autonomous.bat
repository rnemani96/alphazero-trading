@echo off
title AlphaZero Autonomous Trading System
color 0A

echo =======================================================================
echo          AlphaZero Capital - 24/7 Autonomous Trading Engine
echo =======================================================================
echo.
echo [1/3] Checking environment...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found in PATH. Please install Python 3.11+.
    pause
    exit /b 1
)

echo [2/3] Verifying dependencies and models...
if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "models" mkdir models

echo [3/3] Starting Autonomous Supervisor Watchdog...
python scripts\watchdog.py

pause
