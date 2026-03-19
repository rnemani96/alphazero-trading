"""
src/utils/stats.py  —  AlphaZero Capital
══════════════════════════════════════════
Shared statistical utilities used by Backtest, LENS, KARMA, and Risk modules.

Single source of truth for:
  - Sharpe / Sortino ratio
  - Maximum drawdown
  - CAGR / annualised return
  - Profit factor
  - Kelly criterion
  - Win-rate rolling stats
"""

from __future__ import annotations
import math
from typing import List, Dict, Sequence, Optional
import numpy as np


# ── Constants ─────────────────────────────────────────────────────────────────
TRADING_DAYS_YEAR = 252
RISK_FREE_RATE    = 0.065   # Indian 10-yr G-Sec approximate


# ── Core metrics ──────────────────────────────────────────────────────────────

def sharpe(returns: Sequence[float],
           risk_free: float = RISK_FREE_RATE,
           ann_factor: int  = TRADING_DAYS_YEAR) -> float:
    """Annualised Sharpe ratio from a sequence of per-trade or daily returns."""
    arr = np.asarray(returns, dtype=float)
    if len(arr) < 2:
        return 0.0
    std = arr.std()
    if std < 1e-10:
        return 0.0
    excess = arr.mean() * ann_factor - risk_free
    return float(excess / (std * math.sqrt(ann_factor)))


def sortino(returns: Sequence[float],
            risk_free: float = RISK_FREE_RATE,
            ann_factor: int  = TRADING_DAYS_YEAR) -> float:
    """Sortino ratio — penalises only downside volatility."""
    arr  = np.asarray(returns, dtype=float)
    down = arr[arr < 0]
    if len(down) < 2:
        return 0.0
    dstd = down.std()
    if dstd < 1e-10:
        return 0.0
    excess = arr.mean() * ann_factor - risk_free
    return float(excess / (dstd * math.sqrt(ann_factor)))


def max_drawdown(equity_curve: Sequence[float]) -> float:
    """
    Maximum peak-to-trough drawdown as a positive fraction (0–1).
    equity_curve: cumulative equity values (not returns).
    """
    arr  = np.asarray(equity_curve, dtype=float)
    if len(arr) < 2:
        return 0.0
    peak = np.maximum.accumulate(arr)
    dd   = (peak - arr) / np.where(peak > 0, peak, 1)
    return float(dd.max())


def max_drawdown_from_returns(returns: Sequence[float]) -> float:
    """Convenience wrapper — builds equity curve from returns."""
    arr    = np.asarray(returns, dtype=float)
    equity = np.cumprod(1 + arr)
    return max_drawdown(equity)


def cagr(start_value: float, end_value: float, years: float) -> float:
    """Compound Annual Growth Rate."""
    if start_value <= 0 or end_value <= 0 or years <= 0:
        return 0.0
    return float((end_value / start_value) ** (1.0 / years) - 1)


def profit_factor(returns: Sequence[float]) -> float:
    """Gross profit / gross loss.  Returns inf if no losses."""
    arr    = np.asarray(returns, dtype=float)
    gross_win  = arr[arr > 0].sum()
    gross_loss = abs(arr[arr < 0].sum())
    if gross_loss < 1e-10:
        return float('inf')
    return float(gross_win / gross_loss)


def win_rate(returns: Sequence[float]) -> float:
    """Fraction of profitable trades."""
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        return 0.0
    return float((arr > 0).mean())


def expectancy(returns: Sequence[float]) -> float:
    """Average trade return (accounts for win-rate and avg sizes)."""
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        return 0.0
    return float(arr.mean())


# ── Kelly Criterion ───────────────────────────────────────────────────────────

def kelly_fraction(win_prob: float, avg_win_pct: float, avg_loss_pct: float,
                   fraction: float = 0.5) -> float:
    """
    Kelly fraction of capital to risk per trade.
    fraction=0.5 → half-Kelly (recommended for live trading).

    Returns value in [0, 0.25] — hard-capped to prevent ruin.
    """
    if avg_win_pct <= 0 or avg_loss_pct <= 0 or win_prob <= 0:
        return 0.0
    b   = avg_win_pct / avg_loss_pct   # win/loss ratio
    q   = 1 - win_prob
    f   = (win_prob * b - q) / b
    f   = max(0.0, f) * fraction
    return min(f, 0.25)                # cap at 25% of capital


# ── Batch metrics summary ─────────────────────────────────────────────────────

def full_metrics(returns: Sequence[float],
                 risk_free: float = RISK_FREE_RATE) -> Dict[str, float]:
    """
    Compute all key metrics in one call.
    returns: sequence of per-trade P&L as fraction of capital.
    """
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        return {k: 0.0 for k in ['sharpe', 'sortino', 'max_drawdown',
                                   'win_rate', 'profit_factor', 'expectancy',
                                   'total_return', 'trades']}
    return {
        'sharpe':        sharpe(arr, risk_free),
        'sortino':       sortino(arr, risk_free),
        'max_drawdown':  max_drawdown_from_returns(arr),
        'win_rate':      win_rate(arr),
        'profit_factor': profit_factor(arr),
        'expectancy':    expectancy(arr),
        'total_return':  float(arr.sum()),
        'avg_return':    float(arr.mean()),
        'std_return':    float(arr.std()),
        'trades':        len(arr),
    }


# ── Rolling window helpers ────────────────────────────────────────────────────

def rolling_sharpe(returns: Sequence[float], window: int = 20) -> List[float]:
    """Per-step rolling Sharpe over a sliding window."""
    arr    = np.asarray(returns, dtype=float)
    result = []
    for i in range(len(arr)):
        start = max(0, i - window + 1)
        chunk = arr[start: i + 1]
        result.append(sharpe(chunk))
    return result


def rolling_win_rate(returns: Sequence[float], window: int = 20) -> List[float]:
    arr    = np.asarray(returns, dtype=float)
    result = []
    for i in range(len(arr)):
        start = max(0, i - window + 1)
        chunk = arr[start: i + 1]
        result.append(win_rate(chunk))
    return result
