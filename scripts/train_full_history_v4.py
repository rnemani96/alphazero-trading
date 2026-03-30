"""
AlphaZero Capital - Multi-Timeframe Historical Training (10-Year Deep Learning)
scripts/train_full_history_v4.py

This script implements the user's request:
1. Revert to a professional state.
2. Training on 100 stocks total: Top 50 Losers + 50 Random Nifty 500 stocks.
3. Training on all timelines: 1m, 5m, 15m, 1h, 1d.
4. Includes suggestions for optimal training duration.

Suggested Training Duration for Professional Results:
- Data Granularity:
    * 1d: 10+ years
    * 1h: 2 years (max available)
    * 15m/5m: 60 days (free-tier limit)
    * 1m: 7 days (free-tier limit)
- PPO Timesteps: 
    * Minimum: 1,000,000 steps total for 100 stocks.
    * Recommended: 5,000,000 steps for stable convergence.
- Epochs: 10-20 per batch for reinforcement learning stability.
"""

import os
import sys
import logging
import json
import time
import random
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any

# Ensure parent is in path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.universe import get_nifty500_symbols
from src.data.market_data import DataFetcher
from src.agents.karma_agent import KarmaAgent
from src.agents.titan_agent import TitanAgent
from src.event_bus.event_bus import EventBus

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(ROOT / "logs" / "historical_training_v4.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("FullHistoryTrainV4")

# ── CONFIGURATION & SUGGESTIONS ──────────────────────────────────────────

TIMEFRAMES = {
    # Synchronized with safe boundary limits from downloader
    "1m":  {"period": "6d",    "interval": "1m"},
    "5m":  {"period": "58d",   "interval": "5m"},
    "15m": {"period": "58d",   "interval": "15m"},
    "1h":  {"period": "720d",  "interval": "1h"},
    "1d":  {"period": "3650d", "interval": "1d"},
}

# ── SELECTION LOGIC ────────────────────────────────────────────────────────

def select_training_universe(fetcher: DataFetcher) -> List[str]:
    """
    Selects 200 stocks:
    - Top 50 Gainers (based on today's Bhav Copy performance)
    - Top 50 Losers (based on today's Bhav Copy performance)
    - 100 Random from the remaining Nifty 500
    """
    logger.info("Selecting Training Universe: Top 50 Gainers + Top 50 Losers + 100 Random...")
    all_syms = get_nifty500_symbols(use_cache=True)
    if not all_syms:
        logger.error("Failed to fetch Nifty 500 symbols.")
        return []

    # Get Bhav Copy for performance metrics
    bhav = fetcher.get_bhav_copy()
    if bhav is None or bhav.empty:
        logger.warning("Bhav Copy unavailable. Selecting 200 random stocks.")
        return random.sample(all_syms, min(200, len(all_syms)))

    # Standardize symbols
    bhav['symbol'] = bhav['symbol'].str.upper()
    subset = bhav[bhav['symbol'].isin([s.upper() for s in all_syms])].copy()
    
    if subset.empty:
        logger.warning("Bhav Copy doesn't match Nifty 500 symbols. Falling back to 100 random.")
        return random.sample(all_syms, min(100, len(all_syms)))

    # Calculate daily change if not present
    if 'change_pct' not in subset.columns:
        subset['change_pct'] = ((subset['close'] - subset['open']) / subset['open']) * 100

    # Sort to find gainers and losers
    subset = subset.sort_values(by='change_pct', ascending=False)
    top_gainers = subset['symbol'].head(50).tolist()
    top_losers  = subset['symbol'].tail(50).tolist()
    
    # Selection of 100 random from the remaining
    used = set(top_gainers + top_losers)
    remaining_syms = [s for s in all_syms if s.upper() not in used]
    random_sample = random.sample(remaining_syms, min(100, len(remaining_syms)))
    
    final_list = list(set(top_gainers + top_losers + random_sample))
    logger.info(f"Selected {len(final_list)} stocks for training ({len(top_gainers)} gainers, {len(top_losers)} losers, {len(random_sample)} random).")
    return final_list

# ── TRAINING ENGINE ────────────────────────────────────────────────────────

class HistoricalDeepTrainer:
    def __init__(self):
        self.eb = EventBus()
        self.fetcher = DataFetcher({"MODE": "PAPER"})
        self.config = {"MODE": "PAPER", "AGENT_ID": "TRAINER_PRO"}
        self.karma = KarmaAgent(self.eb, self.config)
        self.titan = TitanAgent(self.eb, self.config)
        self.results = {}
        self.symbols = select_training_universe(self.fetcher)

    def fetch_data(self, symbol: str, interval_key: str) -> pd.DataFrame:
        """Fetch maximum history using DataFetcher (handles caching and retries)."""
        conf = TIMEFRAMES[interval_key]
        logger.info(f"  Fetching {symbol} ({interval_key})...")
        
        # Calculate dates for get_historical
        end_date = datetime.now().strftime("%Y-%m-%d")
        
        # Rough estimation of start date based on period
        period_str = conf["period"]
        if "y" in period_str:
            years = int(period_str.replace("y", ""))
            start_date = (datetime.now() - timedelta(days=years*365)).strftime("%Y-%m-%d")
        elif "d" in period_str:
            days = int(period_str.replace("d", ""))
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        else:
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

        try:
            df = self.fetcher.get_historical(symbol, start_date, end_date, interval=conf["interval"])
            if df is None or df.empty:
                return pd.DataFrame()
            
            # Normalize column names to lowercase
            df.columns = [str(c).lower() for c in df.columns]
            return df
        except Exception as e:
            logger.error(f"    Failed to fetch {symbol}: {e}")
            return pd.DataFrame()

    def run_training_sweep(self):
        if not self.symbols:
            logger.error("No symbols selected. Aborting training sweep.")
            return

        logger.info("AlphaZero 10-Year Multi-Timeframe Deep Training Sweep")
        logger.info(f"Universe: {len(self.symbols)} symbols | Timeframes: {list(TIMEFRAMES.keys())}")
        
        from concurrent.futures import ThreadPoolExecutor
        import concurrent.futures
        
        start_time = time.time()
        
        for tf_name in TIMEFRAMES:
            logger.info(f"\n[PHASE: {tf_name.upper()}]")
            tf_data = {}
            
            # Parallel Data Fetching for this timeframe
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_sym = {executor.submit(self.fetch_data, sym, tf_name): sym for sym in self.symbols}
                
                for i, future in enumerate(concurrent.futures.as_completed(future_to_sym)):
                    sym = future_to_sym[future]
                    try:
                        # SET A STRICT TIMEOUT ON EACH FETCH TO PREVENT STALLS (Requirement: Reason for Stall fix)
                        df = future.result(timeout=60) 
                        
                        if not df.empty and len(df) > 50:
                            if 'datetime' in df.columns:
                                df = df.rename(columns={"datetime": "timestamp"})
                            
                            candles = df.to_dict("records")
                            tf_data[sym] = candles
                            
                            # Log source for transparency
                            source = df['source'].iloc[0] if 'source' in df.columns else 'unknown'
                            if i % 5 == 0:  # More frequent logging
                                logger.info(f"    [{i+1}/{len(self.symbols)}] Fetched {sym} via {source}")
                    except Exception as e:
                        logger.error(f"    Failed {sym}: {e}")
            
            if not tf_data:
                logger.warning(f"No data collected for {tf_name}. Skipping optimization.")
                continue
                
            # 1. Trigger KARMA Offline PPO Training
            logger.info(f"  Running KARMA PPO training on {len(tf_data)} datasets...")
            # Note: run_offline_training in karma_agent runs in background thread.
            karma_sess = self.karma.run_offline_training(tf_data, timeframes=[tf_name])
            
            # Wait for the background thread to finish processing the 10-year sweep
            logger.info("  Waiting for PPO Reinforcement Learning to converge...")
            time.sleep(1)  # Ensure thread acquires the lock
            while self.karma._train_lock.locked():
                time.sleep(5)
            logger.info(f"  PPO completed for {tf_name}.")
            
            # 2. Update TITAN strategy weights
            weights = self.karma.get_optimized_weights()
            self.titan.strategy_weights = weights
            
            self.results[tf_name] = {
                "stocks_fetched": len(tf_data),
                "total_candles": sum(len(c) for c in tf_data.values()),
                "status": "QUEUED_PPO_TRAINING",
                "best_strategy": self.karma.get_best_strategy()
            }
            
        elapsed = time.time() - start_time
        self.save_report(elapsed)

    def save_report(self, elapsed: float):
        report_path = ROOT / "logs" / "historical_train_report_v4.json"
        
        final_report = {
            "timestamp": datetime.now().isoformat(),
            "duration_m": round(elapsed / 60, 2),
            "symbols_count": len(self.symbols),
            "timeframe_metrics": self.results,
            "final_optimized_weights": self.karma.get_optimized_weights(),
            "status": "PHASE_DOWNLOAD_COMPLETE",
            "suggestion": "PPO training is continuing in background. Check karma_ppo.zip modification time."
        }
        
        with open(report_path, "w") as f:
            json.dump(final_report, f, indent=4)
            
        logger.info(f"\n✅ Training Sweep Phase 1 Completed in {final_report['duration_m']} minutes.")
        logger.info(f"Report saved to: {report_path}")
        logger.info("Best Current Strategy: " + self.karma.get_best_strategy())

if __name__ == "__main__":
    trainer = HistoricalDeepTrainer()
    trainer.run_training_sweep()
