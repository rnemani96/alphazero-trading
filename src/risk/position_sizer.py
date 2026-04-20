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
from .charge_calculator import calculate_charges, get_minimum_viable_quantity

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
    regime:       str   = "TRENDING",
    confidence:   float = 0.5,
    is_intraday:  bool  = False,
) -> Dict:
    """
    Combined: take the more conservative of Kelly and ATR sizing.
    Scales risk_pct based on confidence (0.5=norm, 0.9=2x).
    Now integrates Charge-Aware sizing (User Requirement).
    """
    # Dynamic Risk Scaling from 0.5% (low conf) to 2.0% (max conf)
    effective_risk = risk_pct * (confidence * 2.0)
    effective_risk = max(0.005, min(0.02, effective_risk))
    
    kqty = kelly_size(capital, entry_price, win_prob, avg_win_pct, avg_loss_pct)
    aqty = atr_size(capital, entry_price, atr, effective_risk)
    qty  = min(kqty, aqty) if (kqty > 0 and aqty > 0) else max(kqty, aqty)
    qty  = max(1, qty)
    
    # Tighten Stop Losses in SIDEWAYS to 2x ATR (was 3x) to cut losers faster.
    sl_mult  = 2.0 if regime == "SIDEWAYS" else 1.5
    tgt_mult = 4.0 if regime == "SIDEWAYS" else 3.0

    sl   = round(entry_price - sl_mult * atr, 2) if atr > 0 else round(entry_price * (0.97 if regime == "SIDEWAYS" else 0.975), 2)
    tgt  = round(entry_price + tgt_mult * atr, 2) if atr > 0 else round(entry_price * (1.05 if regime == "SIDEWAYS" else 1.06), 2)

    # ── Charge-Aware Floor Logic & Dynamic Slippage ──────────────────────────
    # User Requirement: Instead of blocking small trades, INCREASE quantity
    # to ensure charges don't flush away the profits.
    
    # 1. Dynamic Slippage Modeling
    # Estimate slippage based on stock volatility (ATR / Price).
    # Volatile stocks get 0.1% slippage penalty; standard get 0.05%.
    volatility_pct = (atr / entry_price) if entry_price > 0 else 0
    slippage_pct = 0.001 if volatility_pct > 0.02 else 0.0005
    
    # Adjust target price down to account for exit slippage
    # and entry price up to account for entry slippage for viability checks
    effective_entry = entry_price * (1 + slippage_pct)
    effective_tgt = tgt * (1 - slippage_pct)

    min_qty = get_minimum_viable_quantity(effective_entry, effective_tgt, is_intraday)
    
    if qty < min_qty:
        # Increase marginally to min_qty to ensure viability
        # We allow a slightly higher risk cap (3% vs 2%) for this 'viability boost'
        test_risk_pct = (abs(entry_price - sl) * min_qty / capital)
        if test_risk_pct <= 0.03: 
            logger.info(f"⚡ VIABILITY BOOST: Increasing {sym if 'sym' in locals() else 'trade'} qty from {qty} to {min_qty} to cover charges (Risk: {test_risk_pct*100:.1f}%)")
            qty = min_qty
        else:
            # Even if it exceeds 3% risk, we still try to take the trade with min_qty 
            # if the user has enough capital, but we log a warning.
            if min_qty * entry_price <= capital * 0.10: # Max 10% of total capital in one stock
                logger.warning(f"⚠️ HIGH RISK VIABILITY: Forcing {min_qty} shares to cover charges. Risk: {test_risk_pct*100:.1f}%")
                qty = min_qty
            else:
                # Absolute last resort: if we can't even afford 10% capital, then it's truly unviable
                qty = 0

    # Sanity check: if qty is 0, return zeroed result
    if qty == 0:
        return {
            'qty': 0, 'kelly_qty': kqty, 'atr_qty': aqty, 
            'capital_used': 0, 'stop_loss': sl, 'target': tgt, 
            'risk_amount': 0, 'risk_pct': 0, 'expected_charges': 0, 'expected_net_pnl': 0
        }

    # Final Charge Calculation for Metadata
    fees = calculate_charges(qty, entry_price, tgt, is_intraday)

    return {
        'qty':          qty,
        'kelly_qty':    kqty,
        'atr_qty':      aqty,
        'capital_used': round(qty * entry_price, 2),
        'stop_loss':    sl,
        'target':       tgt,
        'risk_amount':  round(abs(entry_price - sl) * qty, 2),
        'risk_pct':     round((abs(entry_price - sl) * qty / capital) * 100, 2) if capital > 0 else 0,
        'expected_charges': fees['total'],
        'expected_net_pnl': fees['net_pnl'],
        'break_even':       fees['break_even']
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
        macro_status: str = "LIVE",
        regime:       str = "TRENDING",
        confidence:   float = 0.5,
        is_intraday:  bool  = False,
    ) -> Dict:
        """
        Compute position size for a strategy.
        Uses historical win-rate if enough data (≥15 trades), else default.
        Now scales by 'confidence' score for High-Conviction setups.
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

        # Boost wp/aw slightly for ultra-high confidence signals (>0.9)
        if confidence > 0.9:
            wp = min(0.70, wp + 0.05)
            
        # Detect intraday if not explicitly passed
        if not is_intraday:
            is_intraday = strategy.upper().startswith("INTRADAY") or strategy.upper().find("SCALP") >= 0

        result       = optimal_size(self.capital, entry_price, atr, wp, aw, al, self.risk_per_trade, regime, confidence, is_intraday)
        result['qty'] = scale_by_vix(result['qty'], vix)
        
        # Apply Macro Reliability discounts
        if macro_status == "FFILL":
            result['qty'] = max(1, int(result['qty'] * 0.8)) # 20% reduction
            logger.info(f"PositionSizer: Applied 20% discount due to macro_status=FFILL")
        elif macro_status == "MISSING":
            result['qty'] = max(1, int(result['qty'] * 0.6)) # 40% reduction
            logger.info(f"PositionSizer: Applied 40% discount due to macro_status=MISSING")
            
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
