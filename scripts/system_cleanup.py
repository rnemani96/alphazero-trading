"""
SYSTEM CLEANUP - Daily Maintenance
scripts/system_cleanup.py

Objective: Remove unnecessary files to keep the system fast and smooth.
Rules:
1. Logs: Remove logs older than 7 days.
2. Cache: Remove stale OHLCV parquets older than 30 days.
3. Temp: Clear data/tmp/ and data/cache/tmp/ directories.
4. Backtests: Remove old backtest reports older than 14 days.
"""

import os, sys, time, logging, shutil
from pathlib import Path
from datetime import datetime, timedelta

# Setup Paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("Cleanup")

def run_cleanup():
    logger.info("🧹 Starting Daily System Maintenance...")
    now = time.time()
    
    # ── 1. Clear Logs (> 7 days) ──
    log_dir = ROOT / "logs"
    if log_dir.exists():
        _delete_older_than(log_dir, days=7, pattern="*.log")
        _delete_older_than(log_dir, days=7, pattern="*.xlsx") # Old trade exports
    
    # ── 2. Clear Stale Cache (> 30 days) ──
    cache_dir = ROOT / "data" / "cache" / "ohlcv"
    if cache_dir.exists():
        _delete_older_than(cache_dir, days=30, pattern="*.parquet")
        
    # ── 3. Clear Temporary Directories (Immediate) ──
    tmp_dirs = [
        ROOT / "data" / "cache" / "tmp",
        ROOT / "tmp"
    ]
    for d in tmp_dirs:
        if d.exists():
            shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
            logger.info(f"  Emptied temp directory: {d.name}")

    # ── 4. Clear Old Backtests (> 14 days) ──
    bt_dir = ROOT / "data" / "backtests"
    if bt_dir.exists():
        _delete_older_than(bt_dir, days=14, pattern="*")

    logger.info("🧹 System Cleanup Complete. System is now Optimized.")

def _delete_older_than(directory: Path, days: int, pattern: str):
    cutoff = time.time() - (days * 86400)
    count = 0
    for f in directory.glob(pattern):
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                count += 1
            except Exception:
                pass
    if count > 0:
        logger.info(f"  Deleted {count} stale files from {directory.name} (older than {days} days)")

if __name__ == "__main__":
    run_cleanup()
