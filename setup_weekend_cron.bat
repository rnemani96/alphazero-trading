@echo off
setlocal

echo ===================================================
echo AlphaZero Capital - Windows Task Scheduler Setup
echo ===================================================
echo This script will configure your Windows OS to automatically run
echo the heavy AI retraining jobs every Saturday, so your models
echo are continuously updated for Monday's open without manual work.
echo.

:: Define the absolute path to the Python scripts directory
set PROJECT_DIR=d:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE
set PYTHON_EXE=python

echo [1/3] Scheduling Bayesian Parameter Optimization (Optuna)
echo Runs every Saturday at 10:00 AM...
schtasks /create /tn "AlphaZero_Weekly_Optuna" /tr "cmd.exe /c cd /d %PROJECT_DIR% && %PYTHON_EXE% scripts\optimize_params.py >> logs\cron_optuna.log 2>&1" /sc weekly /d SAT /st 10:00 /f

echo.
echo [2/3] Scheduling NEXUS Regime Classification Retraining (XGBoost)
echo Runs every Saturday at 11:30 AM...
schtasks /create /tn "AlphaZero_Weekly_Nexus" /tr "cmd.exe /c cd /d %PROJECT_DIR% && %PYTHON_EXE% scripts\train_nexus.py --once >> logs\cron_nexus.log 2>&1" /sc weekly /d SAT /st 11:30 /f

echo.
echo [3/3] Scheduling KARMA RL Actor-Critic Retraining (PPO)
echo Runs every Saturday at 13:00 (1:00 PM)...
schtasks /create /tn "AlphaZero_Weekly_Karma_RL" /tr "cmd.exe /c cd /d %PROJECT_DIR% && %PYTHON_EXE% scripts\train_model.py >> logs\cron_karma.log 2>&1" /sc weekly /d SAT /st 13:00 /f

echo.
echo ===================================================
echo SUCCESS! All AlphaZero weekend jobs are now scheduled.
echo To view, modify, or delete them, type 'Task Scheduler' into your Windows Start menu.
echo Logs for these background jobs will be saved automatically to your \logs\ folder.
echo ===================================================
pause
