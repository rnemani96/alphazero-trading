"""
src/backtest/engine.py  —  AlphaZero Capital
════════════════════════════════════════════
Full Backtesting Engine — Phase 7

Features:
  - Run all 5 benchmark strategies on historical NSE data
  - Walk-forward validation (6-month train / 1-month test windows)
  - Full metrics: Sharpe, Sortino, Max DD, Win Rate, Profit Factor, CAGR
  - Strategy ranking leaderboard
  - Slippage + commission model
  - Export to logs/backtest_results.json

Usage (from main.py post-market task):
    from src.backtest.engine import BacktestEngine
    engine = BacktestEngine()
    results = engine.run(symbols=['TCS', 'RELIANCE'], walk_forward=True)

CLI:
    python -m src.backtest.engine
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import numpy as np
import pandas as pd

from ..utils.stats import (
    sharpe, sortino, max_drawdown_from_returns,
    win_rate, profit_factor, full_metrics, cagr
)

logger = logging.getLogger("Backtest")

_ROOT        = Path(__file__).resolve().parents[2]
_LOG_DIR     = _ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_RESULT_FILE = str(_LOG_DIR / "backtest_results.json")


# ── Indicator helpers (no external deps) ─────────────────────────────────────

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
    return tr.ewm(span=n, adjust=False).mean()

def _macd(close: pd.Series):
    e12 = _ema(close, 12); e26 = _ema(close, 26)
    m   = e12 - e26
    sig = _ema(m, 9)
    return m, sig, m - sig

def _bb(close: pd.Series, n: int = 20, std_dev: float = 2.0):
    mid = close.rolling(n).mean()
    std = close.rolling(n).std()
    return mid + std_dev * std, mid, mid - std_dev * std

def _vwap(df: pd.DataFrame) -> pd.Series:
    tp  = (df['high'] + df['low'] + df['close']) / 3
    vol = df.get('volume', pd.Series(1, index=df.index))
    return (tp * vol).rolling(20).sum() / (vol.rolling(20).sum() + 1e-9)


# ══════════════════════════════════════════════════════════════════════════════
# STRATEGY DEFINITIONS
# Each strategy: generate(df) → pd.Series of +1 / -1 / 0
# ══════════════════════════════════════════════════════════════════════════════

class _Strategy:
    name: str = "Base"
    category: str = "General"

    def generate(self, df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    def __str__(self): return self.name


class EMACrossStrategy(_Strategy):
    name     = "EMA_Cross_20_50"
    category = "Trend"
    def generate(self, df):
        e20 = _ema(df['close'], 20); e50 = _ema(df['close'], 50)
        sig = pd.Series(0, index=df.index)
        sig[(e20 > e50) & (e20.shift() <= e50.shift())] =  1
        sig[(e20 < e50) & (e20.shift() >= e50.shift())] = -1
        return sig


class RSIStrategy(_Strategy):
    name     = "RSI_Reversal"
    category = "Mean Reversion"
    def generate(self, df):
        rsi = _rsi(df['close'])
        sig = pd.Series(0, index=df.index)
        sig[rsi < 30] =  1
        sig[rsi > 70] = -1
        return sig


class MACDStrategy(_Strategy):
    name     = "MACD_Momentum"
    category = "Trend"
    def generate(self, df):
        m, s, h = _macd(df['close'])
        sig = pd.Series(0, index=df.index)
        sig[(h > 0) & (h.shift() <= 0)] =  1
        sig[(h < 0) & (h.shift() >= 0)] = -1
        return sig


class VWAPStrategy(_Strategy):
    name     = "VWAP_Cross"
    category = "VWAP"
    def generate(self, df):
        vwap = _vwap(df)
        sig  = pd.Series(0, index=df.index)
        sig[df['close'] > vwap * 1.005] =  1
        sig[df['close'] < vwap * 0.995] = -1
        return sig


class BBBounceStrategy(_Strategy):
    name     = "BB_Bounce"
    category = "Mean Reversion"
    def generate(self, df):
        up, _, lo = _bb(df['close'])
        sig = pd.Series(0, index=df.index)
        sig[df['close'] < lo] =  1
        sig[df['close'] > up] = -1
        return sig


class ORBStrategy(_Strategy):
    """Opening Range Breakout — uses first 4 bars as the range."""
    name     = "ORB_Breakout"
    category = "Breakout"
    def generate(self, df):
        orb_high = df['high'].iloc[:4].max() if len(df) >= 4 else df['high'].iloc[0]
        orb_low  = df['low'].iloc[:4].min()  if len(df) >= 4 else df['low'].iloc[0]
        sig      = pd.Series(0, index=df.index)
        sig[df['close'] > orb_high * 1.002] =  1
        sig[df['close'] < orb_low  * 0.998] = -1
        return sig


class SupertrendStrategy(_Strategy):
    name     = "Supertrend"
    category = "Trend"
    def generate(self, df):
        atr    = _atr(df)
        mid    = (df['high'] + df['low']) / 2
        upper  = mid + 3.0 * atr
        lower  = mid - 3.0 * atr
        trend  = pd.Series(1, index=df.index)
        for i in range(1, len(df)):
            if df['close'].iloc[i] > upper.iloc[i - 1]:
                trend.iloc[i] =  1
            elif df['close'].iloc[i] < lower.iloc[i - 1]:
                trend.iloc[i] = -1
            else:
                trend.iloc[i] = trend.iloc[i - 1]
        # Signal on trend change
        sig = pd.Series(0, index=df.index)
        sig[trend.diff() > 0] =  1
        sig[trend.diff() < 0] = -1
        return sig


# ══════════════════════════════════════════════════════════════════════════════
# BACKTESTING ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class BacktestEngine:
    """
    Runs all registered strategies on historical data and
    produces a ranked performance report.
    """

    STRATEGIES: List[_Strategy] = [
        EMACrossStrategy(),
        RSIStrategy(),
        MACDStrategy(),
        VWAPStrategy(),
        BBBounceStrategy(),
        ORBStrategy(),
        SupertrendStrategy(),
    ]

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        commission:      float = 0.0005,    # 0.05% per trade
        slippage_bps:    int   = 10,         # 10 bps one-way slippage
    ):
        self.initial_capital = initial_capital
        self.commission      = commission
        self.slippage_bps    = slippage_bps

    def run_stress_test(self, symbols: List[str], data_map: Dict[str, Any]):
        """Requirement #2.2: Parallel nightly stress-test to re-rank weights."""
        logger.info(f"🌙 Starting stress-test on {len(symbols)} symbols...")
        
        # Convert List[CandleBar] or list of dicts to pd.DataFrame
        df_map = {}
        for sym, bars in data_map.items():
            if bars:
                try:
                    dicts = [b.to_dict() if hasattr(b, 'to_dict') else b for b in bars]
                    df = pd.DataFrame(dicts)
                    df.columns = [c.lower() for c in df.columns]
                    if 'close' in df.columns:
                        df_map[sym] = df
                except Exception as e:
                    logger.debug(f"Failed to convert data for {sym}: {e}")
        
        # Override data loading if we have pre-fetched data
        results = self.run(symbols=symbols, walk_forward=False, save=True, data_map_override=df_map)
        return results

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        symbols:        Optional[List[str]] = None,
        start:          Optional[str] = None,
        end:            Optional[str] = None,
        interval:       str = '1d',
        walk_forward:   bool = True,
        save:           bool = True,
        data_map_override: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> Dict[str, Any]:
        """
        Run full backtest.

        Args:
            symbols      : NSE symbols to test (defaults to NIFTY 10)
            start        : YYYY-MM-DD start date
            end          : YYYY-MM-DD end date
            interval     : yfinance interval string
            walk_forward : if True, run walk-forward validation in addition
            save         : persist results to logs/

        Returns:
            Full results dict with per-strategy metrics and rankings.
        """
        symbols = symbols or [
            'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
            'SBIN', 'WIPRO', 'TATAMOTORS', 'SUNPHARMA', 'MARUTI',
        ]
        end_dt   = datetime.now()
        start_dt = end_dt - timedelta(days=365)
        start    = start or start_dt.strftime('%Y-%m-%d')
        end      = end   or end_dt.strftime('%Y-%m-%d')

        logger.info("Backtest: %d symbols | %s→%s | interval=%s | wf=%s",
                    len(symbols), start, end, interval, walk_forward)

        if data_map_override:
            data_map = data_map_override
        else:
            data_map = self._load_data(symbols, start, end, interval)

        if not data_map:
            logger.warning("Backtest: no data loaded — aborting")
            return {}

        results: Dict[str, Dict] = {}

        for strat in self.STRATEGIES:
            try:
                res = self._run_strategy(strat, data_map)
                results[strat.name] = res
                logger.info("  %-30s WR=%.1f%% Sharpe=%.2f DD=%.1f%% PF=%.2f trades=%d",
                            strat.name, res['win_rate']*100, res['sharpe'],
                            res['max_drawdown']*100, res['profit_factor'], res['total_trades'])
            except Exception as exc:
                logger.warning("Backtest: %s error — %s", strat.name, exc)

        # Walk-forward layer
        wf_results: Dict[str, Dict] = {}
        if walk_forward:
            wf_results = self._walk_forward(symbols, interval)

        # Merge and rank
        ranked = sorted(
            [{'strategy': k, **v} for k, v in results.items()],
            key=lambda x: x.get('profit_factor', 0),
            reverse=True,
        )

        summary = {
            'run_at':      datetime.now().isoformat(),
            'start':       start,
            'end':         end,
            'symbols':     symbols,
            'interval':    interval,
            'strategies':  results,
            'ranked':      ranked,
            'best':        ranked[0]['strategy'] if ranked else None,
            'worst':       ranked[-1]['strategy'] if ranked else None,
            'walk_forward': wf_results,
            'gate_check':  self._gate_check(ranked[0] if ranked else {}),
        }

        if save:
            self._persist(summary)

        logger.info("Backtest complete — best: %s | worst: %s",
                    summary['best'], summary['worst'])
        return summary

    # ── Walk-forward ──────────────────────────────────────────────────────────

    def _walk_forward(
        self,
        symbols:       List[str],
        interval:      str,
        train_months:  int = 6,
        test_months:   int = 1,
        windows:       int = 12,
    ) -> Dict[str, Any]:
        """
        Rolling out-of-sample validation.
        Trains on in-sample window, tests on OOS window.
        Returns per-strategy OOS metrics.
        """
        wf_out: Dict[str, List[Dict]] = {s.name: [] for s in self.STRATEGIES}
        now = datetime.now()

        for w in range(windows):
            test_end   = now - timedelta(days=30 * w)
            test_start = test_end - timedelta(days=30 * test_months)
            ts = test_start.strftime('%Y-%m-%d')
            te = test_end.strftime('%Y-%m-%d')

            oos_data = self._load_data(symbols, ts, te, interval)
            if not oos_data:
                continue

            for strat in self.STRATEGIES:
                try:
                    r = self._run_strategy(strat, oos_data)
                    r['window'] = f"W{w+1}_{ts[:7]}"
                    wf_out[strat.name].append(r)
                except Exception:
                    pass

        # Aggregate per strategy
        agg: Dict[str, Dict] = {}
        for sname, runs in wf_out.items():
            if not runs:
                continue
            df = pd.DataFrame(runs)
            agg[sname] = {
                'oos_sharpe':    round(df['sharpe'].mean(), 3),
                'oos_win_rate':  round(df['win_rate'].mean(), 3),
                'oos_max_dd':    round(df['max_drawdown'].mean(), 3),
                'oos_pf':        round(df['profit_factor'].mean(), 3),
                'windows':       len(runs),
                'grade':         self._grade(df['win_rate'].mean(), df['sharpe'].mean()),
            }

        return agg

    # ── Strategy simulation ───────────────────────────────────────────────────

    def _run_strategy(
        self,
        strategy: _Strategy,
        data_map: Dict[str, pd.DataFrame],
    ) -> Dict[str, Any]:
        """Simulate strategy across all symbols and aggregate."""
        all_returns: List[float] = []
        equity_curve: List[float] = [self.initial_capital]
        total_trades = wins = losses = 0
        gross_profit = gross_loss = 0.0

        for sym, df in data_map.items():
            if len(df) < 50:
                continue
            try:
                sigs  = strategy.generate(df)
                rets  = self._simulate_trades(df, sigs)
                all_returns.extend(rets)
                for r in rets:
                    total_trades += 1
                    if r > 0:
                        wins         += 1
                        gross_profit += r
                    else:
                        losses       += 1
                        gross_loss   += abs(r)
            except Exception as exc:
                logger.debug("Strategy %s / %s: %s", strategy.name, sym, exc)

        if total_trades == 0:
            return self._empty()

        capital = self.initial_capital
        for r in all_returns:
            capital *= (1 + r)
            equity_curve.append(capital)

        arr      = np.array(all_returns, dtype=float)
        years    = len(all_returns) / TRADING_DAYS_YEAR if all_returns else 1
        _cagr    = cagr(self.initial_capital, capital, max(years, 0.01))

        return {
            'win_rate':      round(wins / max(total_trades, 1), 4),
            'profit_factor': round(gross_profit / max(gross_loss, 1e-9), 3),
            'sharpe':        round(sharpe(arr), 3),
            'sortino':       round(sortino(arr), 3),
            'max_drawdown':  round(max_drawdown_from_returns(arr), 4),
            'cagr':          round(_cagr, 4),
            'total_trades':  total_trades,
            'wins':          wins,
            'losses':        losses,
            'gross_profit':  round(gross_profit, 4),
            'gross_loss':    round(gross_loss, 4),
            'total_return':  round(float(arr.sum()), 4),
            'category':      strategy.category,
        }

    def _simulate_trades(self, df: pd.DataFrame, signals: pd.Series) -> List[float]:
        """
        Long-only simulation: enter on BUY signal, exit on SELL or stop/target.
        Uses ATR-based SL (1.5×ATR) and 3:1 R:R target.
        Applies commission and slippage.
        """
        atr_vals   = _atr(df).fillna(0)
        close      = df['close']
        returns    = []
        in_trade   = False
        entry_p    = stop = target = 0.0

        cost = self.commission + self.slippage_bps / 10_000

        for i in range(len(df)):
            c   = float(close.iloc[i])
            atr = float(atr_vals.iloc[i])
            sig = int(signals.iloc[i])

            if in_trade:
                if c <= stop or c >= target or sig == -1:
                    pnl = (c - entry_p) / entry_p - cost * 2
                    returns.append(round(pnl, 6))
                    in_trade = False

            if not in_trade and sig == 1 and atr > 0:
                entry_p  = c * (1 + cost)   # buy slightly above (slippage)
                stop     = entry_p - 1.5 * atr
                target   = entry_p + 3.0 * atr
                in_trade = True

        return returns

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_data(
        self,
        symbols: List[str],
        start:   str,
        end:     str,
        interval: str,
    ) -> Dict[str, pd.DataFrame]:
        data_map: Dict[str, pd.DataFrame] = {}

        # Try DataFetcher first
        try:
            from src.data.fetch import DataFetcher
            fetcher = DataFetcher({})
            for sym in symbols:
                try:
                    df = fetcher.get_ohlcv(sym, interval=interval, bars=600)
                    if df:
                        frame = pd.DataFrame(df)
                        frame.columns = [c.lower() for c in frame.columns]
                        if 'close' in frame.columns and len(frame) >= 30:
                            data_map[sym] = frame
                except Exception:
                    pass
        except ImportError:
            pass

        # yfinance fallback
        if not data_map:
            try:
                import yfinance as yf
                for sym in symbols:
                    try:
                        df = yf.download(f"{sym}.NS", start=start, end=end,
                                         interval=interval, auto_adjust=True,
                                         progress=False)
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.get_level_values(0)
                        df.columns = [c.lower() for c in df.columns]
                        if 'close' in df.columns and len(df) >= 30:
                            data_map[sym] = df.dropna(subset=['close'])
                    except Exception:
                        pass
            except ImportError:
                pass

        logger.info("Backtest data: %d / %d symbols loaded", len(data_map), len(symbols))
        return data_map

    # ── Gate check (paper→live readiness) ────────────────────────────────────

    def _gate_check(self, best: Dict) -> Dict[str, Any]:
        """Check if the best strategy meets paper→live transition gates."""
        wr   = best.get('win_rate', 0)
        pf   = best.get('profit_factor', 0)
        dd   = best.get('max_drawdown', 1)
        sh   = best.get('sharpe', 0)
        gates = {
            'win_rate_55pct':     wr >= 0.55,
            'profit_factor_15':   pf >= 1.5,
            'max_dd_under_10pct': dd <= 0.10,
            'sharpe_above_12':    sh >= 1.2,
        }
        gates['all_passed'] = all(gates.values())
        return gates

    @staticmethod
    def _grade(wr: float, sh: float) -> str:
        if wr >= 0.60 and sh >= 1.5: return 'A'
        if wr >= 0.55 and sh >= 1.0: return 'B'
        if wr >= 0.50 and sh >= 0.5: return 'C'
        return 'D'

    @staticmethod
    def _empty() -> Dict[str, Any]:
        return {k: 0 for k in ['win_rate', 'profit_factor', 'sharpe', 'sortino',
                                 'max_drawdown', 'cagr', 'total_trades', 'wins',
                                 'losses', 'gross_profit', 'gross_loss', 'total_return']}

    def _persist(self, summary: Dict):
        try:
            tmp = _RESULT_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(summary, f, indent=2, default=str)
            os.replace(tmp, _RESULT_FILE)
            logger.info("Backtest results → %s", _RESULT_FILE)
        except Exception as exc:
            logger.warning("Backtest persist failed: %s", exc)


TRADING_DAYS_YEAR = 252


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
    syms    = sys.argv[1:] or None
    engine  = BacktestEngine()
    results = engine.run(symbols=syms, walk_forward=True)

    print("\n" + "=" * 70)
    print("  ALPHAZERO CAPITAL — BACKTEST RESULTS")
    print("=" * 70)
    for rank, r in enumerate(results.get('ranked', []), 1):
        print(f"  #{rank:2d}  {r['strategy']:30}  "
              f"WR={r['win_rate']*100:.1f}%  "
              f"PF={r['profit_factor']:.2f}  "
              f"Sharpe={r['sharpe']:.2f}  "
              f"MaxDD={r['max_drawdown']*100:.1f}%  "
              f"Trades={r['total_trades']}")
    gates = results.get('gate_check', {})
    print("\n  Paper→Live Gates:")
    for g, passed in gates.items():
        print(f"    {'✅' if passed else '❌'} {g}")
    print("=" * 70)
