"""
src/backtest/walk_forward.py  —  AlphaZero Capital
════════════════════════════════════════════════════
Walk-Forward Validation Engine

Delegates heavy lifting to BacktestEngine._walk_forward().
This module exists as a lightweight entry point / scheduler.
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional
from .engine import BacktestEngine

logger = logging.getLogger("WalkForward")


class WalkForwardEngine:
    """
    Convenience wrapper around BacktestEngine.run(walk_forward=True).

    Usage:
        wfe = WalkForwardEngine()
        report = wfe.run(symbols=['TCS', 'RELIANCE'], train_months=6, test_months=1)
    """

    def __init__(self, data_fetcher=None, train_months: int = 6,
                 test_months: int = 1, total_months: int = 24):
        self.fetcher      = data_fetcher
        self.train_months = train_months
        self.test_months  = test_months
        self.windows      = total_months // test_months

    def run(self, symbols: Optional[List[str]] = None,
            strategies: Optional[List[str]] = None) -> Dict:
        engine = BacktestEngine()
        result = engine.run(
            symbols=symbols,
            walk_forward=True,
            save=True,
        )
        wf = result.get('walk_forward', {})
        if wf:
            ranked = sorted(wf.items(), key=lambda x: x[1].get('oos_sharpe', 0), reverse=True)
            logger.info("Walk-forward results (OOS Sharpe):")
            for strat, metrics in ranked:
                logger.info("  %-30s Sharpe=%.2f WR=%.1f%% grade=%s",
                            strat, metrics.get('oos_sharpe', 0),
                            metrics.get('oos_win_rate', 0) * 100,
                            metrics.get('grade', '?'))
        return result
