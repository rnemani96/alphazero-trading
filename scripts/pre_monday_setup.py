"""
scripts/pre_monday_setup.py — AlphaZero Capital Pre-Market Automation
======================================================================
Runs automatically every Sunday evening at 8:00 PM via Windows Task Scheduler.
Also safe to run manually at any time.

Steps:
  1. Performance self-test (validate speed baseline)
  2. NEXUS XGBoost regime model training
  3. Verify models/ directory has required files
  4. Send Telegram summary of what's ready for Monday

Usage:
  python scripts/pre_monday_setup.py
"""

import os
import sys
import json
import time
import logging
import subprocess
from datetime import datetime
from pathlib import Path

# ── Setup ──────────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/pre_monday_setup.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("PreMondaySetup")

from dotenv import load_dotenv
load_dotenv()

REPORT = []  # Collects lines for the Telegram summary

def step(title: str):
    logger.info("")
    logger.info(f"{'─'*55}")
    logger.info(f"  {title}")
    logger.info(f"{'─'*55}")
    REPORT.append(f"\n*{title}*")

def ok(msg: str):
    logger.info(f"  ✅ {msg}")
    REPORT.append(f"✅ {msg}")

def warn(msg: str):
    logger.warning(f"  ⚠️  {msg}")
    REPORT.append(f"⚠️ {msg}")

def fail(msg: str):
    logger.error(f"  ❌ {msg}")
    REPORT.append(f"❌ {msg}")


# ── Step 1: Performance Self-Test ─────────────────────────────────────────────
def run_perf_test():
    step("1/4 — Performance Self-Test")
    try:
        from config.sectors import SECTORS
        from concurrent.futures import ThreadPoolExecutor
        import pandas as pd
        import numpy as np
        from src.titan import TitanStrategyEngine

        symbols = [s for syms in SECTORS.values() for s in syms]
        ok(f"Universe loaded: {len(symbols)} symbols across {len(SECTORS)} sectors")

        # TITAN speed test
        engine = TitanStrategyEngine()
        n = 100
        prices  = 1000 + np.cumsum(np.random.randn(n) * 5)
        df = pd.DataFrame({
            'open': prices * 0.999, 'high': prices * 1.005,
            'low': prices * 0.995, 'close': prices,
            'volume': np.random.randint(100_000, 500_000, n).astype(float)
        })
        t0 = time.perf_counter()
        for _ in range(20):
            engine.compute_all(df, symbol="PERF_TEST")
        t1 = time.perf_counter()
        ms_per = (t1 - t0) / 20 * 1000
        ok(f"TITAN speed: {ms_per:.1f}ms per symbol × {len(symbols)} = {ms_per*len(symbols)/1000:.2f}s total")

        # Parallel fetch simulation
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=50) as ex:
            list(ex.map(lambda _: time.sleep(0.05), symbols))
        t1 = time.perf_counter()
        ok(f"50-worker parallel: {t1-t0:.2f}s for {len(symbols)} tasks (sequential would be {len(symbols)*0.05:.1f}s)")

    except Exception as e:
        fail(f"Performance test error: {e}")


# ── Step 2: NEXUS XGBoost Retraining ─────────────────────────────────────────
def run_nexus_training():
    step("2/4 — NEXUS Regime Model Retraining")
    nexus_log = "logs/cron_nexus_premarket.log"
    try:
        logger.info("  Training NEXUS XGBoost model... (may take 1-2 minutes)")
        result = subprocess.run(
            [sys.executable, "scripts/train_nexus.py", "--once"],
            capture_output=True, text=True, timeout=300,
            cwd=str(Path(__file__).resolve().parent.parent)
        )
        # Write output to log
        with open(nexus_log, "w", encoding="utf-8") as f:
            f.write(result.stdout)
            f.write(result.stderr)

        if result.returncode == 0:
            ok("NEXUS XGBoost training completed — regime model updated")
        else:
            warn(f"NEXUS training exited with code {result.returncode} — check logs/cron_nexus_premarket.log")

    except subprocess.TimeoutExpired:
        warn("NEXUS training timed out after 5 minutes — will retry next Saturday")
    except Exception as e:
        fail(f"NEXUS training failed: {e}")


# ── Step 3: Model File Validation ─────────────────────────────────────────────
def validate_models():
    step("3/4 — Model File Validation")
    models_dir = Path("models")

    checks = {
        "nexus_model.json":            "NEXUS XGBoost regime classifier",
        "karma_ppo.zip":               "KARMA PPO reinforcement model",
        "karma_ppo_champion.zip":      "Shadow Model — Champion slot",
        "optimized_params.json":       "Bayesian-tuned strategy parameters",
    }

    ready = 0
    for filename, description in checks.items():
        path = models_dir / filename
        if path.exists():
            size_kb = path.stat().st_size / 1024
            ok(f"{description} ({filename}) — {size_kb:.1f} KB")
            ready += 1
        else:
            warn(f"{description} ({filename}) — NOT FOUND (using defaults)")

    ok(f"Model readiness: {ready}/{len(checks)} files present")

    # Check optimized_params.json has data
    params_path = models_dir / "optimized_params.json"
    if params_path.exists():
        try:
            with open(params_path) as f:
                params = json.load(f)
            ok(f"Optuna params: {len(params)} symbols have custom parameters")
        except Exception:
            warn("optimized_params.json exists but could not be parsed")


# ── Step 4: Telegram Summary ───────────────────────────────────────────────────
def send_telegram_summary():
    step("4/4 — Sending Monday Readiness Report to Telegram")
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        warn("Telegram not configured — skipping notification (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env)")
        return

    now = datetime.now().strftime("%d %b %Y %I:%M %p")
    message = (
        f"🤖 *AlphaZero Capital — Monday Readiness Report*\n"
        f"_{now} IST_\n\n"
        + "\n".join(REPORT)
        + "\n\n🚀 System is ready for Monday 09:15 AM open.\nRun `python main.py` to launch."
    )

    try:
        import requests
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
        if resp.status_code == 200:
            ok("Telegram readiness report sent successfully!")
        else:
            warn(f"Telegram send failed: HTTP {resp.status_code}")
    except Exception as e:
        warn(f"Telegram delivery error: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("="*55)
    logger.info("  AlphaZero Capital — Pre-Monday Setup")
    logger.info(f"  Started: {datetime.now().strftime('%d %b %Y %H:%M:%S IST')}")
    logger.info("="*55)

    t_start = time.time()

    run_perf_test()
    run_nexus_training()
    validate_models()
    send_telegram_summary()

    elapsed = time.time() - t_start
    logger.info("")
    logger.info("="*55)
    logger.info(f"  Pre-Monday setup complete in {elapsed:.0f}s")
    logger.info(f"  Log saved to: logs/pre_monday_setup.log")
    logger.info("="*55)
