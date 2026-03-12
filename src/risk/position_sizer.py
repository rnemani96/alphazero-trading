"""
src/risk/position_sizer.py  —  AlphaZero Capital
══════════════════════════════════════════════════
FIX: Full Kelly Criterion implementation (was PARTIAL)

Methods:
  kelly_size()     — Full Kelly with win rate + avg win/loss
  half_kelly()     — Safer: 50% of full Kelly (recommended)
  atr_size()       — ATR-based position sizing (1% account risk / ATR)
  optimal_size()   — Combined: min(kelly, atr) for conservative sizing
"""

from __future__ import annotations
import logging
from typing import Optional, Dict
import numpy as np

logger = logging.getLogger("PositionSizer")

# Max position size per risk settings
MAX_POSITION_PCT = float(0.05)   # 5% of capital max per position


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Full Kelly Criterion: f* = (p*b - q) / b
    where p = win_rate, q = 1-p, b = avg_win/avg_loss ratio

    Returns fraction of capital to bet (0.0 to 1.0).
    Clamped to [0, MAX_POSITION_PCT].
    """
    if win_rate <= 0 or avg_win <= 0 or avg_loss <= 0:
        return 0.0
    q = 1 - win_rate
    b = avg_win / avg_loss          # win/loss ratio
    f = (win_rate * b - q) / b
    # Negative Kelly = don't trade this strategy
    if f <= 0:
        return 0.0
    return min(f, MAX_POSITION_PCT)


def half_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Half-Kelly (recommended for live trading).
    Reduces variance significantly while keeping most of the growth rate.
    """
    return kelly_fraction(win_rate, avg_win, avg_loss) * 0.5


def atr_position_size(capital: float, entry_price: float,
                       atr: float, risk_pct: float = 0.01) -> int:
    """
    ATR-based position sizing.
    risk_pct = fraction of capital to risk per trade (default 1%)
    stop_distance = 2x ATR

    Returns number of shares.
    """
    if entry_price <= 0 or atr <= 0:
        return 0
    stop_distance = 2 * atr
    risk_per_trade = capital * risk_pct
    shares = risk_per_trade / stop_distance
    # Cap at MAX_POSITION_PCT
    max_shares = (capital * MAX_POSITION_PCT) / entry_price
    return int(min(shares, max_shares))


def optimal_position_size(capital: float, entry_price: float, atr: float,
                           win_rate: float = 0.55, avg_win: float = 1.5,
                           avg_loss: float = 1.0, risk_pct: float = 0.01) -> Dict:
    """
    Combined sizing: take the more conservative of Kelly and ATR.

    Returns dict with:
      shares       - number of shares to buy
      kelly_pct    - Kelly recommended %
      atr_shares   - ATR-based shares
      final_shares - final recommended shares
      stop_loss    - ATR-based stop loss price
      capital_used - ₹ value of position
    """
    if entry_price <= 0:
        return {"shares": 0, "capital_used": 0}

    # Kelly fraction of capital
    k_frac    = half_kelly(win_rate, avg_win, avg_loss)
    k_shares  = int((capital * k_frac) / entry_price) if k_frac > 0 else 0

    # ATR shares
    a_shares  = atr_position_size(capital, entry_price, atr, risk_pct)

    # Most conservative
    final     = min(k_shares, a_shares) if (k_shares > 0 and a_shares > 0) else max(k_shares, a_shares)
    final     = max(1, final) if final > 0 else 0

    stop_loss = round(entry_price - (2 * atr), 2) if atr > 0 else round(entry_price * 0.97, 2)

    return {
        "shares":       final,
        "kelly_pct":    round(k_frac * 100, 2),
        "atr_shares":   a_shares,
        "kelly_shares": k_shares,
        "final_shares": final,
        "stop_loss":    stop_loss,
        "capital_used": round(final * entry_price, 2),
    }


class PositionSizer:
    """
    Stateful position sizer that tracks win/loss history
    and computes adaptive Kelly fractions per strategy/symbol.
    """

    def __init__(self, total_capital: float, max_position_pct: float = 0.05):
        self.capital        = total_capital
        self.max_pct        = max_position_pct
        self._history: Dict[str, list] = {}   # strategy → [+pnl, -pnl, ...]

    def record_trade(self, strategy: str, pnl: float):
        """Record a closed trade PnL for Kelly learning."""
        self._history.setdefault(strategy, []).append(pnl)

    def _strategy_stats(self, strategy: str):
        trades = self._history.get(strategy, [])
        if len(trades) < 10:
            # Not enough history — use conservative defaults
            return 0.55, 1.5, 1.0
        wins  = [t for t in trades if t > 0]
        losses= [abs(t) for t in trades if t < 0]
        wr    = len(wins) / len(trades)
        aw    = np.mean(wins)   if wins   else 0.01
        al    = np.mean(losses) if losses else 0.01
        return wr, aw, al

    def size(self, strategy: str, entry_price: float, atr: float) -> Dict:
        wr, aw, al = self._strategy_stats(strategy)
        return optimal_position_size(
            self.capital, entry_price, atr, wr, aw, al
        )
