"""
TITAN — Strategy Execution Agent
Runs all 45 strategies in parallel, computes signals + confidence.
Every strategy publishes: {signal: -1/0/+1, confidence: 0-1, reason: str}
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger("TITAN")


@dataclass
class Signal:
    strategy_id: str
    strategy_name: str
    category: str
    signal: int          # -1 SELL | 0 NEUTRAL | +1 BUY
    confidence: float    # 0.0 → 1.0
    reason: str
    timeframe: str
    indicators: dict


class TitanStrategyEngine:
    """
    Runs all 45 strategy modules on a feature-complete candle DataFrame.
    Usage:
        titan = TitanStrategyEngine()
        signals = titan.compute_all(df, symbol="RELIANCE")
        agreed = titan.get_consensus(signals, min_agreement=0.6)
    """

    def __init__(self):
        self.strategies = self._register_all_strategies()
        self.signal_history: dict[str, list] = {}
        self.optimized_params: dict[str, dict] = {}
        self._load_optimized_params()

    def _load_optimized_params(self):
        """Load Bayesian-optimized hyperparameters per symbol if available."""
        import os, json
        path = "models/optimized_params.json"
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    self.optimized_params = json.load(f)
                logger.info("TITAN: Loaded Bayesian optimized parameters for %d stocks", len(self.optimized_params))
            except Exception as e:
                logger.debug("Failed to load optimized_params.json: %s", e)

    def _register_all_strategies(self):
        """Return list of (id, name, category, timeframe, fn) tuples."""
        return [
            # ── Category A: Trend Following (12) ──────────────────────────
            ("T1",  "EMA Cross Classic",       "Trend",          "15m+1D", self.t1_ema_cross),
            ("T2",  "Triple EMA (TEMA)",        "Trend",          "15m",    self.t2_triple_ema),
            ("T3",  "Supertrend Follower",      "Trend",          "15m+1D", self.t3_supertrend),
            ("T4",  "MACD Momentum",            "Trend",          "1D",     self.t4_macd),
            ("T5",  "ADX Trend Strength",       "Trend",          "1D",     self.t5_adx),
            ("T6",  "Parabolic SAR",            "Trend",          "5m",     self.t6_psar),
            ("T7",  "Donchian Breakout",        "Trend",          "1D",     self.t7_donchian),
            ("T8",  "Hull Moving Average",      "Trend",          "15m",    self.t8_hma),
            ("T9",  "Ichimoku Cloud",           "Trend",          "1D",     self.t9_ichimoku),
            ("T10", "Linear Regression Slope",  "Trend",          "15m",    self.t10_linreg),
            ("T11", "Elder Triple Screen",      "Trend",          "1D",     self.t11_elder),
            ("T12", "Aroon Oscillator",         "Trend",          "1D",     self.t12_aroon),
            # ── Category B: Mean Reversion (10) ───────────────────────────
            ("M1",  "RSI Reversal",             "Mean Reversion", "15m",    self.m1_rsi),
            ("M2",  "Bollinger Band Bounce",    "Mean Reversion", "15m",    self.m2_bb),
            ("M3",  "BB Squeeze",               "Mean Reversion", "15m+1D", self.m3_bb_squeeze),
            ("M4",  "Stochastic Oversold",      "Mean Reversion", "15m",    self.m4_stoch),
            ("M5",  "CCI Extreme",              "Mean Reversion", "1D",     self.m5_cci),
            ("M6",  "Williams %R",              "Mean Reversion", "15m",    self.m6_williams),
            ("M7",  "RSI Divergence",           "Mean Reversion", "1D",     self.m7_rsi_div),
            ("M8",  "Keltner Channel Revert",   "Mean Reversion", "15m",    self.m8_keltner),
            ("M9",  "Z-Score Reversion",        "Mean Reversion", "1D",     self.m9_zscore),
            ("M10", "Price Momentum Oscillator","Mean Reversion", "1D",     self.m10_pmo),
            # ── Category C: Breakout (8) ──────────────────────────────────
            ("B1",  "ORB Strategy",             "Breakout",       "5m",     self.b1_orb),
            ("B2",  "Volume Breakout",          "Breakout",       "15m+1D", self.b2_volume_bo),
            ("B3",  "52-Week High Break",       "Breakout",       "1D",     self.b3_52wk),
            ("B4",  "Inside Bar Breakout",      "Breakout",       "1D",     self.b4_inside),
            ("B5",  "Resistance Break",         "Breakout",       "15m",    self.b5_resistance),
            ("B6",  "Flag Pattern",             "Breakout",       "1D",     self.b6_flag),
            ("B7",  "Cup and Handle",           "Breakout",       "1D",     self.b7_cup),
            ("B8",  "Volatility Squeeze BO",    "Breakout",       "15m",    self.b8_squeeze_bo),
            # ── Category D: VWAP (5) ──────────────────────────────────────
            ("V1",  "VWAP Cross",               "VWAP",           "5m",     self.v1_vwap_cross),
            ("V2",  "VWAP Deviation",           "VWAP",           "5m",     self.v2_vwap_dev),
            ("V3",  "VWAP Anchored",            "VWAP",           "5m",     self.v3_vwap_anchored),
            ("V4",  "VWAP Bands",               "VWAP",           "5m",     self.v4_vwap_bands),
            ("V5",  "VWAP Slope",               "VWAP",           "5m",     self.v5_vwap_slope),
            # ── Category E: Volume (5) ────────────────────────────────────
            ("VL1", "OBV Trend",                "Volume",         "1D",     self.vl1_obv),
            ("VL2", "Volume Price Trend",       "Volume",         "1D",     self.vl2_vpt),
            ("VL3", "Accumulation/Distribution","Volume",         "1D",     self.vl3_adl),
            ("VL4", "Chaikin Money Flow",       "Volume",         "15m",    self.vl4_cmf),
            ("VL5", "Volume Profile",           "Volume",         "1D",     self.vl5_volume_profile),
            # ── Category F: Statistical (5) ───────────────────────────────
            ("S1",  "Pairs Trading",            "Statistical",    "1D",     self.s1_pairs),
            ("S2",  "Gap Fill",                 "Statistical",    "15m",    self.s2_gap),
            ("S3",  "Opening Range Bias",       "Statistical",    "15m",    self.s3_orb2),
            ("S4",  "Seasonal Pattern",         "Statistical",    "1D",     self.s4_seasonal),
            ("S5",  "Event Momentum",           "Statistical",    "1D",     self.s5_event),
            # ── Category G: Candlestick Patterns (4) ──────────────────────
            ("G1",  "Hammer / Shooting Star",   "Price Action",   "15m",    self.g1_hammer),
            ("G2",  "Engulfing Reversal",       "Price Action",   "15m",    self.g2_engulfing),
            ("G3",  "Morning / Evening Star",   "Price Action",   "15m",    self.g3_stars),
            ("G4",  "Doji Breakout",            "Price Action",   "15m",    self.g4_doji),
        ]

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _safe(df: pd.DataFrame, col: str, n: int = 1):
        """Safely get last n values of column as numpy array."""
        if col not in df.columns or len(df) < n:
            return None
        return df[col].iloc[-n:].values

    @staticmethod
    def _last(df: pd.DataFrame, col: str):
        if col not in df.columns or df.empty:
            return None
        return df[col].iloc[-1]

    def _compute_base(self, df: pd.DataFrame, symbol: str = "") -> dict:
        """Compute all base indicators using optimized per-symbol params if available."""
        r = {}
        if df.empty:
            return r
        c = df["close"].values
        h = df["high"].values
        l = df["low"].values
        v = df["volume"].values if "volume" in df.columns else np.ones(len(c))

        # EMAs
        def ema(x, p):
            k = 2 / (p + 1)
            result = np.zeros(len(x))
            result[0] = x[0]
            for i in range(1, len(x)):
                result[i] = x[i] * k + result[i-1] * (1 - k)
            return result

        # Fetch dynamic parameters
        p = self.optimized_params.get(symbol, {})
        ema_fast = p.get("EMA_FAST", 20)
        ema_slow = p.get("EMA_SLOW", 50)
        rsi_per  = p.get("RSI_PERIOD", 14)
        atr_per  = p.get("ATR_PERIOD", 14)

        r["ema9"]  = ema(c, 9)
        r["ema20"] = ema(c, ema_fast) # Re-mapped for dynamic T1
        r["ema50"] = ema(c, ema_slow) # Re-mapped for dynamic T1
        r["ema200"]= ema(c, 200) if len(c) >= 200 else ema(c, len(c))

        # ATR
        if len(c) > 1:
            tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1))))
            tr[0] = h[0] - l[0]
            r["atr14"] = ema(tr, atr_per)

        # RSI
        if len(c) >= rsi_per + 1:
            delta = np.diff(c, prepend=c[0])
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            avg_g = ema(gain, rsi_per)
            avg_l = ema(loss, rsi_per)
            rs = np.divide(avg_g, avg_l, out=np.full_like(avg_g, 100), where=avg_l != 0)
            r["rsi"] = 100 - 100 / (1 + rs)

        # Bollinger Bands
        if len(c) >= 20:
            ma20 = np.array([np.mean(c[max(0, i-19):i+1]) for i in range(len(c))])
            std20 = np.array([np.std(c[max(0, i-19):i+1]) for i in range(len(c))])
            r["bb_mid"] = ma20; r["bb_up"] = ma20 + 2*std20; r["bb_lo"] = ma20 - 2*std20
            r["bb_width"] = np.divide((r["bb_up"] - r["bb_lo"]), ma20, out=np.zeros_like(ma20), where=ma20 != 0)

        # MACD
        if len(c) >= 26:
            macd_line = ema(c, 12) - ema(c, 26)
            signal = ema(macd_line, 9)
            r["macd"] = macd_line; r["macd_sig"] = signal; r["macd_hist"] = macd_line - signal

        # ADX
        if len(c) > 14:
            tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1))))
            tr[0] = h[0] - l[0]
            pdm = np.where((h - np.roll(h, 1)) > (np.roll(l, 1) - l), np.maximum(h - np.roll(h, 1), 0), 0)
            ndm = np.where((np.roll(l, 1) - l) > (h - np.roll(h, 1)), np.maximum(np.roll(l, 1) - l, 0), 0)
            atr14 = ema(tr, 14)
            pdi = 100 * ema(pdm, 14) / np.where(atr14 != 0, atr14, 1)
            ndi = 100 * ema(ndm, 14) / np.where(atr14 != 0, atr14, 1)
            dx = 100 * np.divide(abs(pdi - ndi), (pdi + ndi), out=np.zeros_like(pdi), where=(pdi + ndi) != 0)
            r["adx"] = ema(dx, 14); r["pdi"] = pdi; r["ndi"] = ndi

        # Stochastic
        if len(c) >= 14:
            lo14 = np.array([np.min(l[max(0,i-13):i+1]) for i in range(len(c))])
            hi14 = np.array([np.max(h[max(0,i-13):i+1]) for i in range(len(c))])
            denom = hi14 - lo14
            r["stoch_k"] = 100 * np.divide((c - lo14), denom, out=np.full_like(c, 0.5), where=denom != 0)
            r["stoch_d"] = ema(r["stoch_k"], 3)

        # VWAP
        if len(c) >= 2:
            tp = (h + l + c) / 3
            cum_vol = np.cumsum(v)
            cum_tpv = np.cumsum(tp * v)
            r["vwap"] = np.divide(cum_tpv, cum_vol, out=tp.copy(), where=cum_vol > 0)

        # OBV
        obv = np.zeros(len(c))
        for i in range(1, len(c)):
            obv[i] = obv[i-1] + (v[i] if c[i] > c[i-1] else -v[i] if c[i] < c[i-1] else 0)
        r["obv"] = obv

        r["close"] = c; r["high"] = h; r["low"] = l; r["volume"] = v
        return r

    # ── Individual Strategy Functions ────────────────────────────────────────

    def t1_ema_cross(self, df, ind):
        e20, e50, c = ind.get("ema20"), ind.get("ema50"), ind.get("close")
        if e20 is None or len(e20) < 2: return Signal("T1","EMA Cross Classic","Trend",0,0.0,"Insufficient data","15m+1D",{})
        cross_up   = e20[-1] > e50[-1] and e20[-2] <= e50[-2]
        cross_down = e20[-1] < e50[-1] and e20[-2] >= e50[-2]
        above = e20[-1] > e50[-1]
        gap = abs(e20[-1] - e50[-1]) / e50[-1] * 100
        if cross_up:
            return Signal("T1","EMA Cross Classic","Trend",1, min(0.95, 0.65 + gap*2), f"EMA20 crossed above EMA50. Gap={gap:.2f}%","15m+1D",{"ema20":e20[-1],"ema50":e50[-1]})
        if cross_down:
            return Signal("T1","EMA Cross Classic","Trend",-1, min(0.95, 0.65 + gap*2), f"EMA20 crossed below EMA50. Gap={gap:.2f}%","15m+1D",{"ema20":e20[-1],"ema50":e50[-1]})
        sig = 1 if above else -1
        return Signal("T1","EMA Cross Classic","Trend", sig, 0.40 + min(0.25, gap*3), f"EMA20 {'above' if above else 'below'} EMA50 (no fresh cross)","15m+1D",{"ema20":e20[-1],"ema50":e50[-1]})

    def t2_triple_ema(self, df, ind):
        e9, e20, e50, c = ind.get("ema9"), ind.get("ema20"), ind.get("ema50"), ind.get("close")
        if e9 is None: return Signal("T2","Triple EMA","Trend",0,0.0,"Insufficient data","15m",{})
        aligned_bull = e9[-1] > e20[-1] > e50[-1]
        aligned_bear = e9[-1] < e20[-1] < e50[-1]
        if aligned_bull:
            return Signal("T2","Triple EMA","Trend",1,0.78, "Full bullish EMA alignment: 9>20>50","15m",{"e9":e9[-1],"e20":e20[-1],"e50":e50[-1]})
        if aligned_bear:
            return Signal("T2","Triple EMA","Trend",-1,0.78,"Full bearish EMA alignment: 9<20<50","15m",{"e9":e9[-1],"e20":e20[-1],"e50":e50[-1]})
        return Signal("T2","Triple EMA","Trend",0,0.30,"EMAs mixed/crossing","15m",{})

    def t3_supertrend(self, df, ind):
        atr = ind.get("atr14"); c = ind.get("close"); h = ind.get("high"); l = ind.get("low")
        if atr is None or len(c) < 2: return Signal("T3","Supertrend Follower","Trend",0,0.0,"No ATR","15m+1D",{})
        factor = 3.0
        ub = (h[-1] + l[-1]) / 2 + factor * atr[-1]
        lb = (h[-1] + l[-1]) / 2 - factor * atr[-1]
        prev_c = c[-2]
        if c[-1] > lb and prev_c < (h[-2]+l[-2])/2 - factor*atr[-2]:
            return Signal("T3","Supertrend Follower","Trend",1,0.72,"Price flipped above Supertrend lower band","15m+1D",{"support":lb})
        if c[-1] < ub and prev_c > (h[-2]+l[-2])/2 + factor*atr[-2]:
            return Signal("T3","Supertrend Follower","Trend",-1,0.72,"Price flipped below Supertrend upper band","15m+1D",{"resistance":ub})
        if c[-1] > lb: return Signal("T3","Supertrend Follower","Trend",1,0.55,"Price above Supertrend support","15m+1D",{"support":lb})
        return Signal("T3","Supertrend Follower","Trend",-1,0.55,"Price below Supertrend resistance","15m+1D",{"resistance":ub})

    def t4_macd(self, df, ind):
        hist = ind.get("macd_hist"); macd = ind.get("macd"); sig = ind.get("macd_sig")
        if hist is None or len(hist) < 2: return Signal("T4","MACD Momentum","Trend",0,0.0,"No MACD","1D",{})
        cross_up   = hist[-1] > 0 and hist[-2] <= 0
        cross_down = hist[-1] < 0 and hist[-2] >= 0
        rising = hist[-1] > hist[-2]
        if cross_up:   return Signal("T4","MACD Momentum","Trend",1,0.75,"MACD histogram crossed above zero","1D",{"macd":macd[-1],"sig":sig[-1]})
        if cross_down: return Signal("T4","MACD Momentum","Trend",-1,0.75,"MACD histogram crossed below zero","1D",{"macd":macd[-1],"sig":sig[-1]})
        if hist[-1] > 0 and rising: return Signal("T4","MACD Momentum","Trend",1,0.55,"MACD positive and expanding","1D",{})
        if hist[-1] < 0 and not rising: return Signal("T4","MACD Momentum","Trend",-1,0.55,"MACD negative and expanding","1D",{})
        return Signal("T4","MACD Momentum","Trend",0,0.30,"MACD momentum weak","1D",{})

    def t5_adx(self, df, ind):
        adx = ind.get("adx"); pdi = ind.get("pdi"); ndi = ind.get("ndi")
        if adx is None: return Signal("T5","ADX Trend Strength","Trend",0,0.0,"No ADX","1D",{})
        strong = adx[-1] > 25; very_strong = adx[-1] > 35
        if strong and pdi[-1] > ndi[-1]:
            return Signal("T5","ADX Trend Strength","Trend",1, 0.80 if very_strong else 0.65, f"ADX={adx[-1]:.1f} strong uptrend. +DI>{'-DI'}","1D",{"adx":adx[-1],"pdi":pdi[-1],"ndi":ndi[-1]})
        if strong and ndi[-1] > pdi[-1]:
            return Signal("T5","ADX Trend Strength","Trend",-1, 0.80 if very_strong else 0.65, f"ADX={adx[-1]:.1f} strong downtrend. -DI>+DI","1D",{"adx":adx[-1]})
        return Signal("T5","ADX Trend Strength","Trend",0, 0.30, f"ADX={adx[-1]:.1f} weak/no trend","1D",{"adx":adx[-1]})

    def t6_psar(self, df, ind):
        c = ind.get("close"); h = ind.get("high"); l = ind.get("low")
        if c is None or len(c) < 5: return Signal("T6","Parabolic SAR","Trend",0,0.0,"Insufficient data","15m",{})
        # Simplified: PSAR is above/below price based on recent trend
        recent_high = np.max(h[-5:]) if len(h) >= 5 else h[-1]
        recent_low  = np.min(l[-5:]) if len(l) >= 5 else l[-1]
        bullish = c[-1] > (recent_high + recent_low) / 2
        v = ind.get("volume"); avg_v = np.mean(v[-10:]) if v is not None and len(v) >= 10 else 1
        vol_conf = v[-1] > avg_v * 1.1 if v is not None else False
        sig = 1 if bullish else -1
        conf = 0.62 if vol_conf else 0.48
        return Signal("T6","Parabolic SAR","Trend",sig,conf,f"SAR {'below' if bullish else 'above'} price. Vol {'confirmed' if vol_conf else 'weak'}","15m",{})

    def t7_donchian(self, df, ind):
        c = ind.get("close"); h = ind.get("high"); l = ind.get("low")
        if c is None or len(c) < 20: return Signal("T7","Donchian Breakout","Trend",0,0.0,"Need 20 bars","1D",{})
        upper = np.max(h[-20:]); lower = np.min(l[-20:])
        if c[-1] >= upper * 0.998:
            return Signal("T7","Donchian Breakout","Trend",1,0.80,f"Price at 20-period high ({upper:.2f}) — Donchian breakout","1D",{"upper":upper})
        if c[-1] <= lower * 1.002:
            return Signal("T7","Donchian Breakout","Trend",-1,0.80,f"Price at 20-period low ({lower:.2f}) — breakdown","1D",{"lower":lower})
        pos = (c[-1] - lower) / max(upper - lower, 1)
        return Signal("T7","Donchian Breakout","Trend",1 if pos > 0.6 else (-1 if pos < 0.4 else 0), 0.38, f"Within Donchian range. Pos={pos:.2f}","1D",{})

    def t8_hma(self, df, ind):
        c = ind.get("close")
        if c is None or len(c) < 20: return Signal("T8","Hull MA Cross","Trend",0,0.0,"Need data","15m",{})
        def wma(x, p):
            weights = np.arange(1, p+1)
            return np.array([np.dot(x[max(0,i-p+1):i+1], weights[-min(p,i+1):]) / np.sum(weights[-min(p,i+1):]) for i in range(len(x))])
        p = min(16, len(c)//2)
        half_wma = wma(c, p//2)
        full_wma = wma(c, p)
        raw = 2 * half_wma - full_wma
        hma = wma(raw, max(2, int(p**0.5)))
        rising = len(hma) >= 2 and hma[-1] > hma[-2]
        return Signal("T8","Hull MA Cross","Trend", 1 if rising else -1, 0.65 if abs(hma[-1]-hma[-2])/max(abs(hma[-2]),1) > 0.001 else 0.42, f"HMA {'rising' if rising else 'falling'}","15m",{"hma":hma[-1]})

    def t9_ichimoku(self, df, ind):
        c = ind.get("close"); h = ind.get("high"); l = ind.get("low")
        if c is None or len(c) < 52: return Signal("T9","Ichimoku Cloud","Trend",0,0.0,"Need 52 bars","1D",{})
        tenkan = (np.max(h[-9:]) + np.min(l[-9:])) / 2
        kijun  = (np.max(h[-26:]) + np.min(l[-26:])) / 2
        sa = (tenkan + kijun) / 2
        sb = (np.max(h[-52:]) + np.min(l[-52:])) / 2
        above_cloud = c[-1] > max(sa, sb)
        below_cloud = c[-1] < min(sa, sb)
        tk_cross_bull = tenkan > kijun
        if above_cloud and tk_cross_bull:
            return Signal("T9","Ichimoku Cloud","Trend",1,0.82,"Price above cloud, Tenkan>Kijun — strong bull","1D",{"tenkan":tenkan,"kijun":kijun})
        if below_cloud and not tk_cross_bull:
            return Signal("T9","Ichimoku Cloud","Trend",-1,0.82,"Price below cloud — strong bear","1D",{"tenkan":tenkan,"kijun":kijun})
        return Signal("T9","Ichimoku Cloud","Trend",0,0.35,"Price in cloud / mixed","1D",{})

    def t10_linreg(self, df, ind):
        c = ind.get("close")
        if c is None or len(c) < 14: return Signal("T10","LinReg Slope","Trend",0,0.0,"Need data","15m",{})
        x = np.arange(14); y = c[-14:]
        slope = np.polyfit(x, y, 1)[0]
        norm_slope = slope / c[-1] * 100
        if norm_slope > 0.05:  return Signal("T10","LinReg Slope","Trend",1, min(0.85, 0.5+abs(norm_slope)*3), f"Positive slope={norm_slope:.3f}%/bar","15m",{"slope":slope})
        if norm_slope < -0.05: return Signal("T10","LinReg Slope","Trend",-1, min(0.85, 0.5+abs(norm_slope)*3), f"Negative slope={norm_slope:.3f}%/bar","15m",{"slope":slope})
        return Signal("T10","LinReg Slope","Trend",0,0.28,"Flat trend","15m",{})

    def t11_elder(self, df, ind):
        c = ind.get("close"); macd_h = ind.get("macd_hist"); rsi = ind.get("rsi")
        if c is None or macd_h is None or rsi is None: return Signal("T11","Elder Triple Screen","Trend",0,0.0,"Insufficient","1D",{})
        e13 = ind.get("ema20")  # use as weekly proxy
        if e13 is None: return Signal("T11","Elder Triple Screen","Trend",0,0.0,"No EMA","1D",{})
        bull = c[-1] > e13[-1] and macd_h[-1] > 0 and rsi[-1] > 50
        bear = c[-1] < e13[-1] and macd_h[-1] < 0 and rsi[-1] < 50
        if bull: return Signal("T11","Elder Triple Screen","Trend",1,0.78,"All 3 screens bullish aligned","1D",{})
        if bear: return Signal("T11","Elder Triple Screen","Trend",-1,0.78,"All 3 screens bearish aligned","1D",{})
        return Signal("T11","Elder Triple Screen","Trend",0,0.30,"Mixed screens","1D",{})

    def t12_aroon(self, df, ind):
        h = ind.get("high"); l = ind.get("low")
        if h is None or len(h) < 25: return Signal("T12","Aroon Oscillator","Trend",0,0.0,"Need 25 bars","1D",{})
        aroon_up   = (25 - (25 - 1 - np.argmax(h[-25:]))) / 25 * 100
        aroon_down = (25 - (25 - 1 - np.argmax(-l[-25:]))) / 25 * 100
        osc = aroon_up - aroon_down
        if osc > 50:  return Signal("T12","Aroon Oscillator","Trend",1, 0.5+osc/200, f"Aroon osc={osc:.1f} bull","1D",{"aroon_osc":osc})
        if osc < -50: return Signal("T12","Aroon Oscillator","Trend",-1, 0.5+abs(osc)/200, f"Aroon osc={osc:.1f} bear","1D",{"aroon_osc":osc})
        return Signal("T12","Aroon Oscillator","Trend",0,0.30,"Aroon neutral","1D",{})

    def m1_rsi(self, df, ind):
        rsi = ind.get("rsi")
        if rsi is None or len(rsi) < 2: return Signal("M1","RSI Reversal","Mean Reversion",0,0.0,"No RSI","15m",{})
        r = rsi[-1]
        if r < 30:  return Signal("M1","RSI Reversal","Mean Reversion",1, 0.65+max(0,(30-r)/30*0.30), f"RSI={r:.1f} oversold — reversal buy","15m",{"rsi":r})
        if r > 70:  return Signal("M1","RSI Reversal","Mean Reversion",-1, 0.65+max(0,(r-70)/30*0.30), f"RSI={r:.1f} overbought — reversal sell","15m",{"rsi":r})
        if r < 40 and rsi[-2] < rsi[-1]: return Signal("M1","RSI Reversal","Mean Reversion",1,0.48,f"RSI={r:.1f} recovering from oversold","15m",{"rsi":r})
        if r > 60 and rsi[-2] > rsi[-1]: return Signal("M1","RSI Reversal","Mean Reversion",-1,0.48,f"RSI={r:.1f} pulling back from overbought","15m",{"rsi":r})
        return Signal("M1","RSI Reversal","Mean Reversion",0,0.25,f"RSI={r:.1f} neutral zone","15m",{"rsi":r})

    def m2_bb(self, df, ind):
        c = ind.get("close"); bb_up = ind.get("bb_up"); bb_lo = ind.get("bb_lo"); bb_mid = ind.get("bb_mid")
        if bb_up is None: return Signal("M2","BB Bounce","Mean Reversion",0,0.0,"No BB","15m",{})
        pct_b = (c[-1] - bb_lo[-1]) / max(bb_up[-1] - bb_lo[-1], 1)
        if pct_b < 0.05:  return Signal("M2","BB Bounce","Mean Reversion",1,0.72,f"Price at lower BB band — bounce expected. %B={pct_b:.2f}","15m",{"pct_b":pct_b})
        if pct_b > 0.95:  return Signal("M2","BB Bounce","Mean Reversion",-1,0.72,f"Price at upper BB band — reversal expected. %B={pct_b:.2f}","15m",{"pct_b":pct_b})
        return Signal("M2","BB Bounce","Mean Reversion",0,0.25,"Price mid-band","15m",{"pct_b":pct_b})

    def m3_bb_squeeze(self, df, ind):
        bw = ind.get("bb_width"); c = ind.get("close")
        if bw is None or len(bw) < 20: return Signal("M3","BB Squeeze","Mean Reversion",0,0.0,"No BB width","15m+1D",{})
        avg_bw = np.mean(bw[-20:]); curr_bw = bw[-1]
        squeeze = curr_bw < avg_bw * 0.75
        if squeeze:
            e20 = ind.get("ema20")
            direction = 1 if (e20 is not None and c[-1] > e20[-1]) else -1
            return Signal("M3","BB Squeeze","Mean Reversion",direction,0.73,f"BB squeeze detected! Width={curr_bw:.4f} vs avg={avg_bw:.4f}. Breakout imminent","15m+1D",{"bb_width":curr_bw})
        return Signal("M3","BB Squeeze","Mean Reversion",0,0.28,"No squeeze — bands expanding","15m+1D",{"bb_width":curr_bw})

    def m4_stoch(self, df, ind):
        k = ind.get("stoch_k"); d = ind.get("stoch_d")
        if k is None: return Signal("M4","Stochastic","Mean Reversion",0,0.0,"No Stoch","15m",{})
        if k[-1] < 20 and d is not None and k[-1] > d[-1]:
            return Signal("M4","Stochastic","Mean Reversion",1,0.68,f"Stoch K={k[-1]:.1f} oversold+cross","15m",{"k":k[-1],"d":d[-1] if d is not None else 0})
        if k[-1] > 80 and d is not None and k[-1] < d[-1]:
            return Signal("M4","Stochastic","Mean Reversion",-1,0.68,f"Stoch K={k[-1]:.1f} overbought+cross","15m",{"k":k[-1]})
        return Signal("M4","Stochastic","Mean Reversion",0,0.25,"Stoch neutral","15m",{})

    def m5_cci(self, df, ind):
        c = ind.get("close"); h = ind.get("high"); l = ind.get("low")
        if c is None or len(c) < 20: return Signal("M5","CCI Extreme","Mean Reversion",0,0.0,"Need data","1D",{})
        tp = (c[-20:] + h[-20:] + l[-20:]) / 3
        mean_tp = np.mean(tp); mad = np.mean(np.abs(tp - mean_tp))
        cci = (tp[-1] - mean_tp) / (0.015 * max(mad, 0.001))
        if cci < -100: return Signal("M5","CCI Extreme","Mean Reversion",1,0.68,f"CCI={cci:.1f} extreme oversold","1D",{"cci":cci})
        if cci > 100:  return Signal("M5","CCI Extreme","Mean Reversion",-1,0.68,f"CCI={cci:.1f} extreme overbought","1D",{"cci":cci})
        return Signal("M5","CCI Extreme","Mean Reversion",0,0.28,f"CCI={cci:.1f} normal","1D",{"cci":cci})

    def m6_williams(self, df, ind):
        c = ind.get("close"); h = ind.get("high"); l = ind.get("low")
        if c is None or len(c) < 14: return Signal("M6","Williams %R","Mean Reversion",0,0.0,"Need data","15m",{})
        hh = np.max(h[-14:]); ll = np.min(l[-14:])
        wr = -100 * (hh - c[-1]) / max(hh - ll, 0.001)
        if wr < -80: return Signal("M6","Williams %R","Mean Reversion",1,0.65,f"W%R={wr:.1f} oversold","15m",{"wr":wr})
        if wr > -20: return Signal("M6","Williams %R","Mean Reversion",-1,0.65,f"W%R={wr:.1f} overbought","15m",{"wr":wr})
        return Signal("M6","Williams %R","Mean Reversion",0,0.28,"W%R neutral","15m",{})

    def m7_rsi_div(self, df, ind):
        c = ind.get("close"); rsi = ind.get("rsi")
        if c is None or rsi is None or len(c) < 14: return Signal("M7","RSI Divergence","Mean Reversion",0,0.0,"Need data","1D",{})
        price_rising = c[-1] > np.mean(c[-7:-1])
        rsi_falling  = rsi[-1] < np.mean(rsi[-7:-1])
        if price_rising and rsi_falling: return Signal("M7","RSI Divergence","Mean Reversion",-1,0.72,"Bearish RSI divergence: price up, RSI falling","1D",{"rsi":rsi[-1]})
        price_falling = c[-1] < np.mean(c[-7:-1])
        rsi_rising    = rsi[-1] > np.mean(rsi[-7:-1])
        if price_falling and rsi_rising: return Signal("M7","RSI Divergence","Mean Reversion",1,0.72,"Bullish RSI divergence: price down, RSI rising","1D",{"rsi":rsi[-1]})
        return Signal("M7","RSI Divergence","Mean Reversion",0,0.28,"No divergence","1D",{})

    def m8_keltner(self, df, ind):
        c = ind.get("close"); atr = ind.get("atr14"); e20 = ind.get("ema20")
        if atr is None or e20 is None: return Signal("M8","Keltner Revert","Mean Reversion",0,0.0,"No ATR/EMA","15m",{})
        kup = e20[-1] + 2*atr[-1]; klo = e20[-1] - 2*atr[-1]
        if c[-1] < klo: return Signal("M8","Keltner Revert","Mean Reversion",1,0.68,f"Price below Keltner lower ({klo:.2f}) — buy","15m",{"keltner_lo":klo})
        if c[-1] > kup: return Signal("M8","Keltner Revert","Mean Reversion",-1,0.68,f"Price above Keltner upper ({kup:.2f}) — sell","15m",{"keltner_up":kup})
        return Signal("M8","Keltner Revert","Mean Reversion",0,0.28,"Within Keltner","15m",{})

    def m9_zscore(self, df, ind):
        c = ind.get("close")
        if c is None or len(c) < 20: return Signal("M9","Z-Score Reversion","Mean Reversion",0,0.0,"Need data","1D",{})
        mu = np.mean(c[-20:]); sigma = np.std(c[-20:])
        z = (c[-1] - mu) / max(sigma, 0.001)
        if z < -2: return Signal("M9","Z-Score","Mean Reversion",1,0.75+min(0.15,abs(z+2)*0.1),f"Z={z:.2f} — 2σ below mean, strong reversion buy","1D",{"z":z})
        if z > 2:  return Signal("M9","Z-Score","Mean Reversion",-1,0.75+min(0.15,(z-2)*0.1),f"Z={z:.2f} — 2σ above mean, strong reversion sell","1D",{"z":z})
        return Signal("M9","Z-Score","Mean Reversion",0,0.28,f"Z={z:.2f} normal","1D",{})

    def m10_pmo(self, df, ind):
        c = ind.get("close")
        if c is None or len(c) < 35: return Signal("M10","PMO","Mean Reversion",0,0.0,"Need data","1D",{})
        roc = np.diff(c[-35:], prepend=c[-35]) / c[-35] * 10
        def ema(x, p):
            k = 2/(p+1); r = np.zeros(len(x)); r[0] = x[0]
            for i in range(1,len(x)): r[i] = x[i]*k + r[i-1]*(1-k)
            return r
        pmo = ema(ema(roc, 35), 20)
        sig_line = ema(pmo, 10)
        if pmo[-1] > sig_line[-1] and pmo[-2] <= sig_line[-2]: return Signal("M10","PMO","Mean Reversion",1,0.65,"PMO crossed above signal","1D",{})
        if pmo[-1] < sig_line[-1] and pmo[-2] >= sig_line[-2]: return Signal("M10","PMO","Mean Reversion",-1,0.65,"PMO crossed below signal","1D",{})
        return Signal("M10","PMO","Mean Reversion",0,0.28,"PMO no cross","1D",{})

    def b1_orb(self, df, ind):
        c = ind.get("close"); h = ind.get("high"); l = ind.get("low")
        if c is None or len(c) < 4: return Signal("B1","ORB Strategy","Breakout",0,0.0,"Need data","15m",{})
        orb_high = np.max(h[:min(4, len(h))]); orb_low = np.min(l[:min(4, len(l))])
        v = ind.get("volume"); avg_v = np.mean(v) if v is not None else 1
        vol_surge = v[-1] > avg_v * 1.3 if v is not None else False
        if c[-1] > orb_high * 1.002:
            return Signal("B1","ORB Strategy","Breakout",1, 0.80 if vol_surge else 0.62, f"ORB bullish breakout above {orb_high:.2f}. Vol:{'surge' if vol_surge else 'normal'}","15m",{"orb_high":orb_high})
        if c[-1] < orb_low * 0.998:
            return Signal("B1","ORB Strategy","Breakout",-1, 0.80 if vol_surge else 0.62, f"ORB bearish breakdown below {orb_low:.2f}","15m",{"orb_low":orb_low})
        return Signal("B1","ORB Strategy","Breakout",0,0.25,"Within ORB range","15m",{})

    def b2_volume_bo(self, df, ind):
        c = ind.get("close"); v = ind.get("volume")
        if c is None or v is None or len(v) < 20: return Signal("B2","Volume BO","Breakout",0,0.0,"Need data","15m+1D",{})
        avg_v = np.mean(v[-20:]); vol_ratio = v[-1] / max(avg_v, 1)
        high20 = np.max(ind.get("high")[-20:]) if ind.get("high") is not None else c[-1]
        if c[-1] >= high20 * 0.998 and vol_ratio > 1.5:
            return Signal("B2","Volume Breakout","Breakout",1, min(0.9, 0.6+vol_ratio*0.08), f"Price at 20-bar high with vol surge x{vol_ratio:.1f}","15m+1D",{"vol_ratio":vol_ratio})
        if vol_ratio > 1.8 and c[-1] > c[-2]:
            return Signal("B2","Volume Breakout","Breakout",1, min(0.85, 0.55+vol_ratio*0.07), f"Vol surge x{vol_ratio:.1f} on up candle","15m+1D",{"vol_ratio":vol_ratio})
        return Signal("B2","Volume Breakout","Breakout",0,0.28,f"Vol normal (x{vol_ratio:.1f})","15m+1D",{})

    def b3_52wk(self, df, ind):
        c = ind.get("close"); h = ind.get("high")
        n = min(252, len(c)) if c is not None else 0
        if c is None or n < 50: return Signal("B3","52Wk High Break","Breakout",0,0.0,"Need data","1D",{})
        wk52_high = np.max(h[-n:]) if h is not None else np.max(c[-n:])
        near_high = c[-1] >= wk52_high * 0.98
        if near_high: return Signal("B3","52Wk High","Breakout",1,0.82,f"Near 52-week high ({wk52_high:.2f}) — institutional momentum","1D",{"wk52_high":wk52_high})
        return Signal("B3","52Wk High","Breakout",0,0.28,"Not near 52wk high","1D",{})

    def b4_inside(self, df, ind):
        h = ind.get("high"); l = ind.get("low"); c = ind.get("close")
        if h is None or len(h) < 3: return Signal("B4","Inside Bar","Breakout",0,0.0,"Need data","1D",{})
        inside = h[-1] < h[-2] and l[-1] > l[-2]
        if inside:
            direction = 1 if c[-1] > (h[-2]+l[-2])/2 else -1
            return Signal("B4","Inside Bar","Breakout",direction,0.65,f"Inside bar pattern — breakout pending {'bullish' if direction>0 else 'bearish'}","1D",{})
        return Signal("B4","Inside Bar","Breakout",0,0.25,"No inside bar","1D",{})

    def b5_resistance(self, df, ind):
        c = ind.get("close"); h = ind.get("high")
        if c is None or len(c) < 20: return Signal("B5","Resistance Break","Breakout",0,0.0,"Need data","15m",{})
        pivot = np.mean(h[-20:])
        if c[-1] > pivot * 1.002: return Signal("B5","Resistance Break","Breakout",1,0.62,f"Price above mean resistance {pivot:.2f}","15m",{"resistance":pivot})
        if c[-1] < pivot * 0.998: return Signal("B5","Resistance Break","Breakout",-1,0.55,f"Price below mean support {pivot:.2f}","15m",{"support":pivot})
        return Signal("B5","Resistance Break","Breakout",0,0.28,"At resistance","15m",{})

    def b6_flag(self, df, ind):
        c = ind.get("close")
        if c is None or len(c) < 20: return Signal("B6","Flag Pattern","Breakout",0,0.0,"Need data","1D",{})
        surge = c[-10] / c[-20] - 1 if len(c) >= 20 else 0
        consolidate = np.std(c[-5:]) / c[-1] < 0.015
        if surge > 0.03 and consolidate:
            return Signal("B6","Flag Pattern","Breakout",1,0.72,f"Bull flag: surge={surge:.1%}, consolidating","1D",{})
        return Signal("B6","Flag Pattern","Breakout",0,0.28,"No flag pattern","1D",{})

    def b7_cup(self, df, ind):
        c = ind.get("close")
        if c is None or len(c) < 30: return Signal("B7","Cup Handle","Breakout",0,0.0,"Need data","1D",{})
        cup_left = np.max(c[-30:-20]); cup_bottom = np.min(c[-20:-10]); cup_right = np.max(c[-10:])
        recovery = cup_right / cup_left
        if 0.95 <= recovery <= 1.02 and cup_bottom < cup_left * 0.97:
            return Signal("B7","Cup Handle","Breakout",1,0.70,"Cup and handle pattern forming — breakout watch","1D",{"recovery":recovery})
        return Signal("B7","Cup Handle","Breakout",0,0.25,"No cup pattern","1D",{})

    def b8_squeeze_bo(self, df, ind):
        bb_w = ind.get("bb_width"); atr = ind.get("atr14"); c = ind.get("close")
        if bb_w is None or atr is None: return Signal("B8","Volatility Squeeze BO","Breakout",0,0.0,"Need indicators","15m",{})
        if len(bb_w) < 10: return Signal("B8","Volatility Squeeze BO","Breakout",0,0.0,"Insufficient","15m",{})
        momentum = c[-1] - np.mean(c[-5:])
        was_squeezed = bb_w[-3] < np.mean(bb_w[-10:]) * 0.8
        expanding = bb_w[-1] > bb_w[-2]
        if was_squeezed and expanding:
            return Signal("B8","Volatility Squeeze BO","Breakout",1 if momentum > 0 else -1, 0.75, f"Squeeze release! Momentum={'up' if momentum>0 else 'down'}","15m",{})
        return Signal("B8","Volatility Squeeze BO","Breakout",0,0.28,"No squeeze","15m",{})

    def v1_vwap_cross(self, df, ind):
        c = ind.get("close"); vwap = ind.get("vwap")
        if vwap is None or len(c) < 2: return Signal("V1","VWAP Cross","VWAP",0,0.0,"No VWAP","15m",{})
        cross_above = c[-1] > vwap[-1] and c[-2] <= vwap[-2]
        cross_below = c[-1] < vwap[-1] and c[-2] >= vwap[-2]
        if cross_above: return Signal("V1","VWAP Cross","VWAP",1,0.72,"Price crossed above VWAP — intraday bullish","15m",{"vwap":vwap[-1]})
        if cross_below: return Signal("V1","VWAP Cross","VWAP",-1,0.72,"Price crossed below VWAP — intraday bearish","15m",{"vwap":vwap[-1]})
        sig = 1 if c[-1] > vwap[-1] else -1
        dev = abs(c[-1]-vwap[-1])/vwap[-1]*100
        return Signal("V1","VWAP Cross","VWAP",sig, 0.40+min(0.20,dev*5), f"Price {'above' if sig>0 else 'below'} VWAP by {dev:.2f}%","15m",{"vwap":vwap[-1]})

    def v2_vwap_dev(self, df, ind):
        c = ind.get("close"); vwap = ind.get("vwap")
        if vwap is None: return Signal("V2","VWAP Deviation","VWAP",0,0.0,"No VWAP","15m",{})
        dev_pct = (c[-1] - vwap[-1]) / vwap[-1] * 100
        if dev_pct > 1.5:  return Signal("V2","VWAP Deviation","VWAP",-1,0.68,f"Price {dev_pct:.2f}% above VWAP — overextended","15m",{"dev":dev_pct})
        if dev_pct < -1.5: return Signal("V2","VWAP Deviation","VWAP",1,0.68,f"Price {dev_pct:.2f}% below VWAP — bounce zone","15m",{"dev":dev_pct})
        return Signal("V2","VWAP Deviation","VWAP",0,0.30,f"Normal VWAP deviation {dev_pct:.2f}%","15m",{"dev":dev_pct})

    def v3_vwap_anchored(self, df, ind):
        return self.v1_vwap_cross(df, ind)  # simplified

    def v4_vwap_bands(self, df, ind):
        c = ind.get("close"); vwap = ind.get("vwap")
        if vwap is None: return Signal("V4","VWAP Bands","VWAP",0,0.0,"No VWAP","15m",{})
        atr = ind.get("atr14"); band = atr[-1] if atr is not None else vwap[-1]*0.01
        upper = vwap[-1] + 2*band; lower = vwap[-1] - 2*band
        if c[-1] < lower: return Signal("V4","VWAP Bands","VWAP",1,0.68,"Price below VWAP lower band — buy zone","15m",{})
        if c[-1] > upper: return Signal("V4","VWAP Bands","VWAP",-1,0.68,"Price above VWAP upper band — sell zone","15m",{})
        return Signal("V4","VWAP Bands","VWAP",0,0.30,"Within VWAP bands","15m",{})

    def v5_vwap_slope(self, df, ind):
        vwap = ind.get("vwap")
        if vwap is None or len(vwap) < 5: return Signal("V5","VWAP Slope","VWAP",0,0.0,"Need data","15m",{})
        slope = (vwap[-1] - vwap[-5]) / vwap[-5] * 100
        if slope > 0.1:  return Signal("V5","VWAP Slope","VWAP",1,0.60,f"VWAP rising slope {slope:.2f}%","15m",{"slope":slope})
        if slope < -0.1: return Signal("V5","VWAP Slope","VWAP",-1,0.60,f"VWAP falling slope {slope:.2f}%","15m",{"slope":slope})
        return Signal("V5","VWAP Slope","VWAP",0,0.25,"VWAP flat","15m",{})

    def vl1_obv(self, df, ind):
        obv = ind.get("obv"); c = ind.get("close")
        if obv is None or len(obv) < 10: return Signal("VL1","OBV Trend","Volume",0,0.0,"Need data","1D",{})
        obv_rising = obv[-1] > np.mean(obv[-10:])
        price_rising = c[-1] > np.mean(c[-10:])
        if obv_rising and price_rising: return Signal("VL1","OBV Trend","Volume",1,0.65,"OBV + price both rising — institutional accumulation","1D",{})
        if not obv_rising and not price_rising: return Signal("VL1","OBV Trend","Volume",-1,0.65,"OBV + price both falling — distribution","1D",{})
        if obv_rising and not price_rising: return Signal("VL1","OBV Trend","Volume",1,0.58,"OBV rising vs falling price — bullish divergence","1D",{})
        return Signal("VL1","OBV Trend","Volume",-1,0.52,"OBV falling vs rising price — bearish divergence","1D",{})

    def vl2_vpt(self, df, ind):
        c = ind.get("close"); v = ind.get("volume")
        if c is None or v is None or len(c) < 2: return Signal("VL2","VPT","Volume",0,0.0,"Need data","1D",{})
        vpt = np.cumsum(v[1:] * (np.diff(c) / c[:-1]))
        if len(vpt) < 5: return Signal("VL2","VPT","Volume",0,0.30,"Insufficient","1D",{})
        sig = 1 if vpt[-1] > np.mean(vpt[-5:]) else -1
        return Signal("VL2","VPT","Volume",sig,0.55,f"VPT trend {'bullish' if sig>0 else 'bearish'}","1D",{})

    def vl3_adl(self, df, ind):
        c = ind.get("close"); h = ind.get("high"); l = ind.get("low"); v = ind.get("volume")
        if c is None or h is None: return Signal("VL3","A/D Line","Volume",0,0.0,"Need data","1D",{})
        mfm = ((c - l) - (h - c)) / np.where(h-l != 0, h-l, 1)
        mfv = mfm * (v if v is not None else np.ones(len(c)))
        adl = np.cumsum(mfv)
        rising = len(adl) >= 5 and adl[-1] > np.mean(adl[-5:])
        return Signal("VL3","A/D Line","Volume",1 if rising else -1, 0.58, f"A/D Line {'accumulating' if rising else 'distributing'}","1D",{})

    def vl4_cmf(self, df, ind):
        c = ind.get("close"); h = ind.get("high"); l = ind.get("low"); v = ind.get("volume")
        if c is None or h is None or len(c) < 20: return Signal("VL4","CMF","Volume",0,0.0,"Need data","15m",{})
        mfm = ((c - l) - (h - c)) / np.where(h-l != 0, h-l, 1)
        mfv = mfm * (v if v is not None else np.ones(len(c)))
        cmf = np.sum(mfv[-20:]) / np.sum(v[-20:] if v is not None else np.ones(20))
        if cmf > 0.1:  return Signal("VL4","CMF","Volume",1,0.60+min(0.2,cmf),f"CMF={cmf:.2f} — buying pressure","15m",{"cmf":cmf})
        if cmf < -0.1: return Signal("VL4","CMF","Volume",-1,0.60+min(0.2,abs(cmf)),f"CMF={cmf:.2f} — selling pressure","15m",{"cmf":cmf})
        return Signal("VL4","CMF","Volume",0,0.28,f"CMF={cmf:.2f} neutral","15m",{"cmf":cmf})

    def vl5_volume_profile(self, df, ind):
        c = ind.get("close"); v = ind.get("volume")
        if c is None or v is None or len(c) < 20: return Signal("VL5","Volume Profile","Volume",0,0.0,"Need data","1D",{})
        poc_idx = np.argmax(v[-20:]); poc_price = c[-20:][poc_idx]
        if c[-1] > poc_price * 1.002: return Signal("VL5","Volume Profile","Volume",1,0.62,f"Price above POC ({poc_price:.2f}) — buying zone","1D",{"poc":poc_price})
        if c[-1] < poc_price * 0.998: return Signal("VL5","Volume Profile","Volume",-1,0.62,f"Price below POC ({poc_price:.2f}) — selling zone","1D",{"poc":poc_price})
        return Signal("VL5","Volume Profile","Volume",0,0.30,"At POC","1D",{})

    def s1_pairs(self, df, ind):
        # Statistical: use z-score of price vs own mean
        return self.m9_zscore(df, ind)

    def s2_gap(self, df, ind):
        c = ind.get("close"); h = ind.get("high"); l = ind.get("low")
        if c is None or len(c) < 2: return Signal("S2","Gap Fill","Statistical",0,0.0,"Need data","15m",{})
        gap = (c[-1] - c[-2]) / c[-2] * 100
        if gap > 0.5:  return Signal("S2","Gap Fill","Statistical",-1,0.58,f"Gap up {gap:.2f}% — fade/fill expected","15m",{"gap":gap})
        if gap < -0.5: return Signal("S2","Gap Fill","Statistical",1,0.58,f"Gap down {gap:.2f}% — fill rally expected","15m",{"gap":gap})
        return Signal("S2","Gap Fill","Statistical",0,0.28,"No significant gap","15m",{})

    def s3_orb2(self, df, ind):
        return self.b1_orb(df, ind)

    def s4_seasonal(self, df, ind):
        import datetime
        now = datetime.datetime.now()
        # India: Budget rally Jan-Feb, results season Apr/Oct
        bull_months = {1, 2, 4, 10, 11}
        sig = 1 if now.month in bull_months else 0
        return Signal("S4","Seasonal Pattern","Statistical",sig,0.45,f"Month={now.month} {'seasonal bull' if sig>0 else 'neutral season'}","1D",{})

    def s5_event(self, df, ind):
        rsi = ind.get("rsi"); macd_h = ind.get("macd_hist")
        if rsi is None: return Signal("S5","Event Momentum","Statistical",0,0.0,"Need data","1D",{})
        # Simplified: momentum burst detection
        if rsi is not None and len(rsi) >= 3:
            rsi_surge = rsi[-1] - rsi[-3]
            if rsi_surge > 10: return Signal("S5","Event Momentum","Statistical",1,0.65,f"RSI surge +{rsi_surge:.1f} in 3 bars — event momentum","1D",{"rsi_surge":rsi_surge})
            if rsi_surge < -10: return Signal("S5","Event Momentum","Statistical",1,0.65,f"RSI drop {rsi_surge:.1f} in 3 bars — event selloff","1D",{"rsi_surge":rsi_surge})
        return Signal("S5","Event Momentum","Statistical",0,0.28,"No momentum event","1D",{})

    # ── Category G: Candlestick Patterns ──────────────────────────────────

    def g1_hammer(self, df, ind):
        if not df.get('is_hammer', pd.Series([False]*len(df))).iloc[-1] and \
           not df.get('is_shooting_star', pd.Series([False]*len(df))).iloc[-1]:
            return Signal("G1","Hammer/ShootingStar","Price Action",0,0.0,"No pattern","15m",{})
        
        is_hammer = df['is_hammer'].iloc[-1]
        c = ind.get("close"); rsi = ind.get("rsi")
        if is_hammer:
            # Hammer is bullish reversal if RSI was low
            conf = 0.72 if (rsi is not None and rsi[-1] < 40) else 0.55
            return Signal("G1","Hammer","Price Action",1,conf,"Bullish Hammer pattern detected","15m",{})
        else:
            # Shooting star is bearish reversal
            conf = 0.72 if (rsi is not None and rsi[-1] > 60) else 0.55
            return Signal("G1","Shooting Star","Price Action",-1,conf,"Bearish Shooting Star pattern detected","15m",{})

    def g2_engulfing(self, df, ind):
        bull = df.get('is_bull_engulfing', pd.Series([False]*len(df))).iloc[-1]
        bear = df.get('is_bear_engulfing', pd.Series([False]*len(df))).iloc[-1]
        if bull: return Signal("G2","Bullish Engulfing","Price Action",1,0.75,"Strong Bullish Engulfing reversal","15m",{})
        if bear: return Signal("G2","Bearish Engulfing","Price Action",-1,0.75,"Strong Bearish Engulfing reversal","15m",{})
        return Signal("G2","Engulfing","Price Action",0,0.0,"No pattern","15m",{})

    def g3_stars(self, df, ind):
        morning = df.get('is_morning_star', pd.Series([False]*len(df))).iloc[-1]
        evening = df.get('is_evening_star', pd.Series([False]*len(df))).iloc[-1]
        if morning: return Signal("G3","Morning Star","Price Action",1,0.80,"Morning Star 3-bar reversal bullish","15m",{})
        if evening: return Signal("G3","Evening Star","Price Action",-1,0.80,"Evening Star 3-bar reversal bearish","15m",{})
        return Signal("G3","Stars","Price Action",0,0.0,"No pattern","15m",{})

    def g4_doji(self, df, ind):
        if not df.get('is_doji', pd.Series([False]*len(df))).iloc[-1]:
            return Signal("G4","Doji","Price Action",0,0.0,"No Doji","15m",{})
        # Doji is neutral, but can signal reversal
        rsi = ind.get("rsi")
        if rsi is not None and rsi[-1] < 30: return Signal("G4","Doji Reversal","Price Action",1,0.58,"Oversold Doji — potential bounce","15m",{})
        if rsi is not None and rsi[-1] > 70: return Signal("G4","Doji Reversal","Price Action",-1,0.58,"Overbought Doji — potential pullback","15m",{})
        return Signal("G4","Doji","Price Action",0,0.30,"Neutral Doji (indecision)","15m",{})

    # ── Master runner ─────────────────────────────────────────────────────────

    def compute_all(self, df: pd.DataFrame, symbol: str = "", regime: str = "TRENDING", timeframe: Optional[str] = None) -> list[Signal]:
        """Run all 45 strategies. Returns list of Signal objects."""
        if df.empty or len(df) < 5:
            logger.warning(f"TITAN: insufficient data for {symbol}")
            return []

        ind = self._compute_base(df, symbol=symbol)
        signals = []
        for sid, name, cat, tf, fn in self.strategies:
            # Timeframe filter (e.g. only run '5m' strategies)
            if timeframe and timeframe not in tf:
                continue
            try:
                sig = fn(df, ind)
                if sig.signal != 0:  # Only non-neutral signals
                    signals.append(sig)
            except Exception as e:
                logger.debug(f"TITAN strategy {sid} error: {e}")

        logger.info(f"TITAN [{symbol}]: {len(signals)} signals from {len(self.strategies)} strategies")
        return signals

    def get_consensus(self, signals: list[Signal], min_confidence: float = 0.55) -> dict:
        """Aggregate signals into a single consensus decision."""
        if not signals:
            return {"signal": 0, "confidence": 0.0, "reason": "No signals", "count": 0}

        buys  = [s for s in signals if s.signal ==  1 and s.confidence >= min_confidence]
        sells = [s for s in signals if s.signal == -1 and s.confidence >= min_confidence]

        buy_score  = sum(s.confidence for s in buys)
        sell_score = sum(s.confidence for s in sells)
        total_conf = buy_score + sell_score

        if total_conf == 0:
            return {"signal": 0, "confidence": 0.0, "reason": "All signals below threshold", "count": len(signals)}

        if buy_score > sell_score:
            net_conf = buy_score / (total_conf + len(signals) * 0.3)
            return {
                "signal": 1,
                "confidence": min(0.95, net_conf),
                "reason": f"{len(buys)} buy signals (conf={buy_score:.2f}) vs {len(sells)} sell ({sell_score:.2f})",
                "top_strategy": buys[0].strategy_id if buys else "—",
                "count": len(signals),
                "buy_count": len(buys), "sell_count": len(sells),
            }
        else:
            net_conf = sell_score / (total_conf + len(signals) * 0.3)
            return {
                "signal": -1,
                "confidence": min(0.95, net_conf),
                "reason": f"{len(sells)} sell signals (conf={sell_score:.2f}) vs {len(buys)} buy ({buy_score:.2f})",
                "top_strategy": sells[0].strategy_id if sells else "—",
                "count": len(signals),
                "buy_count": len(buys), "sell_count": len(sells),
            }
