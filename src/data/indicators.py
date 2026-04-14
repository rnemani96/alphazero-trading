"""
AlphaZero Capital - Indicator Engine
=====================================
src/data/indicators.py

THE SINGLE SOURCE OF TRUTH for all technical indicator calculations.

Design rule from stock_ai_design.docx:
  "Same code used in: Backtest | Replay | Live"
  "Feature calculation must match LIVE and BACKTEST exactly."

All agents (TITAN, MultiTimeframe, IntradayRegime, etc.) must call this
module instead of computing indicators inline.  This guarantees that a
15-period RSI in the live system is IDENTICAL to the one used in backtests.

Supported indicators (aligned with the 45 strategies in MasterPlan):
  Trend      : EMA, DEMA, TEMA, HMA, Supertrend, Ichimoku, Parabolic SAR,
                Donchian Channel, Linear Regression Slope, Aroon, VWAP Band
  Momentum   : MACD, RSI, Stochastic, CCI, Williams %R, ADX/DI, MFI
  Volatility : ATR, Bollinger Bands, Keltner Channel, Historical Vol
  Volume     : OBV, A/D Line, Volume Z-Score, Delivery %
  India-specific: India VIX interpretation (passed in as scalar)

Usage:
    import pandas as pd
    from src.data.indicators import add_all_indicators, IndicatorEngine

    df = pd.read_parquet("data/features/RELIANCE_15m.parquet")
    df = add_all_indicators(df)          # adds ALL columns in-place

    # Or selective:
    engine = IndicatorEngine(df)
    df = engine.add_trend().add_momentum().add_volatility().build()
"""

from __future__ import annotations

import logging
from typing import Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add every indicator to a candle DataFrame and return it.

    Expects columns: open, high, low, close, volume
    Adds  : rsi, ema20, ema50, ema9, tema, hma20, macd, macd_signal,
            macd_hist, adx, di_plus, di_minus, atr, bb_upper, bb_mid,
            bb_lower, bb_width, kc_upper, kc_lower, stoch_k, stoch_d,
            cci, williams_r, obv, ad_line, vwap, mfi, aroon_up,
            aroon_down, volume_zscore, new_high_20d, new_low_20d,
            price_change_pct, supertrend, supertrend_direction
    """
    return (
        IndicatorEngine(df)
        .add_trend()
        .add_momentum()
        .add_volatility()
        .add_volume()
        .add_candlestick()
        .add_meta()
        .build()
    )


# ---------------------------------------------------------------------------
# IndicatorEngine — fluent builder
# ---------------------------------------------------------------------------

class IndicatorEngine:
    """
    Fluent builder that attaches indicators to a candle DataFrame.

    Example:
        df = IndicatorEngine(raw_df) \
                .add_trend() \
                .add_momentum() \
                .add_volatility() \
                .add_volume() \
                .build()
    """

    def __init__(self, df: pd.DataFrame):
        if df.empty:
            raise ValueError("IndicatorEngine: DataFrame must not be empty")
        required = {'open', 'high', 'low', 'close', 'volume'}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"IndicatorEngine: missing columns {missing}")

        self._df = df.copy()

    def build(self) -> pd.DataFrame:
        """Return the DataFrame, only dropping rows where core OHLCV data is missing."""
        # Essential columns required for any meaningful analysis
        essential = ['open', 'high', 'low', 'close', 'volume']
        return self._df.dropna(subset=essential).reset_index(drop=True)

    # ── Trend ────────────────────────────────────────────────────────────────

    def add_trend(self) -> 'IndicatorEngine':
        """EMA family, MACD, ADX, Supertrend, VWAP, Aroon."""
        df = self._df
        close = df['close']
        high  = df['high']
        low   = df['low']

        # EMA 9 / 20 / 50 / 200
        df['ema9']  = _ema(close, 9)
        df['ema20'] = _ema(close, 20)
        df['ema50'] = _ema(close, 50)
        df['ema200']= _ema(close, 200)

        # DEMA (Double EMA — less lag)
        ema20_2      = _ema(_ema(close, 20), 20)
        df['dema20'] = 2 * df['ema20'] - ema20_2

        # TEMA (Triple EMA)
        e1 = _ema(close, 20)
        e2 = _ema(e1, 20)
        e3 = _ema(e2, 20)
        df['tema20'] = 3 * e1 - 3 * e2 + e3

        # HMA (Hull MA — very low lag)
        df['hma20'] = _hma(close, 20)

        # MACD (12, 26, 9)
        df['macd'], df['macd_signal'], df['macd_hist'] = _macd(close)

        # ADX + DI+/DI- (14)
        df['adx'], df['di_plus'], df['di_minus'] = _adx(high, low, close, 14)

        # Supertrend (10, 3)
        df['supertrend'], df['supertrend_direction'] = _supertrend(high, low, close, 10, 3.0)

        # VWAP (intraday rolling — resets would need date logic; here: cumulative)
        df['vwap'] = _vwap(high, low, close, df['volume'])

        # Aroon (25)
        df['aroon_up'], df['aroon_down'] = _aroon(high, low, 25)
        df['aroon_osc'] = df['aroon_up'] - df['aroon_down']

        # Linear Regression Slope (20)
        df['lr_slope20'] = _lr_slope(close, 20)

        # Distance features (needed for CommitteeTrainer)
        df['ema20_dist'] = (close - df['ema20']) / df['ema20']
        df['ema50_dist'] = (close - df['ema50']) / df['ema50']

        self._df = df
        return self

    # ── Momentum ─────────────────────────────────────────────────────────────

    def add_momentum(self) -> 'IndicatorEngine':
        """RSI, Stochastic, CCI, Williams %R, MFI."""
        df    = self._df
        close = df['close']
        high  = df['high']
        low   = df['low']
        vol   = df['volume']

        # RSI (14)
        df['rsi'] = _rsi(close, 14)

        # Stochastic (14, 3)
        df['stoch_k'], df['stoch_d'] = _stochastic(high, low, close, 14, 3)

        # CCI (20)
        df['cci'] = _cci(high, low, close, 20)

        # Williams %R (14)
        df['williams_r'] = _williams_r(high, low, close, 14)

        # MFI (14)
        df['mfi'] = _mfi(high, low, close, vol, 14)

        self._df = df
        return self

    # ── Volatility ───────────────────────────────────────────────────────────

    def add_volatility(self) -> 'IndicatorEngine':
        """ATR, Bollinger Bands, Keltner Channel, Historical Volatility."""
        df    = self._df
        close = df['close']
        high  = df['high']
        low   = df['low']

        # ATR (14)
        df['atr'] = _atr(high, low, close, 14)

        # Bollinger Bands (20, 2σ)
        df['bb_upper'], df['bb_mid'], df['bb_lower'] = _bollinger(close, 20, 2.0)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
        df['bb_pct']   = (close - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        # Keltner Channel (20, 1.5×ATR)
        df['kc_upper'], df['kc_lower'] = _keltner(close, df['atr'], 20, 1.5)

        # Historical Volatility (20-period std of log-returns, annualised)
        log_ret = np.log(close / close.shift(1))
        df['hist_vol'] = log_ret.rolling(20).std() * np.sqrt(252)

        self._df = df
        return self

    # ── Volume ───────────────────────────────────────────────────────────────

    def add_volume(self) -> 'IndicatorEngine':
        """OBV, A/D Line, Volume Z-Score."""
        df    = self._df
        close = df['close']
        high  = df['high']
        low   = df['low']
        vol   = df['volume']

        # OBV
        df['obv'] = _obv(close, vol)

        # Accumulation / Distribution Line
        df['ad_line'] = _ad_line(high, low, close, vol)

        # Volume Z-Score (20-period)
        vol_mean = vol.rolling(20).mean()
        vol_std  = vol.rolling(20).std()
        df['volume_zscore'] = (vol - vol_mean) / (vol_std + 1e-9)

        # Average volume
        df['avg_volume'] = vol.rolling(20).mean()
        
        # Volume Ratio (relative to 20-period moving average)
        df['volume_ratio'] = vol / (df['avg_volume'] + 1e-9)

        self._df = df
        return self

    # ── Candlestick Patterns ───────────────────────────────────────────────

    def add_candlestick(self) -> 'IndicatorEngine':
        """Common price-action patterns (Doji, Hammer, Engulfing)."""
        df = self._df
        df = _detect_patterns(df)
        self._df = df
        return self

    # ── Meta / Derived ───────────────────────────────────────────────────────

    def add_meta(self) -> 'IndicatorEngine':
        """Derived flags used directly by TITAN and other agents."""
        df    = self._df
        close = df['close']
        high  = df['high']
        low   = df['low']

        # 20-day highs / lows
        df['new_high_20d'] = (close == high.rolling(20).max())
        df['new_low_20d']  = (close == low.rolling(20).min())

        # Price change %
        df['price_change_pct'] = close.pct_change() * 100

        # VWAP relative position
        if 'vwap' in df.columns:
            df['price_vs_vwap'] = (close - df['vwap']) / df['vwap']

        self._df = df
        return self


# ---------------------------------------------------------------------------
# Private calculation helpers (pure functions — no side effects)
# All take pandas Series, return Series (same index)
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def _hma(series: pd.Series, period: int) -> pd.Series:
    """Hull Moving Average (low-lag)."""
    half  = _ema(series, period // 2)
    full  = _ema(series, period)
    raw   = 2 * half - full
    return _ema(raw, int(np.sqrt(period)))


def _macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
):
    """Return (macd_line, signal_line, histogram)."""
    fast_ema   = _ema(close, fast)
    slow_ema   = _ema(close, slow)
    macd_line  = fast_ema - slow_ema
    signal_line= _ema(macd_line, signal)
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
):
    """Return (ADX, +DI, -DI)."""
    up   = high.diff()
    down = -low.diff()

    plus_dm  = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)

    atr14      = _atr(high, low, close, period)
    plus_di    = 100 * _ema(plus_dm, period)  / (atr14 + 1e-9)
    minus_di   = 100 * _ema(minus_dm, period) / (atr14 + 1e-9)
    dx         = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx        = _ema(dx, period)
    return adx, plus_di, minus_di


def _bollinger(close: pd.Series, period: int = 20, std_dev: float = 2.0):
    """Return (upper, middle, lower)."""
    mid   = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    return mid + std_dev * sigma, mid, mid - std_dev * sigma


def _keltner(close: pd.Series, atr: pd.Series, period: int = 20, mult: float = 1.5):
    """Return (upper, lower) Keltner Channel."""
    mid = close.rolling(period).mean()
    return mid + mult * atr, mid - mult * atr


def _stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series,
    k_period: int = 14, d_period: int = 3
):
    """Return (%K, %D)."""
    lowest  = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    k = 100 * (close - lowest) / (highest - lowest + 1e-9)
    d = k.rolling(d_period).mean()
    return k, d


def _cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    """Commodity Channel Index."""
    typical = (high + low + close) / 3
    mean    = typical.rolling(period).mean()
    mad     = typical.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (typical - mean) / (0.015 * mad + 1e-9)


def _williams_r(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Williams %R."""
    highest = high.rolling(period).max()
    lowest  = low.rolling(period).min()
    return -100 * (highest - close) / (highest - lowest + 1e-9)


def _mfi(
    high: pd.Series, low: pd.Series, close: pd.Series,
    volume: pd.Series, period: int = 14
) -> pd.Series:
    """Money Flow Index."""
    typical = (high + low + close) / 3
    raw_mf  = typical * volume
    pos_mf  = pd.Series(np.where(typical > typical.shift(1), raw_mf, 0.0), index=close.index)
    neg_mf  = pd.Series(np.where(typical < typical.shift(1), raw_mf, 0.0), index=close.index)
    mfr     = pos_mf.rolling(period).sum() / (neg_mf.rolling(period).sum() + 1e-9)
    return 100 - (100 / (1 + mfr))


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def _ad_line(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series
) -> pd.Series:
    """Accumulation / Distribution Line."""
    clv = ((close - low) - (high - close)) / (high - low + 1e-9)
    return (clv * volume).cumsum()


def _vwap(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series
) -> pd.Series:
    """
    Rolling VWAP.
    In production, reset daily. Here uses a 20-bar rolling window.
    """
    typical = (high + low + close) / 3
    return (typical * volume).rolling(20).sum() / (volume.rolling(20).sum() + 1e-9)


def _aroon(high: pd.Series, low: pd.Series, period: int = 25):
    """Return (Aroon Up, Aroon Down)."""
    aroon_up   = high.rolling(period + 1).apply(
        lambda x: (x.argmax() / period) * 100, raw=True
    )
    aroon_down = low.rolling(period + 1).apply(
        lambda x: (x.argmin() / period) * 100, raw=True
    )
    return aroon_up, aroon_down


def _lr_slope(close: pd.Series, period: int = 20) -> pd.Series:
    """Linear Regression Slope (normalised by price)."""
    x = np.arange(period)

    def slope(y: np.ndarray) -> float:
        if len(y) < period:
            return np.nan
        b = np.polyfit(x, y, 1)[0]
        return b / (y[-1] + 1e-9)   # normalise

    return close.rolling(period).apply(slope, raw=True)


def _supertrend(
    high: pd.Series, low: pd.Series, close: pd.Series,
    period: int = 10, multiplier: float = 3.0
):
    """
    Supertrend indicator.
    Returns (supertrend_line, direction) where direction = 1 (bullish) / -1 (bearish).
    """
    atr = _atr(high, low, close, period)
    mid = (high + low) / 2

    upper_band = mid + multiplier * atr
    lower_band = mid - multiplier * atr

    supertrend  = pd.Series(np.nan, index=close.index)
    direction   = pd.Series(1, index=close.index)

    for i in range(1, len(close)):
        prev_upper = upper_band.iloc[i - 1]
        prev_lower = lower_band.iloc[i - 1]
        curr_close = close.iloc[i]

        # Update bands
        if lower_band.iloc[i] < prev_lower or close.iloc[i - 1] < prev_lower:
            lower_band.iloc[i] = lower_band.iloc[i]
        else:
            lower_band.iloc[i] = prev_lower

        if upper_band.iloc[i] > prev_upper or close.iloc[i - 1] > prev_upper:
            upper_band.iloc[i] = upper_band.iloc[i]
        else:
            upper_band.iloc[i] = prev_upper

        # Direction
        prev_dir = direction.iloc[i - 1]
        if prev_dir == -1 and curr_close > upper_band.iloc[i - 1]:
            direction.iloc[i] = 1
        elif prev_dir == 1 and curr_close < lower_band.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = prev_dir

        supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]

    return supertrend, direction


def _detect_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Detect common candlestick patterns (True/False or 1/0)."""
    o, h, l, c = df['open'], df['high'], df['low'], df['close']
    body_size = (c - o).abs()
    candle_range = h - l
    
    # Doji (Body size <= 10% of total range)
    df['is_doji'] = (body_size <= (0.10 * candle_range)) & (candle_range > 0)
    
    # Hammer (Small body, long lower wick)
    # - Body in upper 1/3 of range
    # - Lower wick >= 2 * body size
    # - Upper wick <= 0.1 * candle_range
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)
    df['is_hammer'] = (lower_wick >= (2 * body_size)) & (upper_wick <= (0.1 * candle_range)) & (candle_range > 0)
    
    # Shooting Star (Small body, long upper wick) - Bearish reversal
    df['is_shooting_star'] = (upper_wick >= (2 * body_size)) & (lower_wick <= (0.1 * candle_range)) & (candle_range > 0)
    
    # Engulfing Patterns
    # Bullish: Previous candle red, current green and engulfs body
    prev_o = o.shift(1); prev_c = c.shift(1)
    df['is_bull_engulfing'] = (prev_c < prev_o) & (c > o) & (c >= prev_o) & (o <= prev_c)
    
    # Bearish: Previous candle green, current red and engulfs body
    df['is_bear_engulfing'] = (prev_c > prev_o) & (c < o) & (c <= prev_o) & (o >= prev_c)
    
    # Morning / Evening Star (3-candle patterns)
    # Morning Star: Bearish -> Doji/Small -> Bullish
    # Shift indices manually for 3-candle window
    # Simple versions:
    df['is_morning_star'] = (c.shift(2) < o.shift(2)) & (df['is_doji'].shift(1)) & (c > o) & (c > (o.shift(2) + c.shift(2))/2)
    df['is_evening_star'] = (c.shift(2) > o.shift(2)) & (df['is_doji'].shift(1)) & (c < o) & (c < (o.shift(2) + c.shift(2))/2)

    return df


# ---------------------------------------------------------------------------
# Convenience: compute single indicator from raw dict (for live streaming)
# ---------------------------------------------------------------------------

def compute_from_dict(candle_dict: dict, history: pd.DataFrame) -> dict:
    """
    Append a new candle to history, compute all indicators, return the
    latest row as a dict.  Suitable for live streaming (one candle at a time).

    Args:
        candle_dict : {'open':…, 'high':…, 'low':…, 'close':…, 'volume':…}
        history     : DataFrame of past candles (already has indicator columns)

    Returns:
        Dict with all indicator values for the latest candle.
    """
    new_row = pd.DataFrame([candle_dict])
    combined = pd.concat([history, new_row], ignore_index=True)

    # Only need the raw OHLCV columns to recompute
    raw = combined[['open', 'high', 'low', 'close', 'volume']].copy()
    enriched = add_all_indicators(raw)

    if enriched.empty:
        return candle_dict

    return enriched.iloc[-1].to_dict()
