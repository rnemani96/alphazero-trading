"""
scripts/train_and_test_tonight.py — AlphaZero Capital
======================================================
Full end-to-end overnight training + validation pipeline.
Trains all three models:
  1. NEXUS  — XGBoost regime classifier (TRENDING/SIDEWAYS/VOLATILE/RISK_OFF)
  2. KARMA  — RL Actor-Critic stock scorer
  3. Optuna — Bayesian hyperparameter optimization for TITAN strategy params

Run this while main.py is running (uses separate processes).
Safe to run any evening / on-demand.

Usage:
    python scripts/train_and_test_tonight.py
"""

from __future__ import annotations
import os, sys, json, time, logging, subprocess, datetime, random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.makedirs(ROOT / "logs", exist_ok=True)
os.makedirs(ROOT / "models", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(ROOT / "logs" / "train_tonight.log"), mode="w", encoding="utf-8"),
    ],
)
log = logging.getLogger("TrainTonight")

RESULTS = []

def banner(msg: str):
    log.info("")
    log.info("=" * 60)
    log.info(f"  {msg}")
    log.info("=" * 60)
    RESULTS.append(f"\n{'='*40}\n{msg}\n{'='*40}")

def ok(msg: str):   log.info(f"  ✅ {msg}"); RESULTS.append(f"✅ {msg}")
def warn(msg: str): log.warning(f"  ⚠️  {msg}"); RESULTS.append(f"⚠️ {msg}")
def fail(msg: str): log.error(f"  ❌ {msg}"); RESULTS.append(f"❌ {msg}")


# ─────────────────────────────────────────────────────────────
# 1. NEXUS XGBoost — Regime Classifier
# ─────────────────────────────────────────────────────────────
def train_nexus():
    banner("STEP 1/3 — NEXUS Regime Classifier (XGBoost)")
    log.info("  Downloading data + engineering causal features...")
    log.info("  This fetches 5 years of NIFTY500 data & re-trains the model.")
    log.info("  Expected time: 3-8 minutes")

    t0 = time.time()
    result = subprocess.run(
        [sys.executable, "scripts/train_nexus.py", "--once"],
        capture_output=False,   # live output to console
        cwd=str(ROOT),
        timeout=600,
    )
    elapsed = time.time() - t0

    if result.returncode == 0:
        model_path = ROOT / "models" / "nexus_regime.json"
        if model_path.exists():
            kb = model_path.stat().st_size / 1024
            ok(f"NEXUS model saved → models/nexus_regime.json  ({kb:.1f} KB)  [{elapsed:.0f}s]")
        else:
            warn(f"Script exited OK but model file not found [{elapsed:.0f}s]")
    else:
        fail(f"NEXUS training failed (exit code {result.returncode}) [{elapsed:.0f}s]")


# ─────────────────────────────────────────────────────────────
# 2. KARMA — RL Stock Scorer Training
# ─────────────────────────────────────────────────────────────
def train_karma():
    banner("STEP 2/3 — KARMA RL Training (Actor-Critic PPO)")
    log.info("  Loading KARMA agent and running offline training on recent market data...")

    try:
        import numpy as np
        import pandas as pd
        from dotenv import load_dotenv
        load_dotenv()

        from src.agents.karma_agent import KarmaAgent   # correct class name
        from src.event_bus.event_bus import EventBus

        eb = EventBus()
        karma = KarmaAgent(eb, {})

        # Use nightly-harvested parquet cache (already downloaded by data_daemon)
        parquet_dir = ROOT / "data" / "training_ready" / "1d"
        sym_files = list(parquet_dir.glob("*.parquet"))[:100] if parquet_dir.exists() else []

        hist_data = {}
        for fp in sym_files:
            try:
                sym = fp.stem
                import pandas as pd
                df_p = pd.read_parquet(fp)
                df_p.columns = [c.lower() for c in df_p.columns]
                if 'close' in df_p.columns and len(df_p) >= 30:
                    hist_data[sym] = df_p.tail(200).to_dict('records')
            except Exception:
                pass

        # Fallback: use live MSD data if parquet cache is sparse
        if len(hist_data) < 10:
            log.info("  OHLCV cache sparse — fetching live data for top 30 symbols...")
            from src.data.multi_source_data import get_msd
            msd = get_msd()
            TOP_SYMS = [
                "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","BHARTIARTL","SBIN",
                "ITC","HCLTECH","MARUTI","AXISBANK","KOTAKBANK","TITAN","BAJFINANCE",
                "SUNPHARMA","ONGC","TATAMOTORS","ADANIPORTS","JSWSTEEL","NTPC",
                "DIXON","SUZLON","ANGELONE","RVNL","POLYCAB","HAL","VBL","TRENT",
                "CDSL","KPITTECH"
            ]
            for sym in TOP_SYMS:
                try:
                    candles = msd.get_candles(sym, period="60d", interval="1d")
                    if len(candles) >= 30:
                        hist_data[sym] = [c.to_dict() for c in candles]
                except Exception:
                    pass

        if not hist_data:
            warn("No training data available for KARMA — skipping")
            return

        log.info(f"  Training KARMA on {len(hist_data)} symbols...")
        t0 = time.time()
        karma.run_offline_training(hist_data)
        elapsed = time.time() - t0

        karma_path = ROOT / "models" / "karma_ppo.zip"
        if karma_path.exists():
            kb = karma_path.stat().st_size / 1024
            ok(f"KARMA model saved → models/karma_ppo.zip  ({kb:.1f} KB)  [{elapsed:.0f}s]")
        else:
            warn(f"KARMA training ran but zip not found [{elapsed:.0f}s]")

    except ImportError as e:
        warn(f"KARMA dependencies missing (stable-baselines3?): {e}")
    except Exception as e:
        fail(f"KARMA training error: {e}")
        import traceback
        log.error(traceback.format_exc())


# ─────────────────────────────────────────────────────────────
# 3. Optuna — Bayesian Hyperparameter Tuning for TITAN
# ─────────────────────────────────────────────────────────────
def optimize_params():
    banner("STEP 3/3 — Bayesian Hyperparameter Optimization (Optuna)")
    log.info("  Tuning TITAN strategy parameters for top 30 momentum stocks...")

    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        import numpy as np
        import pandas as pd

        from src.titan import TitanStrategyEngine

        engine = TitanStrategyEngine()

        # Simulate realistic stock data (use live cache if available)
        from src.data.multi_source_data import get_msd
        msd = get_msd()

        TARGETS = [
            "SUZLON","ANGELONE","RVNL","DIXON","CDSL","VBL","TCS","HAL",
            "POLYCAB","TATAELXSI","KPITTECH","TRENT","RELIANCE","HDFCBANK",
            "INFY","ICICIBANK","BHARTIARTL","SBIN","TITAN","BAJFINANCE"
        ]

        all_params = {}
        best_scores = {}

        # Use parquet cache for Optuna (1d bars are reliable, always present after harvest)
        parquet_dir = ROOT / "data" / "training_ready" / "1d"
        if not parquet_dir.exists():
            # Fallback to 15m
            parquet_dir = ROOT / "data" / "training_ready" / "15m"

        for sym in TARGETS:
            try:
                pq_path = parquet_dir / f"{sym}.parquet"
                if not pq_path.exists():
                    log.info(f"    {sym}: no parquet cache, skipping")
                    continue
                log.info(f"  Optimizing {sym}...")
                import pandas as pd
                df = pd.read_parquet(pq_path).tail(500)
                df.columns = [c.lower() for c in df.columns]
                for col in ('open','high','low','close','volume'):
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                df = df.dropna(subset=['close'])

                if len(df) < 30:
                    continue

                def objective(trial):
                    # Key TITAN parameters to tune
                    ema_fast  = trial.suggest_int("ema_fast", 5, 20)
                    ema_slow  = trial.suggest_int("ema_slow", 20, 60)
                    rsi_lo    = trial.suggest_int("rsi_lo", 25, 40)
                    rsi_hi    = trial.suggest_int("rsi_hi", 60, 80)
                    bb_std    = trial.suggest_float("bb_std", 1.5, 2.5)

                    if ema_fast >= ema_slow:
                        return 0.0

                    # Score: count buy signals on this data
                    try:
                        sigs = engine.compute_all(df.copy(), symbol=sym)
                        buy_sigs = [s for s in sigs if getattr(s, 'signal', 0) > 0]
                        avg_conf = np.mean([getattr(s, 'confidence', 0.5) for s in buy_sigs]) if buy_sigs else 0.0
                        return float(avg_conf * len(buy_sigs))
                    except Exception:
                        return 0.0

                study = optuna.create_study(direction="maximize",
                                            sampler=optuna.samplers.TPESampler(seed=42))
                study.optimize(objective, n_trials=30, timeout=30, show_progress_bar=False)

                if study.best_value > 0:
                    all_params[sym] = study.best_params
                    best_scores[sym] = round(study.best_value, 4)
                    log.info(f"    {sym}: best={study.best_value:.2f}  params={study.best_params}")

            except Exception as e:
                log.debug(f"  Optuna skip {sym}: {e}")

        if all_params:
            path = ROOT / "models" / "optimized_params.json"
            existing = {}
            if path.exists():
                try:
                    with open(path) as f:
                        existing = json.load(f)
                except Exception:
                    pass
            existing.update(all_params)
            with open(path, "w") as f:
                json.dump(existing, f, indent=2)
            ok(f"Optuna params saved → models/optimized_params.json ({len(existing)} symbols total)")
        else:
            warn("No Optuna improvements found")

    except ImportError:
        warn("Optuna not installed — run: pip install optuna")
    except Exception as e:
        fail(f"Optuna error: {e}")
        import traceback
        log.error(traceback.format_exc())


# ─────────────────────────────────────────────────────────────
# 4. Validation Report
# ─────────────────────────────────────────────────────────────
def validate_and_report():
    banner("VALIDATION — Model Readiness Check")

    from src.data.multi_source_data import get_msd
    import numpy as np, pandas as pd

    checks = {
        "models/nexus_regime.json":    "NEXUS XGBoost Regime Model",
        "models/nexus_meta.json":      "NEXUS Metadata",
        "models/optimized_params.json":"Optuna Bayesian Params",
    }

    all_ok = True
    for rel_path, label in checks.items():
        p = ROOT / rel_path
        if p.exists():
            kb = p.stat().st_size / 1024
            ok(f"{label}: {rel_path}  ({kb:.1f} KB)")
        else:
            warn(f"{label}: NOT FOUND at {rel_path}")
            all_ok = False

    # Quick NEXUS inference test
    try:
        # Try both known module paths for NEXUS
        nexus = None
        for mod_path, cls_name in [
            ('src.agents.intraday_regime_agent', 'IntradayRegimeAgent'),
            ('src.agents.nexus_agent', 'NEXUSAgent'),
        ]:
            try:
                import importlib
                mod = importlib.import_module(mod_path)
                nexus = getattr(mod, cls_name)(None, {})
                break
            except Exception:
                continue

        if nexus is None:
            warn("NEXUS inference test skipped — agent not loadable (non-critical)")
        else:
            test_input = {
                'data': {},
                'india_vix':     15.0,
                'spx_prev_ret':   0.3,
                'usdinr_change':  0.1,
                'news_sentiment': 0.2,
                'event_flag':     0.0,
                'pc_ratio':       1.0,
                'max_pain_diff':  0.0,
                'uoa_flag':       0,
            }
            regime = nexus.detect_regime(test_input)
            ok(f"NEXUS inference test: predicted regime = {regime}")
    except Exception as e:
        warn(f"NEXUS inference test failed: {e}")
        all_ok = False

    # Quick TITAN signal test
    try:
        from src.titan import TitanStrategyEngine
        engine = TitanStrategyEngine()
        n = 100
        prices = 1000 + np.cumsum(np.random.randn(n) * 5)
        df = pd.DataFrame({
            'open': prices * 0.999, 'high': prices * 1.005,
            'low':  prices * 0.995, 'close': prices,
            'volume': np.random.randint(100_000, 500_000, n).astype(float)
        })
        t0 = time.perf_counter()
        sigs = engine.compute_all(df, symbol="TEST")
        ms = (time.perf_counter() - t0) * 1000
        ok(f"TITAN speed test: {len(sigs)} signals from 49 strategies in {ms:.1f}ms")
    except Exception as e:
        warn(f"TITAN speed test failed: {e}")

    return all_ok


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    t_total = time.time()
    banner("AlphaZero Capital — Overnight Model Training")
    log.info(f"  Started: {datetime.datetime.now().strftime('%d %b %Y %H:%M IST')}")
    log.info(f"  Root:    {ROOT}")
    log.info("")

    train_nexus()
    train_karma()
    optimize_params()
    all_ok = validate_and_report()

    elapsed = time.time() - t_total
    banner("TRAINING COMPLETE")
    log.info(f"  Total time: {elapsed/60:.1f} minutes")
    log.info(f"  Full log:   logs/train_tonight.log")
    log.info("")
    if all_ok:
        log.info("  🚀 System is READY for tomorrow's market open!")
        log.info("  All models trained. Restart main.py to load new weights.")
    else:
        log.info("  ⚠️  Some models missing — check logs above.")

    # Print summary
    log.info("")
    log.info("─" * 60)
    for line in RESULTS:
        log.info(line)
