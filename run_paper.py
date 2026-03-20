#!/usr/bin/env python3
"""
AlphaZero Capital — Standalone Paper Trading Engine
run_paper.py

Runs identically to LIVE mode but routes through PaperExecutor.
No dependency on any broken imports — this file is self-contained.

Usage:
    python run_paper.py                  # starts the engine
    python run_paper.py --capital 500000 # custom capital
    python run_paper.py --interval 60    # faster iterations for testing

Flow per iteration:
  1. ORACLE  → macro context (VIX, FII, USD/INR)
  2. NEXUS   → regime detection (TRENDING/SIDEWAYS/VOLATILE/RISK_OFF)
  3. Scan    → fetch live data for ALL 50 NIFTY stocks via yfinance
  4. HERMES  → sentiment per symbol from RSS + yfinance news
  5. SIGMA   → score every stock using 8 factors
  6. CHIEF   → select top 5 with sector diversification
  7. TITAN   → run strategies on selected stocks
  8. GUARD   → risk checks (daily loss, positions, sector limits)
  9. MERCURY → paper execute with realistic slippage
  10. Write  → logs/status.json (dashboard polls this)
"""

import os, sys, json, time, logging, argparse, random, threading
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Tuple

# ── Setup ─────────────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(ROOT, 'logs'), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)-12s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(ROOT, 'logs', 'paper.log'), encoding='utf-8'),
    ]
)
logger = logging.getLogger('PAPER_ENGINE')

# ── Optional deps ─────────────────────────────────────────────────────────────

try:
    import yfinance as yf
    _YF = True
    logger.info("yfinance ✓")
except ImportError:
    _YF = False
    logger.warning("yfinance not installed — run: pip install yfinance")

try:
    import pandas as pd
    _PD = True
except ImportError:
    _PD = False

try:
    import numpy as np
    _NP = True
except ImportError:
    _NP = False

# ── Universe ──────────────────────────────────────────────────────────────────

NIFTY50 = [
    'RELIANCE','TCS','HDFCBANK','ICICIBANK','INFOSYS','HINDUNILVR','ITC',
    'KOTAKBANK','SBIN','BHARTIARTL','LT','AXISBANK','BAJFINANCE','ASIANPAINT',
    'MARUTI','SUNPHARMA','TITAN','NESTLEIND','WIPRO','ULTRACEMCO',
    'BAJAJFINSV','POWERGRID','NTPC','TATAMOTORS','TATASTEEL','HCLTECH',
    'TECHM','INDUSINDBK','HINDALCO','COALINDIA','GRASIM','DIVISLAB',
    'DRREDDY','CIPLA','APOLLOHOSP','ADANIENT','ADANIPORTS','JSWSTEEL',
    'ONGC','BPCL','EICHERMOT','HEROMOTOCO','BRITANNIA','BAJAJ-AUTO',
    'SHREECEM','UPL','VEDL','DABUR','MUTHOOTFIN','CHOLAFIN',
]

SECTORS = {
    'BANKING':  ['HDFCBANK','ICICIBANK','KOTAKBANK','AXISBANK','SBIN','INDUSINDBK'],
    'IT':       ['TCS','INFOSYS','WIPRO','HCLTECH','TECHM'],
    'FMCG':     ['HINDUNILVR','ITC','NESTLEIND','BRITANNIA','DABUR'],
    'AUTO':     ['MARUTI','TATAMOTORS','BAJAJ-AUTO','HEROMOTOCO','EICHERMOT'],
    'PHARMA':   ['SUNPHARMA','DRREDDY','CIPLA','DIVISLAB','APOLLOHOSP'],
    'ENERGY':   ['RELIANCE','ONGC','NTPC','POWERGRID','COALINDIA','BPCL'],
    'METALS':   ['TATASTEEL','HINDALCO','JSWSTEEL','VEDL'],
    'FINANCE':  ['BAJFINANCE','BAJAJFINSV','MUTHOOTFIN','CHOLAFIN'],
    'INFRA':    ['LT','ULTRACEMCO','GRASIM','ADANIPORTS','ADANIENT'],
    'CONSUMER': ['ASIANPAINT','TITAN','SHREECEM','UPL'],
    'TELECOM':  ['BHARTIARTL'],
}

SYMBOL_SECTOR = {sym: sec for sec, syms in SECTORS.items() for sym in syms}

STATUS_FILE = os.path.join(ROOT, 'logs', 'status.json')


# ═════════════════════════════════════════════════════════════════════════════
# DATA LAYER
# ═════════════════════════════════════════════════════════════════════════════

class DataFetcher:
    """Fetches real NSE data via yfinance with simulation fallback."""

    def __init__(self, cache_secs: int = 300):
        self._cache: Dict[str, Dict] = {}
        self._cache_ts: Dict[str, datetime] = {}
        self._cache_secs = cache_secs

    def get_stock_data(self, symbol: str) -> Optional[Dict]:
        """Returns dict with price, indicators, fundamental proxies."""
        now = datetime.now()
        if symbol in self._cache_ts:
            if (now - self._cache_ts[symbol]).total_seconds() < self._cache_secs:
                return self._cache[symbol]

        if _YF:
            data = self._fetch_live(symbol)
        else:
            data = self._simulate(symbol)

        if data:
            self._cache[symbol] = data
            self._cache_ts[symbol] = now
        return data

    def _fetch_live(self, symbol: str) -> Optional[Dict]:
        """Real yfinance fetch — NSE ticker format."""
        try:
            ticker = yf.Ticker(f"{symbol}.NS")
            hist   = ticker.history(period="60d", interval="1d")
            if hist is None or len(hist) < 20:
                return self._simulate(symbol)

            closes  = hist['Close'].tolist()
            volumes = hist['Volume'].tolist()
            highs   = hist['High'].tolist()
            lows    = hist['Low'].tolist()
            price   = closes[-1]
            prev    = closes[-2] if len(closes) > 1 else price
            change_pct = (price - prev) / prev * 100 if prev else 0

            # Technical indicators (manual — no ta-lib dep)
            ema20 = self._ema(closes, 20)
            ema50 = self._ema(closes, 50)
            rsi   = self._rsi(closes, 14)
            adx   = self._adx(highs, lows, closes, 14)
            atr   = self._atr(highs, lows, closes, 14)
            vol_avg = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else volumes[-1]
            vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0

            # Momentum: price vs ema50
            momentum = min(1.0, max(0.0, (price - ema50) / ema50 * 10 + 0.5)) if ema50 else 0.5
            # Trend strength from ADX
            trend_strength = min(1.0, adx / 50.0) if adx else 0.3
            # Relative strength vs NIFTY (proxy: 5d return vs 20d return)
            ret5  = (closes[-1] - closes[-6]) / closes[-6] if len(closes) > 6 else 0
            ret20 = (closes[-1] - closes[-21]) / closes[-21] if len(closes) > 21 else 0
            rs    = min(1.0, max(0.0, 0.5 + (ret5 - ret20) * 5))
            # Volume confirmation
            vol_confirm = min(1.0, vol_ratio / 2.0)
            # Volatility (normalised ATR)
            volatility = min(1.0, (atr / price * 100) / 3.0) if atr and price else 0.3

            # Fundamental proxies (from yfinance info — best-effort)
            try:
                info = ticker.info
                pe   = info.get('trailingPE', 0) or 0
                # earnings quality: lower P/E relative to sector = better
                # simple normalisation: PE 10=great(1.0), PE 50=poor(0.0)
                eq = max(0.0, min(1.0, 1.0 - (pe - 10) / 40)) if pe > 0 else 0.5
                revenue_growth = info.get('revenueGrowth', 0) or 0
                fii_proxy = min(1.0, max(0.0, 0.5 + revenue_growth))
                fundamental = {
                    'pe_ratio': round(pe, 1),
                    'revenue_growth': round(revenue_growth * 100, 1),
                    'market_cap_cr': round((info.get('marketCap', 0) or 0) / 1e7, 0),
                    'debt_to_equity': round(info.get('debtToEquity', 0) or 0, 2),
                    'roe': round((info.get('returnOnEquity', 0) or 0) * 100, 1),
                    'sector': info.get('sector', SYMBOL_SECTOR.get(symbol, 'OTHER')),
                    'industry': info.get('industry', ''),
                }
            except Exception:
                eq = 0.5; fii_proxy = 0.5
                fundamental = {'pe_ratio': 0, 'revenue_growth': 0, 'market_cap_cr': 0,
                               'debt_to_equity': 0, 'roe': 0, 'sector': SYMBOL_SECTOR.get(symbol,'OTHER')}

            return {
                'symbol':          symbol,
                'price':           round(price, 2),
                'prev_close':      round(prev, 2),
                'change_pct':      round(change_pct, 2),
                'ema20':           round(ema20, 2),
                'ema50':           round(ema50, 2),
                'rsi':             round(rsi, 1),
                'adx':             round(adx, 1),
                'atr':             round(atr, 2),
                'volume':          int(volumes[-1]),
                'volume_avg':      int(vol_avg),
                'vol_ratio':       round(vol_ratio, 2),
                # scoring factors (0–1)
                'momentum':        round(momentum, 3),
                'trend_strength':  round(trend_strength, 3),
                'relative_strength': round(rs, 3),
                'volume_confirm':  round(vol_confirm, 3),
                'volatility':      round(volatility, 3),
                'earnings_quality': round(eq, 3),
                'fii_interest':    round(fii_proxy, 3),
                'news_sentiment':  0.5,   # filled in by HERMES
                'fundamental':     fundamental,
                'closes':          [round(c, 2) for c in closes[-50:]],
                'highs':           [round(h, 2) for h in highs[-50:]],
                'lows':            [round(l, 2) for l in lows[-50:]],
                'volumes':         [int(v) for v in volumes[-50:]],
                'sector':          SYMBOL_SECTOR.get(symbol, 'OTHER'),
                'source':          'yfinance',
                'timestamp':       datetime.now().isoformat(),
            }
        except Exception as e:
            logger.debug(f"yfinance fetch failed for {symbol}: {e}")
            return self._simulate(symbol)

    def _simulate(self, symbol: str) -> Dict:
        """Deterministic simulation when yfinance unavailable."""
        rng   = random.Random(hash(symbol) % 99999)
        base  = rng.uniform(200, 4000)
        price = base * (1 + rng.uniform(-0.02, 0.02))
        rsi   = rng.uniform(35, 70)
        adx   = rng.uniform(15, 45)
        return {
            'symbol':           symbol,
            'price':            round(price, 2),
            'prev_close':       round(base, 2),
            'change_pct':       round((price - base) / base * 100, 2),
            'ema20':            round(price * 0.99, 2),
            'ema50':            round(price * 0.97, 2),
            'rsi':              round(rsi, 1),
            'adx':              round(adx, 1),
            'atr':              round(price * 0.015, 2),
            'volume':           int(rng.uniform(500_000, 5_000_000)),
            'volume_avg':       int(rng.uniform(500_000, 5_000_000)),
            'vol_ratio':        round(rng.uniform(0.5, 2.5), 2),
            'momentum':         round(rng.uniform(0.2, 0.9), 3),
            'trend_strength':   round(adx / 50, 3),
            'relative_strength': round(rng.uniform(0.2, 0.9), 3),
            'volume_confirm':   round(rng.uniform(0.2, 0.9), 3),
            'volatility':       round(rng.uniform(0.1, 0.5), 3),
            'earnings_quality': round(rng.uniform(0.3, 0.9), 3),
            'fii_interest':     round(rng.uniform(0.2, 0.8), 3),
            'news_sentiment':   0.5,
            'fundamental':      {'pe_ratio': round(rng.uniform(8, 60), 1),
                                  'revenue_growth': round(rng.uniform(-5, 25), 1),
                                  'market_cap_cr': round(rng.uniform(5000, 1500000), 0),
                                  'debt_to_equity': round(rng.uniform(0, 2), 2),
                                  'roe': round(rng.uniform(8, 35), 1),
                                  'sector': SYMBOL_SECTOR.get(symbol, 'OTHER'),
                                  'industry': ''},
            'closes':           [round(price * (1 + rng.uniform(-0.03, 0.03)), 2) for _ in range(50)],
            'highs':            [],
            'lows':             [],
            'volumes':          [],
            'sector':           SYMBOL_SECTOR.get(symbol, 'OTHER'),
            'source':           'simulation',
            'timestamp':        datetime.now().isoformat(),
        }

    # ── Indicator helpers (pure Python, no external deps) ─────────────────────

    @staticmethod
    def _ema(prices: list, period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        k = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = p * k + ema * (1 - k)
        return ema

    @staticmethod
    def _rsi(closes: list, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0)); losses.append(max(-d, 0))
        ag = sum(gains[-period:]) / period
        al = sum(losses[-period:]) / period
        if al == 0: return 100.0
        rs = ag / al
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
        if len(closes) < 2 or not highs or not lows:
            return 0.0
        trs = []
        for i in range(1, min(len(highs), len(lows), len(closes))):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i] - closes[i-1]))
            trs.append(tr)
        return sum(trs[-period:]) / min(period, len(trs)) if trs else 0.0

    @staticmethod
    def _adx(highs: list, lows: list, closes: list, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 20.0
        dx_list = []
        for i in range(1, len(closes)):
            h, l, pc = highs[i], lows[i], closes[i-1]
            dm_plus  = max(highs[i] - highs[i-1], 0) if highs[i] - highs[i-1] > lows[i-1] - lows[i] else 0
            dm_minus = max(lows[i-1] - lows[i], 0) if lows[i-1] - lows[i] > highs[i] - highs[i-1] else 0
            tr = max(h - l, abs(h - pc), abs(l - pc))
            if tr == 0: continue
            di_p = dm_plus / tr * 100
            di_m = dm_minus / tr * 100
            if di_p + di_m == 0: continue
            dx_list.append(abs(di_p - di_m) / (di_p + di_m) * 100)
        if not dx_list: return 20.0
        return sum(dx_list[-period:]) / min(period, len(dx_list))


# ═════════════════════════════════════════════════════════════════════════════
# ORACLE — Macro Intelligence
# ═════════════════════════════════════════════════════════════════════════════

class Oracle:
    def analyze(self) -> Dict:
        vix = 15.0; fii_flow = 0.0; usdinr = 84.0; spx_ret = 0.0

        if _YF:
            try: vix = yf.Ticker('^INDIAVIX').history(period='2d')['Close'].iloc[-1]
            except Exception: pass
            try:
                spx_hist = yf.Ticker('^GSPC').history(period='3d')['Close']
                if len(spx_hist) >= 2: spx_ret = (spx_hist.iloc[-1] - spx_hist.iloc[-2]) / spx_hist.iloc[-2] * 100
            except Exception: pass
            try: usdinr = yf.Ticker('USDINR=X').history(period='2d')['Close'].iloc[-1]
            except Exception: pass

        score = 0
        if vix < 15:  score += 1
        elif vix > 26: score -= 3
        elif vix > 20: score -= 1

        if fii_flow > 500: score += 1
        elif fii_flow < -500: score -= 1

        if usdinr < 84: score += 1
        elif usdinr > 88: score -= 2
        elif usdinr > 85: score -= 1

        if spx_ret > 0.5: score += 1
        elif spx_ret < -0.5: score -= 1

        if score >= 3:   bias, risk, mult = 'BULLISH', 'LOW',    1.00
        elif score >= 1: bias, risk, mult = 'BULLISH', 'MEDIUM', 0.90
        elif score == 0: bias, risk, mult = 'NEUTRAL', 'MEDIUM', 0.80
        elif score >= -2: bias, risk, mult = 'BEARISH', 'HIGH',  0.60
        else:             bias, risk, mult = 'BEARISH', 'EXTREME', 0.25

        return {'vix': round(float(vix),1), 'fii_flow_cr': round(fii_flow,0),
                'usdinr': round(float(usdinr),2), 'spx_ret': round(spx_ret,2),
                'macro_bias': bias, 'risk_level': risk, 'size_mult': mult, 'score': score}


# ═════════════════════════════════════════════════════════════════════════════
# NEXUS — Regime Detection
# ═════════════════════════════════════════════════════════════════════════════

class Nexus:
    def detect(self, stocks: List[Dict], vix: float) -> str:
        if not stocks:
            return 'SIDEWAYS'

        adxs   = [s['adx'] for s in stocks if s.get('adx', 0) > 0]
        rsis   = [s['rsi'] for s in stocks if s.get('rsi', 0) > 0]
        above  = sum(1 for s in stocks if s.get('ema20', 0) > s.get('ema50', 0))
        breadth = above / len(stocks)

        adx    = sum(adxs) / len(adxs) if adxs else 20.0
        rsi    = sum(rsis) / len(rsis) if rsis else 50.0

        votes  = {'TRENDING': 0, 'SIDEWAYS': 0, 'VOLATILE': 0, 'RISK_OFF': 0}

        if vix >= 26:   votes['RISK_OFF'] += 3
        elif vix >= 20: votes['VOLATILE'] += 2

        if adx >= 25:   votes['TRENDING'] += 2
        elif adx <= 18: votes['SIDEWAYS'] += 2
        else:           votes['TRENDING'] += 1

        if breadth >= 0.7:   votes['TRENDING'] += 1
        elif breadth <= 0.3: votes['RISK_OFF'] += 1
        else:                votes['SIDEWAYS'] += 1

        if rsi > 70 or rsi < 30: votes['VOLATILE'] += 1
        elif 40 <= rsi <= 60:    votes['SIDEWAYS'] += 1

        return max(votes, key=votes.get)


# ═════════════════════════════════════════════════════════════════════════════
# HERMES — News Sentiment
# ═════════════════════════════════════════════════════════════════════════════

class Hermes:
    POSITIVE = ['profit', 'growth', 'beat', 'surge', 'rally', 'gain', 'record',
                'acquisition', 'deal', 'buyback', 'dividend', 'approved', 'upgrade']
    NEGATIVE = ['loss', 'decline', 'fall', 'miss', 'probe', 'fraud', 'penalty',
                'downgrade', 'default', 'weak', 'slump', 'concern', 'recall']

    def score(self, symbols: List[str]) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        for sym in symbols:
            s = 0.0; hits = 0
            if _YF:
                try:
                    news = yf.Ticker(f"{sym}.NS").news or []
                    for item in news[:5]:
                        title = (item.get('title') or '').lower()
                        for w in self.POSITIVE:
                            if w in title: s += 1; hits += 1
                        for w in self.NEGATIVE:
                            if w in title: s -= 1; hits += 1
                except Exception:
                    pass
            scores[sym] = round(max(-1.0, min(1.0, s / max(hits, 1))), 3)
        overall = sum(scores.values()) / len(scores) if scores else 0.0
        return {'scores': scores, 'overall': 'POSITIVE' if overall > 0.1 else
                ('NEGATIVE' if overall < -0.1 else 'NEUTRAL'), 'score': round(overall, 3)}


# ═════════════════════════════════════════════════════════════════════════════
# SIGMA — 8-Factor Stock Scorer
# ═════════════════════════════════════════════════════════════════════════════

class Sigma:
    REGIME_WEIGHTS = {
        'TRENDING':  {'momentum':0.30,'trend_strength':0.25,'earnings_quality':0.10,
                      'relative_strength':0.15,'news_sentiment':0.05,'volume_confirm':0.10,
                      'low_volatility':0.03,'fii_interest':0.02},
        'SIDEWAYS':  {'momentum':0.10,'trend_strength':0.05,'earnings_quality':0.25,
                      'relative_strength':0.15,'news_sentiment':0.15,'volume_confirm':0.10,
                      'low_volatility':0.15,'fii_interest':0.05},
        'VOLATILE':  {'momentum':0.15,'trend_strength':0.10,'earnings_quality':0.15,
                      'relative_strength':0.10,'news_sentiment':0.10,'volume_confirm':0.10,
                      'low_volatility':0.25,'fii_interest':0.05},
        'RISK_OFF':  {'momentum':0.05,'trend_strength':0.05,'earnings_quality':0.30,
                      'relative_strength':0.10,'news_sentiment':0.10,'volume_confirm':0.05,
                      'low_volatility':0.30,'fii_interest':0.05},
        'NEUTRAL':   {'momentum':0.20,'trend_strength':0.15,'earnings_quality':0.15,
                      'relative_strength':0.15,'news_sentiment':0.10,'volume_confirm':0.10,
                      'low_volatility':0.10,'fii_interest':0.05},
    }

    def score_all(self, stocks: List[Dict], sentiment: Dict, regime: str) -> List[Dict]:
        w = self.REGIME_WEIGHTS.get(regime, self.REGIME_WEIGHTS['NEUTRAL'])
        scored = []
        for s in stocks:
            sym  = s['symbol']
            sent = sentiment.get('scores', {}).get(sym, 0.5)
            s['news_sentiment'] = (sent + 1) / 2   # -1..1 → 0..1

            score = (s.get('momentum',0)         * w['momentum'] +
                     s.get('trend_strength',0)    * w['trend_strength'] +
                     s.get('earnings_quality',0)  * w['earnings_quality'] +
                     s.get('relative_strength',0) * w['relative_strength'] +
                     s.get('news_sentiment',0.5)  * w['news_sentiment'] +
                     s.get('volume_confirm',0)    * w['volume_confirm'] +
                     (1 - s.get('volatility',0.5))* w['low_volatility'] +
                     s.get('fii_interest',0)      * w['fii_interest'])

            # Build human-readable reasons
            ta_reasons  = self._ta_reasons(s)
            fa_reasons  = self._fa_reasons(s)

            scored.append({**s, 'sigma_score': round(score, 4),
                           'ta_reasons': ta_reasons, 'fa_reasons': fa_reasons})

        return sorted(scored, key=lambda x: x['sigma_score'], reverse=True)

    def _ta_reasons(self, s: Dict) -> List[str]:
        r = []
        price, ema20, ema50 = s.get('price',0), s.get('ema20',0), s.get('ema50',0)
        rsi, adx = s.get('rsi',50), s.get('adx',20)
        vol_ratio = s.get('vol_ratio', 1.0)

        if ema20 > ema50 and price > ema20:
            r.append(f"✅ Price ₹{price} above EMA20({round(ema20,0)}) & EMA50({round(ema50,0)}) — bullish alignment")
        elif price < ema20 < ema50:
            r.append(f"⚠️ Price below both EMAs — bearish structure")

        if rsi < 35:
            r.append(f"📉 RSI {round(rsi,1)} oversold — potential reversal entry")
        elif rsi > 65:
            r.append(f"📈 RSI {round(rsi,1)} overbought — momentum extreme, trail stop tight")
        else:
            r.append(f"✅ RSI {round(rsi,1)} in healthy mid-range — room to run")

        if adx > 25:
            r.append(f"✅ ADX {round(adx,1)} strong trend — high conviction directional move")
        elif adx < 18:
            r.append(f"⚠️ ADX {round(adx,1)} weak — choppy, low conviction")

        if vol_ratio > 1.5:
            r.append(f"✅ Volume {round(vol_ratio,1)}× above average — institutional participation")
        elif vol_ratio < 0.7:
            r.append(f"⚠️ Volume below average — weak confirmation")

        atr = s.get('atr', 0)
        if atr > 0 and price > 0:
            atr_pct = atr / price * 100
            r.append(f"📊 ATR ₹{round(atr,1)} ({round(atr_pct,1)}%) — position SL range")

        return r

    def _fa_reasons(self, s: Dict) -> List[str]:
        r = []
        f = s.get('fundamental', {})
        pe  = f.get('pe_ratio', 0)
        rg  = f.get('revenue_growth', 0)
        roe = f.get('roe', 0)
        de  = f.get('debt_to_equity', 0)
        mc  = f.get('market_cap_cr', 0)
        sec = s.get('sector', 'OTHER')

        if pe > 0:
            if pe < 15:   r.append(f"✅ P/E {pe} — undervalued relative to sector")
            elif pe < 30: r.append(f"✅ P/E {pe} — fairly valued")
            else:         r.append(f"⚠️ P/E {pe} — premium valuation, needs strong growth")

        if rg > 15:   r.append(f"✅ Revenue growth {rg}% YoY — strong business momentum")
        elif rg > 5:  r.append(f"✅ Revenue growth {rg}% — steady expansion")
        elif rg < 0:  r.append(f"⚠️ Revenue declining {abs(rg)}% — monitor closely")

        if roe > 20: r.append(f"✅ ROE {roe}% — excellent capital efficiency")
        elif roe > 12: r.append(f"✅ ROE {roe}% — above average returns")

        if de > 0:
            if de < 0.5:  r.append(f"✅ Low debt/equity {de} — strong balance sheet")
            elif de > 2:  r.append(f"⚠️ High debt/equity {de} — leverage risk")

        if mc > 100000: r.append(f"🏢 Large-cap ₹{int(mc/100):,}Cr — high liquidity")
        elif mc > 20000: r.append(f"🏢 Mid-cap ₹{int(mc/100):,}Cr")

        r.append(f"🏭 Sector: {sec}")

        sent = s.get('news_sentiment', 0.5)
        if sent > 0.6:   r.append("✅ Positive news sentiment — favorable macro backdrop")
        elif sent < 0.4: r.append("⚠️ Negative news flow — watch for catalysts")

        return r


# ═════════════════════════════════════════════════════════════════════════════
# CHIEF — Portfolio Selector
# ═════════════════════════════════════════════════════════════════════════════

class Chief:
    def __init__(self, max_positions=5, max_same_sector=2):
        self.max_positions   = max_positions
        self.max_same_sector = max_same_sector

    def select(self, scored: List[Dict], regime: str) -> List[Dict]:
        """Pick top N with sector diversification."""
        sector_counts: Dict[str, int] = {}
        selected: List[Dict] = []

        for s in scored:
            if len(selected) >= self.max_positions:
                break
            sec   = s.get('sector', 'OTHER')
            count = sector_counts.get(sec, 0)
            if count >= self.max_same_sector:
                continue
            selected.append(s)
            sector_counts[sec] = count + 1

        # Fill remaining slots if diversification was too strict
        if len(selected) < self.max_positions:
            existing = {s['symbol'] for s in selected}
            for s in scored:
                if len(selected) >= self.max_positions:
                    break
                if s['symbol'] not in existing:
                    selected.append(s)
                    existing.add(s['symbol'])

        # Assign capital weights (score-proportional)
        total_score = sum(s['sigma_score'] for s in selected) or 1.0
        for s in selected:
            s['capital_weight'] = round(s['sigma_score'] / total_score, 4)

        return selected


# ═════════════════════════════════════════════════════════════════════════════
# TITAN — Signal Generation (simplified — real version in titan.py)
# ═════════════════════════════════════════════════════════════════════════════

class TitanSignals:
    def generate(self, stock: Dict, regime: str) -> Optional[Dict]:
        """
        Run strategy battery on a stock.
        Returns signal dict or None if no consensus.
        """
        price  = stock.get('price', 0)
        ema20  = stock.get('ema20', 0)
        ema50  = stock.get('ema50', 0)
        rsi    = stock.get('rsi', 50)
        adx    = stock.get('adx', 20)
        vol_r  = stock.get('vol_ratio', 1.0)
        atr    = stock.get('atr', price * 0.015) if price else 0

        signals = []
        reasons = []

        # T1 — EMA Cross
        if ema20 > ema50 and price > ema20:
            signals.append(1); reasons.append("EMA20>EMA50 bullish cross")
        elif ema20 < ema50 and price < ema20:
            signals.append(-1); reasons.append("EMA20<EMA50 bearish cross")

        # M1 — RSI Reversal
        if rsi < 35 and regime != 'RISK_OFF':
            signals.append(1); reasons.append(f"RSI {round(rsi,1)} oversold bounce")
        elif rsi > 70:
            signals.append(-1); reasons.append(f"RSI {round(rsi,1)} overbought")

        # T5 — ADX Trend Strength
        if adx > 25 and ema20 > ema50:
            signals.append(1); reasons.append(f"ADX {round(adx,1)} strong uptrend")

        # V1 — Volume Breakout
        if vol_r > 1.5 and price > ema20:
            signals.append(1); reasons.append(f"Volume {round(vol_r,1)}× surge with price breakout")

        # Regime filter
        if regime == 'RISK_OFF':
            return None
        if regime == 'VOLATILE':
            signals = []  # no new entries in volatile
            return None

        if not signals:
            return None

        buy_votes  = sum(1 for s in signals if s > 0)
        sell_votes = sum(1 for s in signals if s < 0)
        total      = len(signals)

        if buy_votes / total >= 0.6 and buy_votes >= 2:
            action     = 'BUY'
            confidence = buy_votes / total
        elif sell_votes / total >= 0.6 and sell_votes >= 2:
            action     = 'SELL'
            confidence = sell_votes / total
        else:
            return None

        stop_loss  = round(price - 2 * atr, 2)
        target     = round(price + 3 * atr, 2)

        return {
            'symbol':     stock['symbol'],
            'signal':     action,
            'action':     action,
            'confidence': round(confidence, 2),
            'price':      price,
            'stop_loss':  stop_loss,
            'target':     target,
            'rr':         round((target - price) / (price - stop_loss), 2) if price > stop_loss else 0,
            'reasons':    reasons,
            'regime':     regime,
            'source':     'TITAN',
            'timestamp':  datetime.now().strftime('%H:%M:%S'),
        }


# ═════════════════════════════════════════════════════════════════════════════
# GUARDIAN — Risk Manager
# ═════════════════════════════════════════════════════════════════════════════

class Guardian:
    def __init__(self, cfg: Dict):
        self.initial_capital      = cfg.get('initial_capital', 1_000_000)
        self.max_daily_loss_pct   = cfg.get('max_daily_loss_pct', 0.02)
        self.max_positions        = cfg.get('max_positions', 5)
        self.max_position_pct     = cfg.get('max_position_pct', 0.05)
        self.max_sector_pct       = cfg.get('max_sector_pct', 0.30)
        self.max_trades_per_day   = cfg.get('max_trades_per_day', 20)
        self.consecutive_limit    = cfg.get('consecutive_loss_limit', 3)

        self.daily_pnl            = 0.0
        self.trades_today         = 0
        self.consecutive_losses   = 0
        self.kill_switch          = False

    def check(self, signal: Dict, positions: Dict, sector_exposure: Dict,
              capital: float, size_mult: float) -> Tuple[bool, str, float]:
        """Returns (approved, reason, position_size_inr)"""
        if self.kill_switch:
            return False, "Kill switch active", 0

        daily_loss_pct = abs(min(self.daily_pnl, 0)) / self.initial_capital
        if daily_loss_pct >= self.max_daily_loss_pct:
            return False, f"Daily loss limit {daily_loss_pct:.1%}", 0

        if len(positions) >= self.max_positions:
            return False, f"Max positions {self.max_positions} reached", 0

        if self.trades_today >= self.max_trades_per_day:
            return False, "Max trades per day reached", 0

        if self.consecutive_losses >= self.consecutive_limit:
            return False, f"{self.consecutive_losses} consecutive losses — cooling off", 0

        sym = signal['symbol']
        if sym in positions:
            return False, f"Already have position in {sym}", 0

        sec = SYMBOL_SECTOR.get(sym, 'OTHER')
        sec_exp = sector_exposure.get(sec, 0.0) / capital if capital > 0 else 0
        if sec_exp >= self.max_sector_pct:
            return False, f"Sector {sec} at {sec_exp:.1%} limit", 0

        position_size = capital * self.max_position_pct * size_mult
        return True, "APPROVED", round(position_size, 0)

    def record_trade(self, pnl: float):
        self.daily_pnl    += pnl
        self.trades_today += 1
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def reset_daily(self):
        self.daily_pnl  = 0.0
        self.trades_today = 0


# ═════════════════════════════════════════════════════════════════════════════
# MERCURY — Paper Executor
# ═════════════════════════════════════════════════════════════════════════════

class Mercury:
    """Paper executor with realistic slippage + position tracking."""

    def __init__(self):
        self.positions:     Dict[str, Dict] = {}
        self.trade_history: List[Dict]      = []
        self.total_trades    = 0
        self.total_slippage  = 0.0

    def execute(self, signal: Dict, position_size: float) -> Optional[Dict]:
        sym   = signal['symbol']
        price = signal['price']
        if price <= 0 or position_size <= 0:
            return None

        # Base properties for typical NIFTY50 depth
        action = signal.get('signal', 'BUY').upper()
        tick_size = 0.05
        avg_depth_per_level = random.randint(500, 2000)
        
        qty = int(position_size / price)
        if qty < 1:
            return None
            
        remaining = qty
        total_cost = 0.0
        current_level_price = price
        
        # Base spread 
        spread_ticks = random.randint(1, 3)
        current_level_price += (spread_ticks * tick_size) if action == 'BUY' else -(spread_ticks * tick_size)
            
        while remaining > 0:
            filled_at_level = min(remaining, avg_depth_per_level)
            total_cost += (filled_at_level * current_level_price)
            remaining -= filled_at_level
            
            if remaining > 0:
                current_level_price += tick_size if action == 'BUY' else -tick_size
                avg_depth_per_level = int(avg_depth_per_level * 0.8)
                if avg_depth_per_level < 50:
                    avg_depth_per_level = 50

        fill = round(total_cost / qty, 2)
        slip_bps = int(abs(fill - price) / price * 10000)

        self.total_slippage += slip_bps
        self.total_trades   += 1

        pos = {
            'symbol':       sym,
            'side':         signal.get('signal', 'BUY'),
            'quantity':     qty,
            'entry_price':  fill,
            'current_price': fill,
            'stop_loss':    signal.get('stop_loss', fill * 0.97),
            'target':       signal.get('target', fill * 1.04),
            'unrealised_pnl': 0.0,
            'pnl_pct':      0.0,
            'source':       signal.get('source', 'TITAN'),
            'entry_time':   datetime.now().isoformat(),
            'reasons':      signal.get('reasons', []),
            'confidence':   signal.get('confidence', 0.6),
            'regime':       signal.get('regime', 'NEUTRAL'),
            'slippage_bps': slip_bps,
            'ta_reasons':   signal.get('ta_reasons', []),
            'fa_reasons':   signal.get('fa_reasons', []),
        }
        self.positions[sym] = pos
        self.trade_history.append({**pos, 'event': 'OPEN', 'fill': fill})
        logger.info(f"[PAPER] BUY {sym} ×{qty} @₹{fill} (slip={slip_bps}bps)")
        return pos

    def update_prices(self, prices: Dict[str, float]) -> List[Dict]:
        """Update positions with latest prices, return list of closed positions."""
        closed = []
        for sym, pos in list(self.positions.items()):
            cp = prices.get(sym, pos['entry_price'])
            ep = pos['entry_price']
            pnl = (cp - ep) * pos['quantity']
            pnl_pct = (cp - ep) / ep * 100
            pos['current_price'] = round(cp, 2)
            pos['unrealised_pnl'] = round(pnl, 0)
            pos['pnl_pct'] = round(pnl_pct, 2)

            # Stop-loss check
            if cp <= pos['stop_loss']:
                closed.append(self._close(sym, cp, 'STOP_HIT'))
            # Target check
            elif cp >= pos['target']:
                closed.append(self._close(sym, cp, 'TARGET_HIT'))

        return [c for c in closed if c]

    def _close(self, sym: str, price: float, reason: str) -> Optional[Dict]:
        if sym not in self.positions:
            return None
        pos = self.positions.pop(sym)
        pnl = round((price - pos['entry_price']) * pos['quantity'], 0)
        result = {**pos, 'close_price': price, 'pnl': pnl, 'close_reason': reason,
                  'close_time': datetime.now().isoformat(), 'event': 'CLOSE'}
        self.trade_history.append(result)
        logger.info(f"[PAPER] CLOSE {sym} @₹{price} → P&L ₹{pnl:+,.0f} ({reason})")
        return result

    def get_stats(self) -> Dict:
        avg_slip = self.total_slippage / self.total_trades if self.total_trades else 0
        closed   = [t for t in self.trade_history if t.get('event') == 'CLOSE']
        wins     = [t for t in closed if t.get('pnl', 0) > 0]
        total_pnl= sum(t.get('pnl', 0) for t in closed)
        return {'total_trades': self.total_trades, 'avg_slippage_bps': round(avg_slip, 1),
                'win_rate': round(len(wins) / max(len(closed), 1), 3),
                'total_pnl': round(total_pnl, 0), 'open_positions': len(self.positions)}


# ═════════════════════════════════════════════════════════════════════════════
# KARMA — Learning (weight updater)
# ═════════════════════════════════════════════════════════════════════════════

class Karma:
    def __init__(self):
        self.strategy_weights = {'trend': 1.0, 'reversion': 1.0, 'breakout': 1.0, 'volume': 1.0}
        self.episodes = 0

    def learn(self, signal: Dict, pnl: float):
        self.episodes += 1
        reward = 1 if pnl > 0 else -1
        src    = signal.get('source', 'trend').lower()
        key    = 'trend' if 'trend' in src or 'ema' in src else \
                 'reversion' if 'rsi' in src or 'bb' in src else \
                 'breakout' if 'breakout' in src or 'adx' in src else 'volume'
        self.strategy_weights[key] = max(0.1, self.strategy_weights[key] + 0.01 * reward)
        # Normalise
        total = sum(self.strategy_weights.values())
        for k in self.strategy_weights:
            self.strategy_weights[k] = round(self.strategy_weights[k] / total * 4, 3)


# ═════════════════════════════════════════════════════════════════════════════
# LENS — Performance Tracker
# ═════════════════════════════════════════════════════════════════════════════

class Lens:
    def __init__(self):
        self.trades:        List[Dict] = []
        self.total_pnl      = 0.0
        self.winning_trades = 0
        self.losing_trades  = 0

    def record(self, trade: Dict):
        self.trades.append(trade)
        pnl = trade.get('pnl', 0)
        self.total_pnl += pnl
        if pnl > 0: self.winning_trades += 1
        else:       self.losing_trades  += 1

    def summary(self) -> Dict:
        total = self.winning_trades + self.losing_trades
        return {'total_pnl': round(self.total_pnl, 0),
                'total_trades': total,
                'win_rate': round(self.winning_trades / max(total, 1), 3)}


# ═════════════════════════════════════════════════════════════════════════════
# PAPER ENGINE — Main Orchestrator
# ═════════════════════════════════════════════════════════════════════════════

class PaperEngine:
    def __init__(self, cfg: Dict):
        self.cfg         = cfg
        self.start_time  = datetime.now()
        self.iteration   = 0
        self.running     = False

        # Agents
        self.fetcher  = DataFetcher(cache_secs=cfg.get('cache_secs', 300))
        self.oracle   = Oracle()
        self.nexus    = Nexus()
        self.hermes   = Hermes()
        self.sigma    = Sigma()
        self.chief    = Chief(max_positions=cfg.get('max_positions', 5))
        self.titan    = TitanSignals()
        self.guardian = Guardian(cfg)
        self.mercury  = Mercury()
        self.karma    = Karma()
        self.lens     = Lens()

        # State
        self.macro_context: Dict = {}
        self.regime:         str = 'SIDEWAYS'
        self.selected_stocks: List[Dict] = []
        self.recent_signals:  List[Dict] = []
        self.activity_log:    List[str]  = []
        self.agent_status:    Dict       = {
            n: {'active': True, 'cycles': 0, 'last': '—'}
            for n in ['ORACLE','NEXUS','HERMES','SIGMA','CHIEF',
                      'TITAN','GUARDIAN','MERCURY','KARMA','LENS']
        }

        logger.info(f"PaperEngine ready — capital ₹{cfg['initial_capital']:,.0f}")

    def log(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        entry = f"[{ts}] {msg}"
        self.activity_log.append(entry)
        self.activity_log = self.activity_log[-200:]

    def run(self):
        self.running = True
        interval     = self.cfg.get('interval', 300)
        logger.info(f"▶  Starting paper trading loop (every {interval}s)\n")
        self.log("🚀 AlphaZero Paper Engine started")
        while self.running:
            try:
                self._run_iteration()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Iteration error: {e}", exc_info=True)
                self.log(f"⚠️ Iteration error: {e}")
            self._write_state()
            if self.running:
                time.sleep(interval)
        self.log("⛔ Engine stopped")
        self._write_state()

    def _run_iteration(self):
        self.iteration += 1
        t0 = time.time()
        logger.info(f"\n{'─'*60}\nIteration {self.iteration}  |  {datetime.now().strftime('%H:%M:%S IST')}")
        self.log(f"📊 Starting iteration {self.iteration}")

        # ── 1. ORACLE: macro context ──────────────────────────────────────────
        self.macro_context = self.oracle.analyze()
        self.agent_status['ORACLE']['cycles'] += 1
        self.agent_status['ORACLE']['last'] = f"VIX={self.macro_context['vix']} bias={self.macro_context['macro_bias']}"
        logger.info(f"  🔭 ORACLE: {self.macro_context['macro_bias']} | VIX={self.macro_context['vix']} | mult={self.macro_context['size_mult']}")
        self.log(f"🔭 ORACLE: {self.macro_context['macro_bias']}, VIX={self.macro_context['vix']}, size×{self.macro_context['size_mult']}")

        # ── 2. Scan all NIFTY50 stocks ────────────────────────────────────────
        logger.info(f"  📡 Scanning {len(NIFTY50)} stocks...")
        self.log(f"📡 Scanning {len(NIFTY50)} NIFTY50 stocks...")
        all_stocks = []
        for sym in NIFTY50:
            d = self.fetcher.get_stock_data(sym)
            if d:
                all_stocks.append(d)
        logger.info(f"  ✓ Fetched {len(all_stocks)} stocks")

        # ── 3. NEXUS: regime ─────────────────────────────────────────────────
        self.regime = self.nexus.detect(all_stocks, self.macro_context['vix'])
        self.agent_status['NEXUS']['cycles'] += 1
        self.agent_status['NEXUS']['last'] = self.regime
        logger.info(f"  🔮 NEXUS: {self.regime}")
        self.log(f"🔮 NEXUS regime: {self.regime}")

        # ── 4. HERMES: sentiment ──────────────────────────────────────────────
        sentiment = self.hermes.score(NIFTY50[:20])  # cap for speed
        self.agent_status['HERMES']['cycles'] += 1
        self.agent_status['HERMES']['last'] = sentiment.get('overall', 'NEUTRAL')

        # ── 5. SIGMA: score all stocks ────────────────────────────────────────
        scored = self.sigma.score_all(all_stocks, sentiment, self.regime)
        self.agent_status['SIGMA']['cycles'] += 1
        self.agent_status['SIGMA']['last'] = f"Top: {scored[0]['symbol'] if scored else '—'}"
        top5_syms = [s['symbol'] for s in scored[:5]]
        logger.info(f"  📊 SIGMA top 5: {top5_syms}")
        self.log(f"📊 SIGMA ranked top 5: {', '.join(top5_syms)}")

        # ── 6. CHIEF: select portfolio ────────────────────────────────────────
        self.selected_stocks = self.chief.select(scored, self.regime)
        self.agent_status['CHIEF']['cycles'] += 1
        selected_syms = [s['symbol'] for s in self.selected_stocks]
        self.agent_status['CHIEF']['last'] = ', '.join(selected_syms)
        logger.info(f"  🎯 CHIEF selected: {selected_syms}")
        self.log(f"🎯 CHIEF portfolio: {', '.join(selected_syms)}")

        # ── 7. Update prices in existing positions ────────────────────────────
        prices = {s['symbol']: s['price'] for s in all_stocks}
        closed = self.mercury.update_prices(prices)
        for trade in closed:
            self.lens.record(trade)
            self.karma.learn(trade, trade.get('pnl', 0))
            pnl_str = f"₹{trade['pnl']:+,.0f}" if trade.get('pnl') else ""
            self.log(f"{'✅' if trade.get('pnl',0)>0 else '❌'} CLOSED {trade['symbol']} → {trade['close_reason']} {pnl_str}")

        # ── 8. TITAN + GUARDIAN + MERCURY: generate & execute signals ────────
        capital     = self.cfg['initial_capital'] + self.lens.summary()['total_pnl']
        size_mult   = self.macro_context.get('size_mult', 1.0)
        sector_exp: Dict[str, float] = {}
        for sym, pos in self.mercury.positions.items():
            sec = SYMBOL_SECTOR.get(sym, 'OTHER')
            sector_exp[sec] = sector_exp.get(sec, 0) + pos['entry_price'] * pos['quantity']

        new_signals = []
        for stock in self.selected_stocks:
            sym    = stock['symbol']
            signal = self.titan.generate(stock, self.regime)
            if not signal:
                continue

            # Attach analysis reasons to signal
            signal['ta_reasons'] = stock.get('ta_reasons', [])
            signal['fa_reasons'] = stock.get('fa_reasons', [])

            approved, reason, pos_size = self.guardian.check(
                signal, self.mercury.positions, sector_exp, capital, size_mult
            )

            if approved:
                result = self.mercury.execute(signal, pos_size)
                if result:
                    self.guardian.record_trade(0)
                    new_signals.append({**signal, 'status': 'EXECUTED',
                                        'position_size': round(pos_size, 0)})
                    self.log(f"⚡ {sym} {signal['signal']} @₹{signal['price']} | conf={signal['confidence']} | ₹{pos_size:,.0f}")
            else:
                new_signals.append({**signal, 'status': 'BLOCKED', 'block_reason': reason})
                logger.info(f"  ⛔ {sym} blocked: {reason}")

            self.recent_signals.insert(0, new_signals[-1])

        self.recent_signals = self.recent_signals[:50]
        self.agent_status['TITAN']['cycles']   += 1
        self.agent_status['GUARDIAN']['cycles'] += 1
        self.agent_status['MERCURY']['cycles']  += 1
        self.agent_status['KARMA']['cycles']    += 1

        elapsed = round(time.time() - t0, 1)
        logger.info(f"  ✓ Done in {elapsed}s | {len(new_signals)} signals | {len(self.mercury.positions)} open positions")
        self.log(f"✓ Iteration {self.iteration} done in {elapsed}s — {len(new_signals)} signals")

    def _write_state(self):
        """Write full state to logs/status.json for dashboard polling."""
        lens = self.lens.summary()
        merc = self.mercury.get_stats()
        cap  = self.cfg['initial_capital']
        uptime = int((datetime.now() - self.start_time).total_seconds())

        positions_list = []
        for sym, pos in self.mercury.positions.items():
            positions_list.append({
                'symbol':        sym,
                'side':          pos.get('side', 'BUY'),
                'quantity':      pos.get('quantity', 0),
                'entry_price':   pos.get('entry_price', 0),
                'current_price': pos.get('current_price', 0),
                'stop_loss':     pos.get('stop_loss', 0),
                'target':        pos.get('target', 0),
                'unrealised_pnl': pos.get('unrealised_pnl', 0),
                'pnl_pct':       pos.get('pnl_pct', 0),
                'source':        pos.get('source', 'TITAN'),
                'confidence':    pos.get('confidence', 0),
                'ta_reasons':    pos.get('ta_reasons', []),
                'fa_reasons':    pos.get('fa_reasons', []),
                'entry_time':    pos.get('entry_time', ''),
                'regime':        pos.get('regime', ''),
            })

        state = {
            'system': {
                'status':    'RUNNING' if self.running else 'STOPPED',
                'mode':      'PAPER',
                'iteration': self.iteration,
                'uptime_s':  uptime,
                'symbols':   NIFTY50,
                'updated':   datetime.now().isoformat(),
            },
            'portfolio': {
                'initial_capital': cap,
                'current_value':   cap + lens['total_pnl'],
                'daily_pnl':       self.guardian.daily_pnl,
                'daily_pnl_pct':   self.guardian.daily_pnl / cap if cap else 0,
                'total_pnl':       lens['total_pnl'],
                'total_trades':    lens['total_trades'],
                'open_positions':  len(self.mercury.positions),
                'win_rate':        lens['win_rate'],
                'avg_slippage':    merc['avg_slippage_bps'],
            },
            'regime':          self.regime,
            'sentiment':       'NEUTRAL',
            'vix':             self.macro_context.get('vix', 0),
            'macro_bias':      self.macro_context.get('macro_bias', 'NEUTRAL'),
            'macro_risk':      self.macro_context.get('risk_level', 'MEDIUM'),
            'fii_flow_cr':     self.macro_context.get('fii_flow_cr', 0),
            'usdinr':          self.macro_context.get('usdinr', 0),
            'oracle_size_mult': self.macro_context.get('size_mult', 1.0),
            'positions':       positions_list,
            'selected_stocks': [
                {'symbol': s['symbol'], 'score': s.get('sigma_score', 0),
                 'sector': s.get('sector', ''), 'price': s.get('price', 0),
                 'change_pct': s.get('change_pct', 0),
                 'capital_weight': s.get('capital_weight', 0)}
                for s in self.selected_stocks
            ],
            'recent_signals':  self.recent_signals[:20],
            'activity_log':    self.activity_log[-30:],
            'agents':          self.agent_status,
            'risk': {
                'kill_switch':        self.guardian.kill_switch,
                'daily_loss_pct':     abs(min(self.guardian.daily_pnl, 0)) / cap,
                'trades_today':       self.guardian.trades_today,
                'consecutive_losses': self.guardian.consecutive_losses,
            },
            'karma_weights': self.karma.strategy_weights,
        }

        try:
            tmp = STATUS_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(state, f, indent=2, default=str)
            os.replace(tmp, STATUS_FILE)
        except Exception as e:
            logger.warning(f"State write failed: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# API SERVER (minimal Flask — dashboard polling)
# ═════════════════════════════════════════════════════════════════════════════

def start_api_server(port: int = 5001):
    """
    Minimal API server so dashboard can poll /api/status.
    Runs in a daemon thread — does not block the engine.
    """
    try:
        from flask import Flask, jsonify, send_from_directory
        from flask_cors import CORS
    except ImportError:
        logger.warning("Flask/flask-cors not installed — API server disabled")
        logger.warning("Install: pip install flask flask-cors")
        return

    app = Flask(__name__)
    CORS(app)

    @app.route('/api/status')
    def status():
        try:
            with open(STATUS_FILE) as f:
                return jsonify(json.load(f))
        except Exception:
            return jsonify({'system': {'status': 'STARTING'}}), 200

    @app.route('/api/stock/<symbol>')
    def stock_detail(symbol):
        try:
            with open(STATUS_FILE) as f:
                state = json.load(f)
            # Find in positions or selected_stocks
            for pos in state.get('positions', []):
                if pos['symbol'] == symbol:
                    return jsonify(pos)
            for s in state.get('selected_stocks', []):
                if s['symbol'] == symbol:
                    return jsonify(s)
            return jsonify({'symbol': symbol, 'error': 'not found'}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/')
    @app.route('/dashboard')
    def dashboard():
        dash_dir = os.path.join(ROOT, 'dashboard')
        if os.path.exists(os.path.join(dash_dir, 'index.html')):
            return send_from_directory(dash_dir, 'index.html')
        return "<h1>AlphaZero Paper Engine Running</h1><p>Dashboard: dashboard/index.html</p>"

    import logging as _log
    _log.getLogger('werkzeug').setLevel(_log.WARNING)
    thread = threading.Thread(
        target=lambda: app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False),
        daemon=True
    )
    thread.start()
    logger.info(f"API server → http://localhost:{port}/api/status")
    logger.info(f"Dashboard → http://localhost:{port}/")


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AlphaZero Capital — Paper Trading Engine')
    parser.add_argument('--capital',  type=float, default=1_000_000, help='Initial capital in INR')
    parser.add_argument('--interval', type=int,   default=300,       help='Iteration interval seconds')
    parser.add_argument('--positions',type=int,   default=5,         help='Max open positions')
    parser.add_argument('--port',     type=int,   default=5001,      help='API server port')
    parser.add_argument('--no-api',   action='store_true',           help='Disable API server')
    args = parser.parse_args()

    cfg = {
        'initial_capital':      args.capital,
        'interval':             args.interval,
        'max_positions':        args.positions,
        'max_daily_loss_pct':   0.02,
        'max_position_pct':     0.05,
        'max_sector_pct':       0.30,
        'max_trades_per_day':   20,
        'consecutive_loss_limit': 3,
        'cache_secs':           300,
    }

    if not args.no_api:
        start_api_server(args.port)

    engine = PaperEngine(cfg)
    engine.run()
