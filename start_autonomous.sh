#!/usr/bin/env bash
# AlphaZero Capital - 24/7 Autonomous Trading Engine Launcher
set -e

echo "======================================================================="
echo "         AlphaZero Capital - 24/7 Autonomous Trading Engine"
echo "======================================================================="

mkdir -p logs data models data/cache

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 could not be found. Please install Python 3.11+."
    exit 1
fi

echo "[*] Launching 24/7 Self-Healing Supervisor Watchdog..."
exec python3 scripts/watchdog.py
