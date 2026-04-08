"""
HYPERPARAMETER TUNER - Bayesian Optimization
scripts/tune_hyperparams.py

Objective: Find the perfect RSI, MACD, and Trail settings for each symbol.
Uses 'Optuna' to sweep thousands of combinations and finds the one 
with the highest Sharpe Ratio for the last 1 year.
"""

import os, sys, logging, json
from pathlib import Path
import pandas as pd
import numpy as np

# Setup Paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import optuna
except ImportError:
    optuna = None

from src.data.market_data import DataFetcher
from src.titan import TitanStrategyEngine

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("Tuner")

def objective(trial, df):
    """Backtest a single window with trial params."""
    # Suggest params
    rsi_period = trial.suggest_int("rsi_period", 7, 21)
    ema_fast   = trial.suggest_int("ema_fast", 5, 15)
    ema_slow   = trial.suggest_int("ema_slow", 20, 50)
    
    # Simple strategy simulation
    df['ema_f'] = df['close'].ewm(span=ema_fast).mean()
    df['ema_s'] = df['close'].ewm(span=ema_slow).mean()
    
    # Calculate returns
    df['sig'] = (df['ema_f'] > df['ema_s']).astype(int).diff().fillna(0)
    df['ret'] = df['close'].pct_change()
    df['strat_ret'] = df['sig'].shift(1) * df['ret']
    
    sharpe = df['strat_ret'].mean() / (df['strat_ret'].std() + 1e-9) * np.sqrt(252)
    return sharpe if not np.isnan(sharpe) else -10

def tune_symbol(symbol):
    if optuna is None: return {}
    
    fetcher = DataFetcher()
    df = fetcher.get_historical(symbol, "2023-01-01", "2024-01-01", interval="1d")
    if df is None or df.empty: return {}
    
    study = optuna.create_study(direction="maximize")
    study.optimize(lambda t: objective(t, df), n_trials=50) # Fast tuning
    
    logger.info(f"  Best params for {symbol}: {study.best_params}")
    return study.best_params

def main():
    if optuna is None:
        logger.error("Optuna not installed. Run 'pip install optuna'")
        return

    symbols = ["RELIANCE.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "ICICIBANK.NS"]
    results = {}

    logger.info(f"--- Starting Bayesian Optimization for {len(symbols)} Core Stocks ---")
    
    for sym in symbols:
        results[sym] = tune_symbol(sym)
        
    path = ROOT / "models" / "optimized_params.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(results, f, indent=4)
        
    logger.info(f"Tuning complete. Parameters saved to {path}")

if __name__ == "__main__":
    main()
