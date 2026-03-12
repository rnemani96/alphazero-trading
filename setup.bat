@echo off
REM ===========================================================================
REM AlphaZero Capital — Windows Setup & Launch Script
REM Usage:  setup.bat          (first time — installs dependencies)
REM         setup.bat run      (just run the system)
REM ===========================================================================

setlocal EnableDelayedExpansion
title AlphaZero Capital v18

echo.
echo ============================================================
echo   AlphaZero Capital v18 - Windows Setup
echo ============================================================
echo.

REM ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Download from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
echo [OK] Python found
python --version

REM ── Skip install if "run" argument given ─────────────────────────────────────
if "%1"=="run" goto :run

REM ── Create virtual environment ───────────────────────────────────────────────
if not exist venv (
    echo.
    echo [*] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment exists
)

REM ── Activate venv ────────────────────────────────────────────────────────────
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment
    pause
    exit /b 1
)
echo [OK] Virtual environment activated

REM ── Upgrade pip ──────────────────────────────────────────────────────────────
echo.
echo [*] Upgrading pip...
python -m pip install --upgrade pip setuptools wheel --quiet

REM ── Install requirements ─────────────────────────────────────────────────────
echo.
echo [*] Installing requirements (may take 3-5 minutes)...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [WARN] Some packages failed. Trying individual installs...
    pip install python-dotenv requests pandas numpy yfinance fastapi uvicorn[standard] websockets --quiet
    pip install pandas-ta --quiet
    pip install reportlab scikit-learn psutil colorama tabulate --quiet
)
echo [OK] Dependencies installed

REM ── Create directories ────────────────────────────────────────────────────────
echo.
echo [*] Creating directory structure...
if not exist logs mkdir logs
if not exist logs\reports mkdir logs\reports
if not exist data mkdir data
if not exist data\raw mkdir data\raw
if not exist data\clean mkdir data\clean
if not exist data\features mkdir data\features
if not exist models mkdir models
echo [OK] Directories created

REM ── Create .env if missing ────────────────────────────────────────────────────
echo.
if not exist .env (
    echo [*] Creating .env from template...
    copy .env.template .env >nul
    echo [!] IMPORTANT: Edit .env and add your API keys
    echo     Minimum required: MODE=PAPER (already set)
    echo     Optional: ALPHA_VANTAGE_KEY, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN
) else (
    echo [OK] .env file exists
)

REM ── Create __init__.py files if missing ──────────────────────────────────────
echo.
echo [*] Ensuring package init files...
if not exist src\__init__.py echo # > src\__init__.py
if not exist src\agents\__init__.py echo # > src\agents\__init__.py
if not exist src\data\__init__.py echo # > src\data\__init__.py
if not exist src\risk\__init__.py echo # > src\risk\__init__.py
if not exist src\execution\__init__.py echo # > src\execution\__init__.py
if not exist src\monitoring\__init__.py echo # > src\monitoring\__init__.py
if not exist src\reporting\__init__.py echo # > src\reporting\__init__.py
if not exist src\event_bus\__init__.py echo # > src\event_bus\__init__.py
if not exist src\backtest\__init__.py echo # > src\backtest\__init__.py
if not exist config\__init__.py echo # > config\__init__.py
if not exist dashboard\__init__.py echo # > dashboard\__init__.py
echo [OK] Init files checked

REM ── Test imports ─────────────────────────────────────────────────────────────
echo.
echo [*] Testing critical imports...
python -c "import fastapi, uvicorn, yfinance, pandas, numpy; print('[OK] Core imports work')" 2>&1
if errorlevel 1 (
    echo [WARN] Some imports failed - check errors above
)

echo.
echo ============================================================
echo   Setup Complete!
echo ============================================================
echo.
echo Next steps:
echo   1. Edit .env with your API keys (optional but recommended)
echo   2. Run:  python main.py
echo   OR use:  setup.bat run
echo.

:run
echo.
echo [*] Starting AlphaZero Capital...
echo [*] Dashboard will open at http://localhost:8000
echo [*] Press Ctrl+C to stop
echo.

REM Activate venv if not already active
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

python main.py
if errorlevel 1 (
    echo.
    echo [ERROR] System crashed. Check logs\alphazero.log for details.
    pause
)
endlocal
