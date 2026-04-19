"""
scripts/optimize_params.py - Weekly Optuna Hyperparameter Optimization

Runs Bayesian Optimization per-symbol on AlphaZero's technical parameters
(RSI Period, EMA Fast/Slow lengths, ATR lengths).
Does NOT hardcode stocks: it extracts the current universe from config.sectors.
Output is saved to `models/optimized_params.json` for TITAN to ingest dynamically.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta

# Ensure parent is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import numpy as np
import yfinance as yf
try:
    import optuna
except ImportError:
    print("WARNING: Optuna is not installed. Please run: pip install optuna")
    sys.exit(1)

from config.sectors import SECTORS
from src.titan import TitanStrategyEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("OptunaOptimizer")
optuna.logging.set_verbosity(optuna.logging.WARNING) # Suppress trial print spam

# ── Dynamic Universe (No hardcoding) ──────────────────────────────
UNIVERSE = []
for sector, symbols in SECTORS.items():
    UNIVERSE.extend(symbols)

# Ensure models directory exists
os.makedirs("models", exist_ok=True)
PARAM_FILE = "models/optimized_params.json"

class TechnicalOptimizer:
    def __init__(self, symbol: str, df: pd.DataFrame):
        self.symbol = symbol
        self.df = df
        self.titan = TitanStrategyEngine()

    def objective(self, trial):
        """
        The objective is to maximize the cumulative return of the T1 and M1 strategies.
        We tune RSI period, EMA Fast, and EMA Slow.
        """
        # 1. Suggest hyperparameters
        rsi_period = trial.suggest_int("RSI_PERIOD", 7, 21)
        ema_fast   = trial.suggest_int("EMA_FAST", 5, 25)
        ema_slow   = trial.suggest_int("EMA_SLOW", 30, 100)
        atr_period = trial.suggest_int("ATR_PERIOD", 10, 20)
        
        # Inject hyperparams into Titan
        self.titan.optimized_params = {
            self.symbol: {
                "RSI_PERIOD": rsi_period,
                "EMA_FAST": ema_fast,
                "EMA_SLOW": ema_slow,
                "ATR_PERIOD": atr_period
            }
        }
        
        # 2. Re-compute indicators with new params
        ind = self.titan._compute_base(self.df, symbol=self.symbol)
        
        # Simulate a simplified PnL over the dataset
        # Vectorized evaluation of T1 (EMA Cross) and M1 (RSI Reversal)
        
        close  = ind.get("close", np.array([]))
        if len(close) < ema_slow:
            return 0.0
            
        returns = np.diff(close) / close[:-1]
        
        t1_signal = np.zeros(len(close))
        ema20 = ind.get("ema20")
        ema50 = ind.get("ema50")
        if ema20 is not None and ema50 is not None:
            t1_signal = np.where(ema20 > ema50, 1.0, -1.0)
            
        m1_signal = np.zeros(len(close))
        rsi = ind.get("rsi")
        if rsi is not None:
            m1_signal = np.where(rsi < 30, 1.0, np.where(rsi > 70, -1.0, 0.0))
            
        # Shift signal by 1 strictly (prevent lookahead bias)
        t1_signal_shifted = np.roll(t1_signal, 1)[:-1]
        m1_signal_shifted = np.roll(m1_signal, 1)[:-1]
        
        # Net strategy return
        strat_returns = (t1_signal_shifted * 0.5 + m1_signal_shifted * 0.5) * returns
        
        # Maximize Sharpe-like metric (Return / Volatility)
        mean_ret = np.mean(strat_returns)
        std_ret = np.std(strat_returns)
        
        if std_ret < 1e-6:
            return 0.0
            
        sharpe = (mean_ret / std_ret) * np.sqrt(252)
        return sharpe

def optimize_all():
    logger.info("Starting Multi-Stock Bayesian Optimization for %d symbols...", len(UNIVERSE))
    
    # Load existing params to avoid overwriting unchanged stocks
    optimized = {}
    if os.path.exists(PARAM_FILE):
        try:
            with open(PARAM_FILE, "r") as f:
                optimized = json.load(f)
        except:
            pass
            
    # Time window: Last 1 year
    end = datetime.now()
    start = end - timedelta(days=365)
    
    # Fast bulk downloader
    logger.info("Downloading historical market data (1Y)...")
    yf_universe = [s + ".NS" if not s.endswith(".NS") else s for s in UNIVERSE]
    data = yf.download(yf_universe, start=start, end=end, progress=False, group_by="ticker")
    
    for symbol in UNIVERSE:
        yf_symbol = symbol + ".NS" if not symbol.endswith(".NS") else symbol
        # Extract stock specific DF
        try:
            if len(UNIVERSE) > 1:
                df = data[yf_symbol].dropna()
            else:
                df = data.dropna()
                
            if len(df) < 100:
                logger.warning(f"Skipping {symbol} - Insufficient data")
                continue
                
            logger.info(f"Optimizing {symbol} ...")
            
            # Formatting DF to lower case for Titan engine
            df.columns = [c.lower() for c in df.columns]
            
            optimizer = TechnicalOptimizer(symbol, df)
            study = optuna.create_study(direction="maximize")
            # We run 50 trials per stock. For 50 stocks this takes ~ 2 mins total.
            study.optimize(optimizer.objective, n_trials=50, n_jobs=-1) 
            
            best = study.best_params
            optimized[symbol] = best
            logger.info(f"  Best params for {symbol}: {best} (Sharpe: {study.best_value:.2f})")
            
        except Exception as e:
            logger.error(f"Failed optimising {symbol}: {e}")
            
    # Save optimal values
    with open(PARAM_FILE, "w") as f:
        json.dump(optimized, f, indent=4)
        
    logger.info(f"✅ Optimization complete! Parameters saved to {PARAM_FILE}")

if __name__ == "__main__":
    optimize_all()
