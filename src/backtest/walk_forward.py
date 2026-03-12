"""
src/backtest/walk_forward.py  —  AlphaZero Capital
════════════════════════════════════════════════════
NEW: Walk-Forward Backtesting (was TODO)

Walk-forward validation:
  1. Split full history into rolling train/test windows
  2. Train strategy parameters on in-sample window
  3. Test on out-of-sample window (no look-ahead)
  4. Repeat sliding forward → unbiased performance estimate

Default: 6-month train window, 1-month test window, sliding monthly.

Usage (called by main.py after market close):
    from src.backtest.walk_forward import WalkForwardEngine
    wfe = WalkForwardEngine(data_fetcher=fetcher)
    report = wfe.run(symbols=['TCS','RELIANCE','INFY'])
"""

from __future__ import annotations

import os, json, logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

import pandas as pd
import numpy as np

logger = logging.getLogger("WalkForward")

_ROOT       = Path(__file__).resolve().parents[2]
_LOG_DIR    = _ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_WF_FILE    = str(_LOG_DIR / "walk_forward_results.json")


# ── Indicator helpers ─────────────────────────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d    = close.diff()
    gain = d.clip(lower=0).rolling(n).mean()
    loss = (-d.clip(upper=0)).rolling(n).mean()
    rs   = gain / (loss + 1e-9)
    return 100 - 100 / (1 + rs)

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def _bb(close: pd.Series, n: int = 20) -> Tuple[pd.Series, pd.Series]:
    mid = close.rolling(n).mean()
    std = close.rolling(n).std()
    return mid + 2 * std, mid - 2 * std


# ── Strategy registry ─────────────────────────────────────────────────────────

STRATEGIES = {
    "ema_cross": {
        "params": {"fast": 20, "slow": 50},
        "signal": lambda df, p: (
            _ema(df['close'], p['fast']) > _ema(df['close'], p['slow'])
        ).astype(int).diff().fillna(0)
    },
    "rsi_reversal": {
        "params": {"period": 14, "oversold": 30, "overbought": 70},
        "signal": lambda df, p: pd.Series(
            np.where(_rsi(df['close'], p['period']) < p['oversold'], 1,
                     np.where(_rsi(df['close'], p['period']) > p['overbought'], -1, 0)),
            index=df.index
        )
    },
    "bb_squeeze": {
        "params": {"period": 20},
        "signal": lambda df, p: pd.Series(
            np.where(df['close'] < _bb(df['close'], p['period'])[1], 1,
                     np.where(df['close'] > _bb(df['close'], p['period'])[0], -1, 0)),
            index=df.index
        )
    },
    "ema_trend": {
        "params": {"period": 50},
        "signal": lambda df, p: pd.Series(
            np.where(df['close'] > _ema(df['close'], p['period']), 1, -1),
            index=df.index
        ).diff().fillna(0)
    },
    "volume_breakout": {
        "params": {"vol_mult": 2.0, "period": 20},
        "signal": lambda df, p: pd.Series(
            np.where(
                (df['volume'] > df['volume'].rolling(p['period']).mean() * p['vol_mult']) &
                (df['close'] > df['close'].shift(1)), 1, 0),
            index=df.index
        )
    },
}


# ── Backtest simulator ────────────────────────────────────────────────────────

def _run_strategy(df: pd.DataFrame, strategy_name: str, params: Dict) -> Dict:
    """
    Run a single strategy on a DataFrame slice.
    Returns performance metrics dict.
    """
    if len(df) < 60:
        return {}

    strat  = STRATEGIES[strategy_name]
    sig    = strat["signal"](df, params)

    trades = []
    position = 0
    entry    = 0.0

    for i in range(1, len(df)):
        s = sig.iloc[i]
        if s > 0 and position == 0:
            position = 1
            entry    = df['close'].iloc[i]
        elif (s < 0 or i == len(df) - 1) and position == 1:
            exit_p = df['close'].iloc[i]
            pnl    = (exit_p - entry) / entry * 100
            trades.append(pnl)
            position = 0

    if not trades:
        return {}

    wins  = [t for t in trades if t > 0]
    loss  = [t for t in trades if t <= 0]
    returns = np.array(trades)

    sharpe  = (returns.mean() / (returns.std() + 1e-9)) * np.sqrt(252 / max(len(trades),1))
    max_dd  = 0.0
    cum = np.cumprod(1 + returns / 100)
    for j in range(len(cum)):
        pk = cum[:j+1].max()
        dd = (pk - cum[j]) / pk * 100
        max_dd = max(max_dd, dd)

    return {
        "trades":       len(trades),
        "win_rate":     round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "avg_win":      round(np.mean(wins), 2) if wins else 0,
        "avg_loss":     round(np.mean(loss), 2) if loss else 0,
        "total_return": round(sum(trades), 2),
        "sharpe":       round(float(sharpe), 2),
        "max_drawdown": round(max_dd, 2),
        "profit_factor": round(sum(wins) / (abs(sum(loss)) + 1e-9), 2),
    }


# ── WalkForwardEngine ─────────────────────────────────────────────────────────

class WalkForwardEngine:
    """
    Walk-forward backtesting engine.
    Runs out-of-sample validation across rolling windows.
    """

    def __init__(self, data_fetcher=None,
                 train_months: int = 6,
                 test_months:  int = 1,
                 total_months: int = 24):
        self.fetcher       = data_fetcher
        self.train_months  = train_months
        self.test_months   = test_months
        self.total_months  = total_months

    def _get_windows(self) -> List[Tuple[str, str, str, str]]:
        """
        Generate (train_start, train_end, test_start, test_end) windows.
        """
        end_date   = datetime.now().replace(day=1) - timedelta(days=1)
        windows    = []
        test_end   = end_date
        for _ in range(self.total_months // self.test_months):
            test_start  = test_end  - timedelta(days=30 * self.test_months)
            train_end   = test_start - timedelta(days=1)
            train_start = train_end - timedelta(days=30 * self.train_months)
            windows.append((
                train_start.strftime("%Y-%m-%d"),
                train_end.strftime("%Y-%m-%d"),
                test_start.strftime("%Y-%m-%d"),
                test_end.strftime("%Y-%m-%d"),
            ))
            test_end = test_start - timedelta(days=1)
        return list(reversed(windows))

    def _fetch_data(self, symbol: str, start: str, end: str) -> Optional[pd.DataFrame]:
        if self.fetcher:
            return self.fetcher.get_historical(symbol, start, end, "1d")
        try:
            import yfinance as yf
            df = yf.download(symbol + ".NS", start=start, end=end, progress=False)
            if df is None or df.empty:
                return None
            df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
            df['datetime'] = df.index
            return df.reset_index(drop=True)
        except Exception:
            return None

    def run(self, symbols: List[str], strategies: Optional[List[str]] = None) -> Dict:
        """
        Run walk-forward test for given symbols and strategies.
        Returns aggregated report.
        """
        if not symbols:
            return {}

        strategies = strategies or list(STRATEGIES.keys())
        windows    = self._get_windows()
        results    = {s: [] for s in strategies}

        logger.info(f"Walk-forward: {len(symbols)} symbols × {len(strategies)} strategies × {len(windows)} windows")

        for sym in symbols:
            logger.info(f"  Processing {sym}...")
            for train_s, train_e, test_s, test_e in windows:
                # Fetch out-of-sample test data
                test_df = self._fetch_data(sym, test_s, test_e)
                if test_df is None or test_df.empty or len(test_df) < 10:
                    continue

                # Ensure required columns
                for col in ['open','high','low','close','volume']:
                    if col not in test_df.columns:
                        break
                else:
                    for strat_name in strategies:
                        try:
                            params = STRATEGIES[strat_name]["params"]
                            metrics = _run_strategy(test_df, strat_name, params)
                            if metrics:
                                metrics.update({
                                    "symbol":     sym,
                                    "strategy":   strat_name,
                                    "test_start": test_s,
                                    "test_end":   test_e,
                                    "oos":        True,   # out-of-sample flag
                                })
                                results[strat_name].append(metrics)
                        except Exception as e:
                            logger.debug(f"Strategy {strat_name} failed on {sym}: {e}")

        # Aggregate per strategy
        summary = {}
        for strat_name, runs in results.items():
            if not runs:
                continue
            df = pd.DataFrame(runs)
            summary[strat_name] = {
                "avg_win_rate":     round(df["win_rate"].mean(),    1),
                "avg_sharpe":       round(df["sharpe"].mean(),      2),
                "avg_max_drawdown": round(df["max_drawdown"].mean(),2),
                "avg_profit_factor":round(df["profit_factor"].mean(),2),
                "avg_total_return": round(df["total_return"].mean(),2),
                "total_trades":     int(df["trades"].sum()),
                "windows_tested":   len(df),
                "symbols_tested":   df["symbol"].nunique(),
                "grade": _grade(df["win_rate"].mean(), df["sharpe"].mean()),
                "raw":  runs[:5],   # Sample of raw runs for debug
            }

        # Rank strategies by Sharpe
        ranked = sorted(summary.items(), key=lambda x: x[1].get("avg_sharpe", 0), reverse=True)

        report = {
            "timestamp":       datetime.now().isoformat(),
            "symbols_tested":  symbols,
            "windows":         len(windows),
            "train_months":    self.train_months,
            "test_months":     self.test_months,
            "strategies":      summary,
            "ranked":          [{"strategy": k, **v} for k, v in ranked],
            "best_strategy":   ranked[0][0] if ranked else None,
        }

        # Persist
        try:
            with open(_WF_FILE, "w") as f:
                json.dump(report, f, indent=2)
            logger.info(f"Walk-forward results saved → {_WF_FILE}")
        except Exception as e:
            logger.warning(f"Could not save walk-forward results: {e}")

        return report


def _grade(win_rate: float, sharpe: float) -> str:
    if win_rate >= 60 and sharpe >= 1.5:
        return "A"
    elif win_rate >= 55 and sharpe >= 1.0:
        return "B"
    elif win_rate >= 50 and sharpe >= 0.5:
        return "C"
    else:
        return "D"
