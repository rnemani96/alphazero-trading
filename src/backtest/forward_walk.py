"""
Forward Walk Validation Engine
src/backtest/forward_walk.py

Implements sliding-window backtesting to prevent overfitting.
"""

import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any
from src.backtest.engine import BacktestEngine

logger = logging.getLogger("FORWARD_WALK")

class ForwardWalk:
    def __init__(self, engine: BacktestEngine):
        self.engine = engine
        self.results = []

    def run(self, 
            total_start: str, 
            total_end: str, 
            symbols: List[str],
            train_days: int = 180,
            test_days: int = 60,
            step_days: int = 60):
        """
        Run sliding window validation.
        """
        start_dt = pd.to_datetime(total_start)
        end_dt = pd.to_datetime(total_end)
        
        current_train_start = start_dt
        
        while True:
            current_train_end = current_train_start + timedelta(days=train_days)
            current_test_start = current_train_end
            current_test_end = current_test_start + timedelta(days=test_days)
            
            if current_test_end > end_dt:
                if current_test_start < end_dt:
                    current_test_end = end_dt
                else:
                    break
            
            logger.info(f"Window: Train {current_train_start.date()} to {current_train_end.date()} | "
                        f"Test {current_test_start.date()} to {current_test_end.date()}")
            
            # Note: In a real ML setup, we'd "train" (optimize params) in the train window
            # For this rule-based system, we can just run the test window
            # but we run the 'train' part too if we want to see cumulative performance.
            
            # Run Out-of-Sample (OOS) Test
            res = self.engine.run(
                current_test_start.strftime('%Y-%m-%d'),
                current_test_end.strftime('%Y-%m-%d'),
                symbols
            )
            
            self.results.append({
                'window_start': current_test_start.isoformat(),
                'window_end': current_test_end.isoformat(),
                'metrics': res.get('metrics', {}),
                'trade_stats': res.get('trade_stats', {})
            })
            
            # Advance the window
            current_train_start += timedelta(days=step_days)
            if current_train_start + timedelta(days=train_days) >= end_dt:
                break
                
        return self.results

    def get_summary(self) -> Dict[str, Any]:
        """
        Aggregate results from all windows.
        """
        if not self.results:
            return {}
            
        avg_sharpe = sum(r['metrics'].get('sharpe', 0) for r in self.results) / len(self.results)
        avg_win_rate = sum(r['trade_stats'].get('win_rate', 0) for r in self.results) / len(self.results)
        
        return {
            "total_windows": len(self.results),
            "avg_oos_sharpe": round(avg_sharpe, 2),
            "avg_oos_win_rate": round(avg_win_rate, 4),
            "windows": self.results
        }
