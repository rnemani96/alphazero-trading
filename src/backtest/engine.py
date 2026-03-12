"""
src/backtest/engine.py  —  AlphaZero Capital
════════════════════════════════════════════
Phase 7: Backtesting Engine

Runs after market close to:
  1. Fetch historical data for all symbols
  2. Apply all TITAN strategies
  3. Evaluate performance: win rate, Sharpe, drawdown, profit factor
  4. Rank strategies
  5. Write results to logs/backtest_results.json

Usage (scheduled by main.py post-market tasks):
    from src.backtest.engine import BacktestEngine
    engine = BacktestEngine()
    results = engine.run(symbols=['TCS','RELIANCE'], start='2024-01-01', end='2024-12-31')

Or from CLI:
    python -m src.backtest.engine
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np

logger = logging.getLogger("Backtest")

_ROOT       = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOG_DIR    = os.path.join(_ROOT, 'logs')
_RESULT_FILE = os.path.join(_LOG_DIR, 'backtest_results.json')
os.makedirs(_LOG_DIR, exist_ok=True)


# ── Strategy functions ────────────────────────────────────────────────────────

def _ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()

def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(n).mean()
    loss  = (-delta.clip(upper=0)).rolling(n).mean()
    rs    = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([high - low,
                    (high - close.shift()).abs(),
                    (low  - close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


# ── StrategyBase ──────────────────────────────────────────────────────────────

class StrategyBase:
    name: str = "Base"

    def generate(self, df: pd.DataFrame) -> pd.Series:
        """Return a Series of +1/0/-1 signals indexed like df."""
        raise NotImplementedError


class EMAcrossStrategy(StrategyBase):
    name = "EMA_Cross_20_50"

    def generate(self, df: pd.DataFrame) -> pd.Series:
        ema20 = _ema(df['close'], 20)
        ema50 = _ema(df['close'], 50)
        sig   = pd.Series(0, index=df.index)
        sig[(ema20 > ema50) & (ema20.shift() <= ema50.shift())] =  1
        sig[(ema20 < ema50) & (ema20.shift() >= ema50.shift())] = -1
        return sig


class RSIStrategy(StrategyBase):
    name = "RSI_Reversal"

    def generate(self, df: pd.DataFrame) -> pd.Series:
        rsi = _rsi(df['close'])
        sig = pd.Series(0, index=df.index)
        sig[rsi < 30] =  1
        sig[rsi > 70] = -1
        return sig


class VWAPStrategy(StrategyBase):
    name = "VWAP_Cross"

    def generate(self, df: pd.DataFrame) -> pd.Series:
        cum_vol  = (df.get('volume', pd.Series(1, index=df.index)) * df['close']).cumsum()
        cum_base = df.get('volume', pd.Series(1, index=df.index)).cumsum()
        vwap     = cum_vol / (cum_base + 1e-9)
        sig      = pd.Series(0, index=df.index)
        sig[df['close'] > vwap * 1.005] =  1
        sig[df['close'] < vwap * 0.995] = -1
        return sig


class BBounceStrategy(StrategyBase):
    name = "BB_Bounce"

    def generate(self, df: pd.DataFrame) -> pd.Series:
        mid   = df['close'].rolling(20).mean()
        std   = df['close'].rolling(20).std()
        upper = mid + 2 * std
        lower = mid - 2 * std
        sig   = pd.Series(0, index=df.index)
        sig[df['close'] < lower] =  1
        sig[df['close'] > upper] = -1
        return sig


class MACDStrategy(StrategyBase):
    name = "MACD_Momentum"

    def generate(self, df: pd.DataFrame) -> pd.Series:
        ema12 = _ema(df['close'], 12)
        ema26 = _ema(df['close'], 26)
        macd  = ema12 - ema26
        sig_  = _ema(macd, 9)
        hist  = macd - sig_
        sig   = pd.Series(0, index=df.index)
        sig[(hist > 0) & (hist.shift() <= 0)] =  1
        sig[(hist < 0) & (hist.shift() >= 0)] = -1
        return sig


# ── BacktestEngine ────────────────────────────────────────────────────────────

class BacktestEngine:
    """
    Phase 7 — backtesting engine.

    Fetches historical data, runs all strategies, evaluates metrics.
    """

    STRATEGIES = [
        EMAcrossStrategy(),
        RSIStrategy(),
        VWAPStrategy(),
        BBounceStrategy(),
        MACDStrategy(),
    ]

    def __init__(self, initial_capital: float = 1_000_000.0, commission: float = 0.0005):
        self.initial_capital = initial_capital
        self.commission      = commission      # 0.05% per trade

    def run(
        self,
        symbols:   Optional[List[str]] = None,
        start:     Optional[str] = None,
        end:       Optional[str] = None,
        interval:  str = '1d',
    ) -> Dict[str, Any]:
        """
        Run full backtest. Returns dict of strategy results.

        Args:
            symbols:  list of NSE symbols (defaults to NIFTY 10)
            start:    start date YYYY-MM-DD (defaults to 1 year ago)
            end:      end date YYYY-MM-DD (defaults to today)
            interval: '1d' | '1h' | '15m'
        """
        symbols = symbols or [
            'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
            'SBIN', 'WIPRO', 'TATAMOTORS', 'SUNPHARMA', 'MARUTI',
        ]
        end_dt   = datetime.now()
        start_dt = end_dt - timedelta(days=365)
        start    = start or start_dt.strftime('%Y-%m-%d')
        end      = end   or end_dt.strftime('%Y-%m-%d')

        logger.info("Backtest: %d symbols | %s → %s | interval=%s", len(symbols), start, end, interval)

        data_map = self._load_data(symbols, start, end, interval)
        if not data_map:
            logger.warning("Backtest: no data loaded")
            return {}

        results: Dict[str, Any] = {}
        for strategy in self.STRATEGIES:
            try:
                res = self._run_strategy(strategy, data_map)
                results[strategy.name] = res
                logger.info(
                    "  %s → WR=%.1f%% Sharpe=%.2f DD=%.1f%% PF=%.2f trades=%d",
                    strategy.name,
                    res['win_rate']     * 100,
                    res['sharpe'],
                    res['max_drawdown'] * 100,
                    res['profit_factor'],
                    res['total_trades'],
                )
            except Exception as e:
                logger.warning("Strategy %s error: %s", strategy.name, e)

        # Rank by profit factor
        ranked = sorted(
            [{'strategy': k, **v} for k, v in results.items()],
            key=lambda x: x.get('profit_factor', 0),
            reverse=True,
        )
        summary = {
            'run_at':     datetime.now().isoformat(),
            'start':      start,
            'end':        end,
            'symbols':    symbols,
            'interval':   interval,
            'strategies': results,
            'ranked':     ranked,
            'best':       ranked[0]['strategy'] if ranked else None,
            'worst':      ranked[-1]['strategy'] if ranked else None,
        }

        self._save(summary)
        logger.info("Backtest complete — best: %s | worst: %s", summary['best'], summary['worst'])
        return summary

    # ── Data loading ─────────────────────────────────────────────────────────

    def _load_data(self, symbols: List[str], start: str, end: str, interval: str) -> Dict[str, pd.DataFrame]:
        data_map: Dict[str, pd.DataFrame] = {}
        try:
            from src.data.fetch import DataFetcher
            fetcher = DataFetcher({})
            for sym in symbols:
                try:
                    df = fetcher.get_ohlcv(sym, interval=interval, start=start, end=end)
                    if df is not None and not df.empty:
                        data_map[sym] = df
                except Exception as e:
                    logger.debug("Data load %s: %s", sym, e)
        except Exception:
            # Fall back to yfinance direct
            try:
                import yfinance as yf
                for sym in symbols:
                    try:
                        df = yf.download(f"{sym}.NS", start=start, end=end,
                                         interval=interval, auto_adjust=True, progress=False)
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.get_level_values(0)
                        df.columns = [c.lower() for c in df.columns]
                        if not df.empty:
                            data_map[sym] = df
                    except Exception:
                        pass
            except ImportError:
                pass
        return data_map

    # ── Strategy evaluation ───────────────────────────────────────────────────

    def _run_strategy(
        self,
        strategy: StrategyBase,
        data_map: Dict[str, pd.DataFrame],
    ) -> Dict[str, Any]:
        """Simulate strategy across all symbols and aggregate metrics."""
        all_returns: List[float] = []
        total_trades = wins = losses = 0
        gross_profit = gross_loss = 0.0

        for sym, df in data_map.items():
            if len(df) < 50:
                continue
            try:
                sigs   = strategy.generate(df)
                rets   = self._simulate(df, sigs)
                all_returns.extend(rets)
                for r in rets:
                    total_trades += 1
                    if r > 0:
                        wins         += 1
                        gross_profit += r
                    else:
                        losses       += 1
                        gross_loss   += abs(r)
            except Exception as e:
                logger.debug("Strategy %s / %s error: %s", strategy.name, sym, e)

        if total_trades == 0:
            return self._empty_result()

        win_rate      = wins / total_trades
        profit_factor = gross_profit / max(gross_loss, 1e-9)
        sharpe        = self._sharpe(all_returns)
        max_dd        = self._max_drawdown(all_returns)

        return {
            'win_rate':      round(win_rate,      4),
            'profit_factor': round(profit_factor, 3),
            'sharpe':        round(sharpe,        3),
            'max_drawdown':  round(max_dd,        4),
            'total_trades':  total_trades,
            'wins':          wins,
            'losses':        losses,
            'gross_profit':  round(gross_profit,  2),
            'gross_loss':    round(gross_loss,    2),
            'total_return':  round(sum(all_returns), 4),
        }

    def _simulate(self, df: pd.DataFrame, signals: pd.Series) -> List[float]:
        """Simple long-only simulation with ATR stop and 3:1 RR."""
        returns = []
        atr_vals = _atr(df).fillna(0)
        close    = df['close']
        in_trade = False
        entry_price = stop = target = 0.0

        for i in range(len(df)):
            c   = float(close.iloc[i])
            atr = float(atr_vals.iloc[i])
            sig = int(signals.iloc[i])

            if in_trade:
                if c <= stop or c >= target:
                    pnl = (c - entry_price) / entry_price - self.commission * 2
                    returns.append(round(pnl, 6))
                    in_trade = False

            if not in_trade and sig == 1 and atr > 0:
                entry_price = c
                stop        = c - 2.0 * atr
                target      = c + 3.0 * atr
                in_trade    = True

        return returns

    @staticmethod
    def _sharpe(returns: List[float], risk_free: float = 0.0) -> float:
        if len(returns) < 5:
            return 0.0
        arr  = np.array(returns, dtype=float)
        std  = arr.std()
        mean = arr.mean() - risk_free
        return float(mean / std * (252 ** 0.5)) if std > 1e-9 else 0.0

    @staticmethod
    def _max_drawdown(returns: List[float]) -> float:
        equity = peak = max_dd = 0.0
        for r in returns:
            equity += r
            if equity > peak:
                peak = equity
            dd = (peak - equity) / max(abs(peak), 1e-9)
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        return {k: 0 for k in ['win_rate', 'profit_factor', 'sharpe',
                                 'max_drawdown', 'total_trades', 'wins',
                                 'losses', 'gross_profit', 'gross_loss', 'total_return']}

    def _save(self, summary: Dict[str, Any]):
        try:
            with open(_RESULT_FILE + '.tmp', 'w') as f:
                json.dump(summary, f, indent=2, default=str)
            os.replace(_RESULT_FILE + '.tmp', _RESULT_FILE)
            logger.info("Backtest results saved → %s", _RESULT_FILE)
        except Exception as e:
            logger.warning("Could not save backtest results: %s", e)


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')

    symbols = sys.argv[1:] if len(sys.argv) > 1 else None
    engine  = BacktestEngine()
    results = engine.run(symbols=symbols)

    print("\n" + "=" * 60)
    print(" BACKTEST RESULTS ")
    print("=" * 60)
    for rank, r in enumerate(results.get('ranked', []), 1):
        print(
            f"  #{rank:2d}  {r['strategy']:30}  "
            f"WR={r['win_rate']*100:.1f}%  "
            f"PF={r['profit_factor']:.2f}  "
            f"Sharpe={r['sharpe']:.2f}  "
            f"MaxDD={r['max_drawdown']*100:.1f}%  "
            f"Trades={r['total_trades']}"
        )
    print("=" * 60)
