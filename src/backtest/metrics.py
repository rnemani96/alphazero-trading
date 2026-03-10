"""
Performance Metrics for AlphaZero Backtesting
src/backtest/metrics.py

Calculates standard trading KPIs from equity curves and trade lists.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any

def calculate_metrics(returns: pd.Series, risk_free_rate: float = 0.05) -> Dict[str, Any]:
    """
    Calculate KPIs from a series of daily returns.
    """
    if returns.empty:
        return {}

    # Annualization factor (assuming 252 trading days)
    ann_factor = 252

    # Cumulative Return
    cum_ret = (1 + returns).prod() - 1

    # Annualized Return (CAGR)
    days = len(returns)
    cagr = (1 + cum_ret) ** (ann_factor / days) - 1 if days > 0 else 0

    # Annualized Volatility
    vol = returns.std() * np.sqrt(ann_factor)

    # Sharpe Ratio
    excess_ret = returns.mean() * ann_factor - risk_free_rate
    sharpe = excess_ret / vol if vol > 0 else 0

    # Sortino Ratio (Downside deviation)
    downside_returns = returns[returns < 0]
    downside_vol = downside_returns.std() * np.sqrt(ann_factor)
    sortino = excess_ret / downside_vol if downside_vol > 0 else 0

    # Max Drawdown
    cum_equity = (1 + returns).cumprod()
    running_max = cum_equity.cummax()
    drawdown = (cum_equity - running_max) / running_max
    max_dd = drawdown.min()

    # Recovery Factor
    recovery_factor = abs(cum_ret / max_dd) if max_dd != 0 else 0

    return {
        "cumulative_return": round(float(cum_ret), 4),
        "cagr":              round(float(cagr), 4),
        "volatility":        round(float(vol), 4),
        "sharpe":            round(float(sharpe), 2),
        "sortino":           round(float(sortino), 2),
        "max_drawdown":      round(float(max_dd), 4),
        "recovery_factor":   round(float(recovery_factor), 2),
    }

def calculate_trade_metrics(trades: List[Dict]) -> Dict[str, Any]:
    """
    Calculate statistics from a list of closed trades.
    Each trade should have: 'pnl_pct', 'pnl_val', 'duration' (days).
    """
    if not trades:
        return {}

    df = pd.DataFrame(trades)
    
    wins = df[df['pnl_val'] > 0]
    losses = df[df['pnl_val'] <= 0]
    
    win_rate = len(wins) / len(df)
    
    avg_win = wins['pnl_pct'].mean() if not wins.empty else 0
    avg_loss = losses['pnl_pct'].mean() if not losses.empty else 0
    
    profit_factor = abs(wins['pnl_val'].sum() / losses['pnl_val'].sum()) if not losses.empty and losses['pnl_val'].sum() != 0 else float('inf')
    
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
    
    return {
        "total_trades":   len(df),
        "win_rate":       round(float(win_rate), 4),
        "avg_win_pct":    round(float(avg_win), 4),
        "avg_loss_pct":   round(float(avg_loss), 4),
        "profit_factor":  round(float(profit_factor), 2),
        "expectancy":     round(float(expectancy), 4),
        "avg_duration":   round(float(df['duration'].mean()), 1) if 'duration' in df.columns else 0,
    }
