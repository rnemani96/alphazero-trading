@echo off
setlocal

echo ===================================================
echo AlphaZero Capital - Windows Task Scheduler Setup
echo ===================================================
echo This script will configure your Windows OS to automatically run
echo all heavy AI retraining AND pre-market setup jobs every weekend,
echo so AlphaZero is sharp and ready every Monday without any manual work.
echo.

:: Define the absolute path to the project directory
set PROJECT_DIR=d:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE
set PYTHON_EXE=python

echo ══════════════════════════════════════════════
echo  SATURDAY JOBS — Retraining
echo ══════════════════════════════════════════════
echo.

echo [1/5] Bayesian Parameter Optimization (Optuna)
echo Runs every Saturday at 10:00 AM...
schtasks /create /tn "AlphaZero_SAT_Optuna" /tr "cmd.exe /c cd /d %PROJECT_DIR% && %PYTHON_EXE% scripts\optimize_params.py >> logs\cron_optuna.log 2>&1" /sc weekly /d SAT /st 10:00 /f
if %errorlevel%==0 (echo    OK) else (echo    FAILED)

echo.
echo [2/5] NEXUS Regime Classification Retraining (XGBoost)
echo Runs every Saturday at 11:30 AM...
schtasks /create /tn "AlphaZero_SAT_Nexus" /tr "cmd.exe /c cd /d %PROJECT_DIR% && %PYTHON_EXE% scripts\train_nexus.py --once >> logs\cron_nexus.log 2>&1" /sc weekly /d SAT /st 11:30 /f
if %errorlevel%==0 (echo    OK) else (echo    FAILED)

echo.
echo [3/5] KARMA RL Actor-Critic Retraining (PPO)
echo Runs every Saturday at 1:00 PM...
schtasks /create /tn "AlphaZero_SAT_Karma_RL" /tr "cmd.exe /c cd /d %PROJECT_DIR% && %PYTHON_EXE% scripts\train_model.py >> logs\cron_karma.log 2>&1" /sc weekly /d SAT /st 13:00 /f
if %errorlevel%==0 (echo    OK) else (echo    FAILED)

echo.
echo ══════════════════════════════════════════════
echo  SUNDAY JOBS — Pre-Market Preparation
echo ══════════════════════════════════════════════
echo.

echo [4/5] Performance Self-Test
echo Runs every Sunday at 7:30 PM...
schtasks /create /tn "AlphaZero_SUN_PerfTest" /tr "cmd.exe /c cd /d %PROJECT_DIR% && %PYTHON_EXE% scripts\perf_test.py >> logs\cron_perftest.log 2>&1" /sc weekly /d SUN /st 19:30 /f
if %errorlevel%==0 (echo    OK) else (echo    FAILED)

echo.
echo [5/5] Pre-Monday Setup (NEXUS re-verify + Model Validation + Telegram Report)
echo Runs every Sunday at 8:00 PM...
schtasks /create /tn "AlphaZero_SUN_PreMonday" /tr "cmd.exe /c cd /d %PROJECT_DIR% && %PYTHON_EXE% scripts\pre_monday_setup.py >> logs\cron_premonday.log 2>&1" /sc weekly /d SUN /st 20:00 /f
if %errorlevel%==0 (echo    OK) else (echo    FAILED)

echo.
echo ══════════════════════════════════════════════
echo  COMPLETE WEEKEND AUTOMATION SCHEDULE
echo ══════════════════════════════════════════════
echo.
echo  SAT 10:00 AM  AlphaZero_SAT_Optuna        (Bayesian param tuning)
echo  SAT 11:30 AM  AlphaZero_SAT_Nexus          (XGBoost regime model)
echo  SAT  1:00 PM  AlphaZero_SAT_Karma_RL       (PPO RL retraining)
echo  SUN  7:30 PM  AlphaZero_SUN_PerfTest        (Speed baseline check)
echo  SUN  8:00 PM  AlphaZero_SUN_PreMonday       (Validation + Telegram alert)
echo.
echo  All logs saved automatically to your \logs\ folder.
echo  To view/edit jobs: Start Menu → Task Scheduler → Task Scheduler Library
echo.
pause
