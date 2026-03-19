"""
src/risk/position_sizer.py  —  AlphaZero Capital
══════════════════════════════════════════════════
Position Sizing Engine

Methods:
  kelly_size()    — Full Kelly with win-rate + avg win/loss
  half_kelly()    — 50% Kelly (recommended)
  atr_size()      — ATR-based: risk 1% of capital per ATR stop
  optimal_size()  — min(kelly, atr) — most conservative
  scale_by_vix()  — halve/quarter size based on VIX level

Design:
  - No indicator code (pure math)
  - Stateful: tracks per-strategy outcomes for adaptive Kelly
  - Thread-safe
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from ..utils.stats import kelly_fraction

logger = logging.getLogger("PositionSizer")

MAX_POSITION_PCT = 0.05   # absolute cap: 5% of capital per position
MIN_POSITION_PCT = 0.005  # minimum meaningful position: 0.5%


# ── Functional API (stateless) ────────────────────────────────────────────────

def kelly_size(
    capital:     float,
    entry_price: float,
    win_prob:    float,
    avg_win_pct: float,
    avg_loss_pct:float,
    fraction:    float = 0.5,
) -> int:
    """Return shares to buy using Half-Kelly criterion."""
    if entry_price <= 0:
        return 0
    kf    = kelly_fraction(win_prob, avg_win_pct, avg_loss_pct, fraction)
    value = capital * kf
    return max(1, int(value / entry_price))


def atr_size(
    capital:      float,
    entry_price:  float,
    atr:          float,
    risk_pct:     float = 0.01,   # 1% of capital at risk per trade
    atr_mult:     float = 1.5,    # stop placed at 1.5× ATR
) -> int:
    """Return shares where risk = risk_pct × capital."""
    if entry_price <= 0 or atr <= 0:
        return 0
    stop_distance = atr * atr_mult
    risk_amount   = capital * risk_pct
    qty           = risk_amount / max(stop_distance, 1)
    max_qty       = (capital * MAX_POSITION_PCT) / entry_price
    return max(1, int(min(qty, max_qty)))


def optimal_size(
    capital:      float,
    entry_price:  float,
    atr:          float,
    win_prob:     float = 0.55,
    avg_win_pct:  float = 0.03,
    avg_loss_pct: float = 0.015,
    risk_pct:     float = 0.01,
) -> Dict:
    """
    Combined: take the more conservative of Kelly and ATR sizing.

    Returns:
        qty          : shares to buy
        kelly_qty    : Kelly-derived quantity
        atr_qty      : ATR-derived quantity
        capital_used : ₹ invested
        stop_loss    : ATR-based stop loss price
        target       : 3:1 R:R target price
    """
    kqty = kelly_size(capital, entry_price, win_prob, avg_win_pct, avg_loss_pct)
    aqty = atr_size(capital, entry_price, atr, risk_pct)
    qty  = min(kqty, aqty) if (kqty > 0 and aqty > 0) else max(kqty, aqty)
    qty  = max(1, qty)
    sl   = round(entry_price - 1.5 * atr, 2) if atr > 0 else round(entry_price * 0.975, 2)
    tgt  = round(entry_price + 3.0 * atr, 2) if atr > 0 else round(entry_price * 1.06,  2)

    return {
        'qty':          qty,
        'kelly_qty':    kqty,
        'atr_qty':      aqty,
        'capital_used': round(qty * entry_price, 2),
        'stop_loss':    sl,
        'target':       tgt,
        'risk_amount':  round(abs(entry_price - sl) * qty, 2),
    }


def scale_by_vix(qty: int, vix: float) -> int:
    """Reduce position size based on India VIX level."""
    if vix >= 30:
        return max(1, qty // 4)
    if vix >= 20:
        return max(1, qty // 2)
    return qty


# ── Stateful Sizer (tracks strategy history) ──────────────────────────────────

class PositionSizer:
    """
    Stateful position sizer that adapts Kelly fractions per-strategy.

    Usage:
        sizer = PositionSizer(total_capital=1_000_000)
        result = sizer.size('EMA_Cross', entry_price=2400, atr=30)
        sizer.record_trade('EMA_Cross', pnl=1500)
    """

    def __init__(
        self,
        total_capital:    float = 1_000_000,
        max_position_pct: float = MAX_POSITION_PCT,
        risk_per_trade:   float = 0.01,
    ):
        self.capital         = total_capital
        self.max_pct         = max_position_pct
        self.risk_per_trade  = risk_per_trade
        self._lock           = threading.Lock()
        self._history:  Dict[str, List[float]] = {}   # strategy → [pnl, ...]

    def size(
        self,
        strategy:    str,
        entry_price: float,
        atr:         float,
        vix:         float = 15.0,
    ) -> Dict:
        """
        Compute position size for a strategy.
        Uses historical win-rate if enough data (≥15 trades), else default.
        """
        with self._lock:
            hist = list(self._history.get(strategy, []))

        if len(hist) >= 15:
            wins  = [h for h in hist if h > 0]
            loses = [h for h in hist if h < 0]
            wp    = len(wins)  / len(hist)
            aw    = (sum(abs(w) for w in wins)  / len(wins))  / max(entry_price, 1) if wins  else 0.03
            al    = (sum(abs(l) for l in loses) / len(loses)) / max(entry_price, 1) if loses else 0.015
        else:
            wp, aw, al = 0.55, 0.03, 0.015

        result       = optimal_size(self.capital, entry_price, atr, wp, aw, al, self.risk_per_trade)
        result['qty'] = scale_by_vix(result['qty'], vix)
        return result

    def record_trade(self, strategy: str, pnl: float):
        """Record outcome for adaptive Kelly learning."""
        with self._lock:
            lst = self._history.setdefault(strategy, [])
            lst.append(pnl)
            if len(lst) > 200:
                lst.pop(0)

    def update_capital(self, new_capital: float):
        with self._lock:
            self.capital = max(new_capital, 0)

    def get_strategy_stats(self, strategy: str) -> Dict:
        with self._lock:
            hist = list(self._history.get(strategy, []))
        if not hist:
            return {'trades': 0, 'win_rate': 0, 'kelly_pct': 0}
        wins  = [h for h in hist if h > 0]
        loses = [h for h in hist if h < 0]
        wp    = len(wins) / len(hist)
        aw    = sum(abs(w) for w in wins)  / max(len(wins),  1)
        al    = sum(abs(l) for l in loses) / max(len(loses), 1)
        kf    = kelly_fraction(wp, aw / 1000, al / 1000, 0.5)
        return {
            'trades':     len(hist),
            'win_rate':   round(wp, 3),
            'avg_win':    round(aw, 2),
            'avg_loss':   round(al, 2),
            'kelly_pct':  round(kf * 100, 2),
        }
