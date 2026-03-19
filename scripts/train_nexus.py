"""
scripts/train_nexus.py  —  AlphaZero Capital
NEXUS Causal Regime Classifier — Dynamic Universe + Causal Reasoning

WHY DYNAMIC GAINERS/LOSERS INSTEAD OF HARDCODED STOCKS
=======================================================
Old version trained on 20 hardcoded NIFTY 50 stocks.

Problem:
  TCS on a normal IT day tells you nothing about RISK_OFF.
  HDFC Bank during sideways banking tells you nothing about VOLATILE.
  Average stocks in average sessions produce noise, not signal.

New version trains on TOP 50 GAINERS and TOP 50 LOSERS from the full
NIFTY 500 universe, every single trading day.

Why this is far better:
  1. Extreme movers have clear causes.
     A stock up 8% almost always has a reason:
       earnings beat, FII buying, sector rotation, results surprise.
     A stock down 7% also has a reason:
       fraud probe, rating cut, global contagion, results miss.
     These cause-effect pairs are exactly what the model learns.

  2. The model learns CAUSE -> REGIME, not just INDICATOR -> LABEL.
     Examples captured in the 14 causal features:
       avg_top50_ret = +5%   means strong broad buying    -> TRENDING
       loser_pct = 60%       means widespread selling     -> RISK_OFF
       sector_dispersion=hi  means rotation happening     -> TRENDING
       SPX prev -2% + VIX>22 means global selloff carried -> RISK_OFF
       budget day positive   means macro event catalyst   -> TRENDING

  3. Universe stays current.
     Today's movers are tomorrow's training examples.
     The model stays calibrated to what the market cares about NOW.

CAUSAL FEATURES (14 per trading day)
=====================================
  adx              NIFTY trend strength (0-60)
  rsi              NIFTY momentum (0-100)
  vix              India VIX
  atr_norm         NIFTY normalised volatility
  cev              price vs EMA20 deviation %
  gainer_pct       fraction of NIFTY500 up >2% today
  loser_pct        fraction of NIFTY500 down >2% today
  avg_top50_ret    average return of top-50 gainers (%)
  avg_bot50_ret    average return of top-50 losers (%)
  sector_disp      std of sector median returns (rotation signal)
  spx_prev_ret     S&P 500 previous day return (global carry)
  usdinr_change    USD/INR daily change (INR stress)
  news_sentiment   RSS headline sentiment proxy [-1, +1]
  event_flag       known macro event: -1=negative, 0=none, +1=positive

HOW DOWNLOAD WORKS
==================
Round 1 (first run, ~5-8 minutes):
  a) Fetch NIFTY 500 constituent list live from NSE website
  b) Download 5yr daily close for all ~500 symbols (50 per batch)
  c) Download macro: NIFTY, VIX, SPX, USD/INR, Crude
  d) For each trading day: rank all 500 stocks by return
     Extract top-50 gainers + top-50 losers
     Compute 14 causal features from those extremes
  e) Label each day with causal voting rule
  f) Train XGBoost -> save model + parquet cache

Round 2+ (every retrain_every days, ~2 minutes):
  a) Download only NEW days since last parquet date (incremental)
  b) Append to existing price matrix
  c) Recompute gainers/losers for new dates only
  d) Retrain on full growing history

USAGE
=====
  python scripts/train_nexus.py              # run forever, retrain weekly
  python scripts/train_nexus.py --once       # train once, exit
  python scripts/train_nexus.py --fresh      # re-download everything
  python scripts/train_nexus.py --top-n 100  # use top 100 instead of 50
"""

from __future__ import annotations
import argparse, json, logging, os, re, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple
import numpy as np
import pandas as pd
try:
    import requests
except ImportError:
    print("WARNING: 'requests' library not found. NSE universe fetch will fail.")
    requests = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT       = Path(__file__).resolve().parents[1]
CACHE_DIR  = ROOT / "data" / "cache" / "nexus"
MODEL_PATH = str(ROOT / "models" / "nexus_regime.json")
META_PATH  = str(ROOT / "models" / "nexus_meta.json")
PRICES_PQ  = str(CACHE_DIR / "prices.parquet")
FEAT_PQ    = str(CACHE_DIR / "features.parquet")
UNIVERSE_F = str(CACHE_DIR / "universe.json")
MACRO_PQ   = str(CACHE_DIR / "macro.parquet")
EXPLAIN_PQ = str(CACHE_DIR / "movement_explanations.parquet")

for _d in [ROOT / "logs", ROOT / "models", CACHE_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(ROOT / "logs" / "nexus_training.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("NEXUS-Train")

# ---------------------------------------------------------------------------
# Known macro events — these teach the model WHAT CAUSED the regime
# event_flag: -1 = negative shock, 0 = neutral/scheduled, +1 = positive
# ---------------------------------------------------------------------------
KNOWN_EVENTS: Dict[str, int] = {
    # Negative shocks
    "2020-03-23": -1,  # COVID crash bottom
    "2021-03-04": -1,  # US bond yield spike
    "2022-05-04": -1,  # RBI emergency rate hike (40bps surprise)
    "2022-06-13": -1,  # US CPI shock (highest since 1981)
    "2022-09-28": -1,  # UK pension crisis
    "2022-10-03": -1,  # Global bonds rout
    "2023-03-10": -1,  # SVB collapse
    "2023-03-15": -1,  # Credit Suisse crisis
    # Budget days (usually positive)
    "2021-02-01":  1,
    "2022-02-01":  1,
    "2023-02-01":  1,
    "2024-02-01":  1,
    "2025-02-01":  1,
    # Election result (2024 - surprise hung parliament fear initially)
    "2024-06-04": -1,
    "2024-06-05":  1,  # recovery
    # RBI policy meetings (neutral)
    "2021-04-07":  0, "2021-06-04":  0, "2021-08-06":  0,
    "2021-10-08":  0, "2021-12-08":  0, "2022-02-10":  0,
    "2022-04-08":  0, "2022-06-08": -1, "2022-08-05": -1,
    "2022-09-30": -1, "2022-12-07": -1,
    "2023-02-08":  0, "2023-04-06":  0, "2023-06-08":  0,
    "2023-08-10":  0, "2023-10-06":  0, "2023-12-08":  0,
    "2024-02-08":  0, "2024-04-05":  0, "2024-06-07":  0,
    "2024-08-08":  0, "2024-10-09":  0, "2024-12-06":  0,
    "2025-02-07":  0,
}

FEATURE_NAMES = [
    "adx", "rsi", "vix", "vix_delta", "atr_norm", "cev",
    "gainer_pct", "loser_pct", "adv_decl_ratio", "gap_pct",
    "avg_top50_ret", "avg_bot50_ret",
    "rolling_vol_5d", "rolling_vol_10d",
    "sector_rot_strength", "spx_prev_ret",
    "usdinr_change", "news_sentiment", "event_flag",
]

# Sector assignment by keyword (for sector_disp feature)
_SECTOR_KW: Dict[str, List[str]] = {
    "BANKING":  ["BANK","HDFC","ICICI","AXIS","KOTAK","INDUSIND","FEDERAL",
                 "IDFC","BANDHAN","PNB","CANARA","BARODA","UNION"],
    "IT":       ["TCS","INFY","WIPRO","HCLT","TECHM","LTIM","MPHASIS",
                 "COFORGE","OFSS","KPIT","TATAELX","PERSISTENT"],
    "PHARMA":   ["PHARMA","CIPLA","DRREDDY","DIVISLAB","SUNPHARMA","APOLLOHOSP",
                 "BIOCON","ALKEM","IPCALAB","TORNTPHARM","AUROPHARMA"],
    "AUTO":     ["MARUTI","TATAMOTORS","M&M","BAJAJ","EICHER","HERO",
                 "TVS","ASHOK","ESCORTS"],
    "ENERGY":   ["NTPC","POWER","TATAPOWER","ADANIGREEN","ONGC","IOC",
                 "BPCL","GAIL","PFC","REC","OIL"],
    "METALS":   ["TATASTEEL","HINDALCO","JSWSTEEL","VEDL","HINDZINC",
                 "NATIONALUM","NMDC","SAIL"],
    "FMCG":     ["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR",
                 "MARICO","GODREJCP","COLPAL","TATACONSUM"],
    "FINANCE":  ["BAJFINANCE","BAJAJFINSV","CHOLAFIN","MUTHOOTFIN",
                 "LICSGFIN","MANAPPURAM","CANFINHOME"],
    "INFRA":    ["LT","SIEMENS","ABB","BHEL","CUMMINSIND","THERMAX",
                 "VOLTAS","HAVELLS","POLYCAB"],
}


def _sector(sym: str) -> str:
    su = sym.upper()
    for sec, keywords in _SECTOR_KW.items():
        if any(k in su for k in keywords):
            return sec
    return "OTHER"


# ===========================================================================
# 1. FETCH NIFTY 500 UNIVERSE (dynamic, live from NSE)
# ===========================================================================

def fetch_universe() -> List[str]:
    """
    Download live NIFTY 500 constituents from NSE CSV.
    Falls back to cached JSON, then to a curated 120-stock list.
    """
    try:
        import requests
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        r   = requests.get(url, timeout=20,
                           headers={"User-Agent": "Mozilla/5.0 AlphaZero/4.0",
                                    "Referer": "https://www.nseindia.com"})
        if r.status_code == 200:
            import io, csv
            reader  = csv.DictReader(io.StringIO(r.text))
            symbols = [
                (row.get("Symbol") or row.get("SYMBOL") or "").strip()
                for row in reader
            ]
            symbols = [s for s in symbols if s]
            if len(symbols) >= 100:
                logger.info("NSE NIFTY500 universe: %d symbols", len(symbols))
                with open(UNIVERSE_F, "w") as f:
                    json.dump(symbols, f)
                return symbols
    except Exception as exc:
        logger.warning("NSE universe fetch failed: %s", exc)

    # Try cached
    if os.path.exists(UNIVERSE_F):
        with open(UNIVERSE_F) as f:
            syms = json.load(f)
        if len(syms) >= 50:
            logger.info("Using cached universe: %d symbols", len(syms))
            return syms

    # Hardcoded fallback (120 most liquid NSE stocks)
    fallback = [
        "HDFCBANK","ICICIBANK","SBIN","AXISBANK","KOTAKBANK","INDUSINDBK",
        "FEDERALBNK","IDFCFIRSTB","BANDHANBNK","PNB","BANKBARODA","CANBK",
        "TCS","INFY","WIPRO","HCLTECH","TECHM","LTIM","MPHASIS","COFORGE",
        "PERSISTENT","OFSS","KPITTECH","TATAELXSI",
        "RELIANCE","ONGC","IOC","BPCL","GAIL","OIL","MGL","IGL",
        "MARUTI","TATAMOTORS","M&M","BAJAJ-AUTO","EICHERMOT","HEROMOTOCO",
        "TVSMOTOR","ASHOKLEY","ESCORTS",
        "SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","APOLLOHOSP","AUROPHARMA",
        "TORNTPHARM","BIOCON","ALKEM","IPCALAB",
        "HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR","MARICO","GODREJCP",
        "COLPAL","TATACONSUM","VBL",
        "BAJFINANCE","BAJAJFINSV","CHOLAFIN","MUTHOOTFIN","LICSGFIN","PNBHOUSING",
        "MANAPPURAM","CANFINHOME","AAVAS","M&MFIN",
        "TATASTEEL","HINDALCO","JSWSTEEL","VEDL","HINDZINC","NATIONALUM",
        "NMDC","SAIL",
        "LT","SIEMENS","ABB","BHEL","CUMMINSIND","THERMAX","VOLTAS",
        "HAVELLS","POLYCAB","KEI",
        "ULTRACEMCO","GRASIM","AMBUJACEM","ACC","SHREECEM","DALMIACEMENTB",
        "NTPC","POWERGRID","TATAPOWER","ADANIGREEN","TORNTPOWER","CESC","PFC","REC",
        "BHARTIARTL","IDEA","INDUSTOWER",
        "TITAN","DMART","ZOMATO","NYKAA","INDHOTEL","JUBLFOOD",
        "DLF","GODREJPROP","OBEROIRLTY","PHOENIXLTD",
        "MAXHEALTH","FORTIS","ASTER","METROPOLIS","LALPATHLAB",
    ]
    logger.warning("Using fallback universe: %d symbols", len(fallback))
    return fallback


# ===========================================================================
# 2. DOWNLOAD ALL PRICES — BATCHED + INCREMENTAL PARQUET
# ===========================================================================

def _yf_batch(symbols: List[str], start: str, end: str,
              chunk: int = 50) -> "pd.DataFrame":
    """
    Download daily closes for a list of NSE symbols.
    Processes in chunks of `chunk` to avoid timeouts.
    Returns wide DataFrame: index=Date, columns=NSE symbol names.
    """
    import yfinance as yf
    import pandas as pd

    all_data: Dict[str, "pd.DataFrame"] = {}
    tickers = [f"{s}.NS" for s in symbols]
    n_chunks = (len(tickers) + chunk - 1) // chunk

    for ci in range(n_chunks):
        c_tix = tickers[ci * chunk: (ci + 1) * chunk]
        c_sym = symbols[ci * chunk: (ci + 1) * chunk]
        logger.info("  Batch %d/%d (%d symbols, %s→%s)",
                    ci + 1, n_chunks, len(c_tix), start[:7], end[:7])

        raw = None
        for attempt in range(3):
            try:
                raw = yf.download(
                    " ".join(c_tix),
                    start=start, end=end,
                    interval="1d", auto_adjust=True,
                    progress=False, timeout=60, group_by="ticker",
                )
                if raw is not None and not raw.empty:
                    break
            except Exception as exc:
                wait = 5 * (attempt + 1)
                logger.warning("  chunk %d attempt %d: %s — retry %ds",
                               ci + 1, attempt + 1, str(exc)[:40], wait)
                time.sleep(wait)

        if raw is None or raw.empty:
            continue

        for sym, ytick in zip(c_sym, c_tix):
            try:
                if len(c_tix) == 1:
                    df = raw.copy()
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    df.columns = [c.lower() for c in df.columns]
                    s = df[["open", "close"]].dropna()
                else:
                    lvl0 = raw.columns.get_level_values(0)
                    if ytick not in lvl0:
                        continue
                    sub = raw[ytick].copy()
                    if isinstance(sub.columns, pd.MultiIndex):
                        sub.columns = sub.columns.get_level_values(0)
                    sub.columns = [c.lower() for c in sub.columns]
                    s = sub[["open", "close"]].dropna()

                if len(s) >= 30:
                    all_data[sym] = s
            except Exception:
                pass

    if not all_data:
        return pd.DataFrame()
    import pandas as pd
    # Return a MultiIndex DataFrame: (Symbol, OHLC)
    df = pd.concat(all_data, axis=1)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def download_prices(symbols: List[str], years: int = 5,
                    fresh: bool = False) -> "pd.DataFrame":
    """
    Download/update the full price matrix for all symbols.
    Incremental: on re-runs only fetches new days.
    Saves to data/cache/nexus/prices.parquet
    """
    import pandas as pd
    end   = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=years * 365 + 30)).strftime("%Y-%m-%d")

    pq = Path(PRICES_PQ)
    if pq.exists() and not fresh:
        try:
            existing = pd.read_parquet(pq)
            last     = existing.index[-1]
            nxt      = (last + timedelta(days=1)).strftime("%Y-%m-%d")
            if nxt >= end:
                logger.info("Prices up to date (%s, %d dates x %d cols)",
                            str(last.date()), len(existing), len(existing.columns))
                return existing
            logger.info("Prices cached to %s — downloading new days", str(last.date()))
            new = _yf_batch(symbols, start=nxt, end=end)
            if not new.empty:
                merged = pd.concat([existing, new]).pipe(
                    lambda d: d[~d.index.duplicated(keep="last")]).sort_index()
                merged.to_parquet(pq)
                logger.info("Prices updated: %d dates (+%d)", len(merged), len(merged)-len(existing))
                return merged
            return existing
        except Exception as exc:
            logger.warning("Prices parquet load: %s — re-downloading", exc)

    print(f"\n  Downloading {years} years of prices for {len(symbols)} symbols...")
    print(f"  Range: {start} → {end}  |  Batch size: 50")
    prices = _yf_batch(symbols, start=start, end=end)
    if not prices.empty:
        prices.to_parquet(pq)
        logger.info("Prices saved: %d dates x %d stocks", len(prices), len(prices.columns))
    return prices


# ===========================================================================
# 3. MACRO SERIES  (NIFTY, VIX, SPX, USD/INR, Crude)
# ===========================================================================

def download_macro(years: int = 7, fresh: bool = False) -> Dict[str, "pd.Series"]:
    """
    Download / incrementally update global macro time series.
    Returns dict of {name: pd.Series(close, index=Date)}
    """
    import yfinance as yf
    import pandas as pd

    TICKERS = {
        "nifty":  "^NSEI",
        "vix":    "^INDIAVIX",
        "spx":    "^GSPC",
        "usdinr": "USDINR=X",
        "crude":  "BZ=F",
    }
    end   = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d")
    pq    = Path(MACRO_PQ)
    result: Dict[str, "pd.Series"] = {}

    # Incremental
    if pq.exists() and not fresh:
        try:
            ex   = pd.read_parquet(pq)
            last = ex.index[-1]
            nxt  = (last + timedelta(days=1)).strftime("%Y-%m-%d")
            if nxt < end:
                for name, ticker in TICKERS.items():
                    try:
                        new = yf.download(ticker, start=nxt, end=end,
                                          interval="1d", auto_adjust=True,
                                          progress=False, timeout=15)
                        if not new.empty:
                            if isinstance(new.columns, pd.MultiIndex):
                                new.columns = new.columns.get_level_values(0)
                            new.columns = [c.lower() for c in new.columns]
                            if "close" in new.columns:
                                ex[name] = pd.concat([
                                    ex.get(name, pd.Series(dtype=float)),
                                    new["close"]
                                ]).sort_index().pipe(
                                    lambda s: s[~s.index.duplicated(keep="last")])
                    except Exception:
                        pass
                ex.to_parquet(pq)
            for col in ex.columns:
                result[col] = ex[col].dropna()
            logger.info("Macro loaded: %s", list(result.keys()))
            return result
        except Exception as exc:
            logger.warning("Macro parquet: %s — re-downloading", exc)

    # Full download
    parts: Dict[str, "pd.Series"] = {}
    for name, ticker in TICKERS.items():
        try:
            df = yf.download(ticker, start=start, end=end,
                             interval="1d", auto_adjust=True,
                             progress=False, timeout=20)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df.columns = [c.lower() for c in df.columns]
                if "close" in df.columns:
                    parts[name] = df["close"].dropna()
                    logger.info("  Macro %-10s %d rows", name, len(parts[name]))
        except Exception as exc:
            logger.warning("  Macro %s failed: %s", name, exc)

    if parts:
        macro_df = pd.DataFrame(parts)
        macro_df.to_parquet(pq)
        for col in macro_df.columns:
            result[col] = macro_df[col].dropna()
    return result


# ===========================================================================
# 4. CAUSAL FEATURE ENGINEERING
#    Key innovation: daily top-50 gainers + losers as training signal
# ===========================================================================

def _ema(s: "pd.Series", n: int) -> "pd.Series":
    return s.ewm(span=n, adjust=False).mean()


def _nifty_indicators(close: "pd.Series") -> "pd.DataFrame":
    """Compute ADX proxy, RSI, ATR_norm, CEV from a close-only NIFTY series."""
    import pandas as pd
    ema20   = _ema(close, 20)
    ema50   = _ema(close, 50)
    cev     = (close - ema20) / (ema20.clip(lower=1)) * 100
    d       = close.diff()
    gain    = d.clip(lower=0).rolling(14).mean()
    loss    = (-d.clip(upper=0)).rolling(14).mean()
    rsi     = 100 - 100 / (1 + gain / (loss + 1e-9))
    tr      = d.abs()
    atr14   = tr.ewm(span=14, adjust=False).mean()
    atr_n   = atr14 / close.clip(lower=1) * 100
    mom     = close.diff(5).abs()
    adx_p   = _ema(mom / close.clip(lower=1) * 100, 14).clip(0, 60)
    return pd.DataFrame({"adx": adx_p, "rsi": rsi, "cev": cev, "atr_norm": atr_n},
                        index=close.index)


def _rss_sentiment_for_date() -> float:
    """Scrape current RSS headline sentiment. Returns value in [-1, +1]."""
    POS = {"surge","rally","gain","profit","beat","record","upgrade","bullish",
           "buy","growth","high","win","deal","approved","inflow","rate cut",
           "positive","recovery","breakout","dividend","buyback"}
    NEG = {"crash","fall","loss","decline","default","fraud","downgrade",
           "bearish","sell","low","penalty","probe","outflow","rate hike",
           "miss","concern","correction","selloff","recession"}
    try:
        import requests
        text = ""
        for url in ["https://www.moneycontrol.com/rss/MCtopnews.xml",
                    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"]:
            try:
                r = requests.get(url, timeout=6, headers={"User-Agent":"AlphaZero/4.0"})
                text += r.text
            except Exception:
                pass
        titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", text, re.DOTALL)
        if not titles:
            titles = re.findall(r"<title>(.*?)</title>", text)
        score = 0
        for t in titles[:30]:
            tl = t.lower()
            score += sum(1 for w in POS if w in tl)
            score -= sum(1 for w in NEG if w in tl)
        return max(-1.0, min(1.0, score / max(len(titles), 1) / 2))
    except Exception:
        return 0.0


def build_causal_features(prices: "pd.DataFrame",
                           macro: Dict[str, "pd.Series"],
                           top_n: int = 50) -> "pd.DataFrame":
    """
    Overhauled Causal Feature Engineering (Sample-Level Dataset)
    
    Sampling Logic per Day:
      - 40 samples: Top 20 gainers + Top 20 losers (weight 1.5)
      - 30 samples: Randomly selected from NIFTY 500 (weight 1.0)
      - 30 samples: High-volatility stocks (ATR spikes) (weight 2.0)
    
    Total: 100 samples per trading day.
    """
    import pandas as pd
    import numpy as np

    print(f"\n  Building rich causal dataset from {len(prices.columns.levels[0])} stocks...")
    
    # 1. Day-level Macro Features
    # NIFTY technicals
    nifty_close = macro.get("nifty", prices.xs("close", axis=1, level=1).mean(axis=1))
    ind         = _nifty_indicators(nifty_close)
    
    # VIX and VIX Delta
    vix_s = macro.get("vix", pd.Series(15.0, index=prices.index))
    vix_s = vix_s.reindex(prices.index).ffill().bfill().fillna(15.0)
    vix_delta = vix_s.diff().fillna(0)
    
    # SPX and USD/INR
    spx_raw = macro.get("spx", pd.Series(dtype=float))
    spx_ret = spx_raw.pct_change().reindex(prices.index).ffill().fillna(0) * 100
    usd_chg = macro.get("usdinr", pd.Series(dtype=float))\
                       .pct_change().reindex(prices.index).ffill().fillna(0) * 100
    
    # Advance/Decline Ratio (Day level)
    closes = prices.xs("close", axis=1, level=1)
    daily_ret = closes.pct_change()
    adv_decl = (daily_ret > 0).sum(axis=1) / (daily_ret < 0).sum(axis=1).clip(lower=1)
    
    # Sector Variance (Day level)
    sector_map = {sym: _sector(sym) for sym in prices.columns.levels[0]}
    
    # 2. Stock-level Features
    opens = prices.xs("open", axis=1, level=1)
    prev_closes = closes.shift(1)
    gap_pct = (opens / prev_closes - 1) * 100
    
    # Rolling Vol (5D, 10D)
    vol5  = daily_ret.rolling(5).std() * np.sqrt(252) * 100
    vol10 = daily_ret.rolling(10).std() * np.sqrt(252) * 100

    # 3. Aggregates for labelling fallback (existing logic)
    g_count_pct = (daily_ret > 0.02).sum(axis=1) / closes.notnull().sum(axis=1).clip(lower=1)
    l_count_pct = (daily_ret < -0.02).sum(axis=1) / closes.notnull().sum(axis=1).clip(lower=1)
    
    # Sentiment
    sentiment_base = spx_raw.pct_change().reindex(prices.index).ffill().fillna(0)
    sentiment_base = (sentiment_base / 0.03).clip(-1, 1) * 0.5
    for date_str, flag in KNOWN_EVENTS.items():
        try:
            dt = pd.Timestamp(date_str)
            if dt in sentiment_base.index: sentiment_base.loc[dt] = float(flag) * 0.7
        except: pass

    # Event flag
    event_s = pd.Series(0, index=prices.index)
    for date_str, flag in KNOWN_EVENTS.items():
        try:
            dt = pd.Timestamp(date_str)
            if dt in event_s.index: event_s.loc[dt] = flag
        except: pass

    all_samples = []
    valid_dates = daily_ret.index[25:]
    
    for dt in valid_dates:
        try:
            day_ret = daily_ret.loc[dt].dropna()
            if len(day_ret) < 50: continue
            
            # --- Sampling ---
            # 1. Extreme (40)
            sorted_ret = day_ret.sort_values(ascending=False)
            extreme_syms = list(sorted_ret.head(20).index) + list(sorted_ret.tail(20).index)
            
            # 2. High-Vol (30)
            day_vol = vol5.loc[dt].dropna()
            high_vol_syms = list(day_vol.sort_values(ascending=False).head(30).index)
            
            # 3. Random (30)
            avail = [s for s in day_ret.index if s not in extreme_syms and s not in high_vol_syms]
            import random
            random_syms = random.sample(avail, min(len(avail), 30))
            
            # Day-level macro context
            try: row_ind = ind.loc[dt]
            except KeyError: row_ind = ind.iloc[ind.index.get_indexer([dt], method="nearest")[0]]
            
            day_macro = {
                "adx":            float(row_ind.get("adx", 20)),
                "rsi":            float(row_ind.get("rsi", 50)),
                "vix":            float(vix_s.get(dt, 15)),
                "vix_delta":      float(vix_delta.get(dt, 0)),
                "atr_norm":       float(row_ind.get("atr_norm", 1)),
                "cev":            float(row_ind.get("cev", 0)),
                "gainer_pct":     float(g_count_pct.get(dt, 0.2)),
                "loser_pct":      float(l_count_pct.get(dt, 0.2)),
                "adv_decl_ratio": float(adv_decl.get(dt, 1.0)),
                "spx_prev_ret":   float(spx_ret.get(dt, 0)),
                "usdinr_change":  float(usd_chg.get(dt, 0)),
                "news_sentiment": float(sentiment_base.get(dt, 0)),
                "event_flag":     int(event_s.get(dt, 0)),
            }
            
            # Sector Rotation Strength for the day
            sec_rets = {}
            for sym, ret in day_ret.items():
                sec_rets.setdefault(sector_map.get(sym, "OTHER"), []).append(float(ret))
            sec_meds = [float(np.median(v)) for v in sec_rets.values() if v]
            day_macro["sector_rot_strength"] = float(np.std(sec_meds)) * 100 if len(sec_meds) > 1 else 0.0

            # Create sample rows
            for group, syms, weight in [
                ("extreme", extreme_syms, 1.5),
                ("random", random_syms, 1.0),
                ("high_vol", high_vol_syms, 2.0)
            ]:
                for s in syms:
                    if s not in day_ret.index: continue
                    sample = {
                        "date":           dt,
                        "symbol":         s,
                        "weight":         weight,
                        "group":          group,
                        "gap_pct":        float(gap_pct.loc[dt, s] if s in gap_pct.columns else 0),
                        "rolling_vol_5d": float(vol5.loc[dt, s] if s in vol5.columns else 0),
                        "rolling_vol_10d":float(vol10.loc[dt, s] if s in vol10.columns else 0),
                        "avg_top50_ret":  round(float(sorted_ret.head(50).mean() * 100), 4),
                        "avg_bot50_ret":  round(float(sorted_ret.tail(50).mean() * 100), 4),
                        **day_macro
                    }
                    all_samples.append(sample)
                    
        except Exception:
            pass

    if not all_samples:
        logger.error("No samples built")
        return pd.DataFrame()

    feat = pd.DataFrame(all_samples).set_index("date").sort_index()
    feat.to_parquet(FEAT_PQ)
    print(f"  Total samples: {len(feat)} over {len(valid_dates)} days")
    return feat


# ===========================================================================
# 5. CAUSAL LABELING  (mirrors NEXUS rule engine + enriched with breadth)
# ===========================================================================

def _causal_label(
    adx: float, rsi: float, vix: float, cev: float,
    gainer_pct: float, loser_pct: float,
    avg_top: float, avg_bot: float,
    spx: float, sentiment: float, event: int,
) -> int:
    """
    Causal voting: assigns regime label using both technical signals
    AND the breadth/magnitude of actual stock movements.

    Returns: 0=TRENDING  1=SIDEWAYS  2=VOLATILE  3=RISK_OFF
    """
    v = {0: 0, 1: 0, 2: 0, 3: 0}

    # Hard override: negative macro event + elevated VIX
    if event == -1 and vix >= 22:
        v[3] += 4

    # VIX (primary safety signal)
    if vix >= 28:         v[3] += 3
    elif vix >= 22:       v[2] += 2
    elif vix >= 18:       v[2] += 1
    else:                 v[0] += 1   # calm market = potential trend

    # Breadth: net gainers vs losers
    net = gainer_pct - loser_pct
    if net > 0.30:        v[0] += 2   # 30%+ more gainers -> strong trend
    elif net > 0.10:      v[0] += 1
    elif net < -0.30:     v[3] += 2   # 30%+ more losers -> risk-off
    elif net < -0.10:     v[2] += 1   # moderate selling -> volatile
    else:                 v[1] += 1   # balanced -> sideways

    # Magnitude of top movers
    # If top-50 avg only moved 0.5%, the market is quiet (sideways)
    # If top-50 avg moved 5%, something real is happening (trending)
    if avg_top >= 4.0:    v[0] += 2   # strong broad gainers
    elif avg_top >= 2.0:  v[0] += 1
    elif avg_top <= 0.5 and abs(avg_bot) <= 0.5:
        v[1] += 2                      # tiny moves both ways = sideways

    if avg_bot <= -4.0:   v[3] += 2   # severe selling = risk-off
    elif avg_bot <= -2.0: v[2] += 1   # moderate selling = volatile

    # ADX (trend confirmation)
    if adx >= 30:         v[0] += 2
    elif adx >= 22:       v[0] += 1
    elif adx <= 15:       v[1] += 2   # no trend = sideways

    # RSI
    if rsi >= 72 or rsi <= 28:  v[2] += 1
    elif 42 <= rsi <= 58:       v[1] += 1

    # CEV (price deviation from EMA20)
    if abs(cev) >= 3.5:   v[0] += 1   # far from mean = trending
    elif abs(cev) <= 0.4: v[1] += 1   # near mean = sideways

    # SPX carry
    if spx >= 1.5:        v[0] += 1
    elif spx <= -1.5:     v[3] += 1

    # Sentiment
    if sentiment >= 0.4:  v[0] += 1
    elif sentiment <= -0.4: v[3] += 1

    # Known positive event (budget, rate cut)
    if event == 1:        v[0] += 1

    return max(v, key=v.get)


def label_features(feat: "pd.DataFrame") -> Tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
    """
    Assign labels to samples based on day-level aggregates.
    Returns (X, y, weights).
    """
    NAMES = ["TRENDING", "SIDEWAYS", "VOLATILE", "RISK_OFF"]
    X_list, y_list, w_list = [], [], []
    
    # We group by date to only compute the label once per day
    for dt, day_feat in feat.groupby(level=0):
        # All samples for this day share these aggregates
        first = day_feat.iloc[0]
        label = _causal_label(
            adx        = float(first.get("adx", 20)),
            rsi        = float(first.get("rsi", 50)),
            vix        = float(first.get("vix", 15)),
            cev        = float(first.get("cev", 0)),
            gainer_pct = float(first.get("gainer_pct", 0.2)),
            loser_pct  = float(first.get("loser_pct", 0.2)),
            avg_top    = float(first.get("avg_top50_ret", 1)),
            avg_bot    = float(first.get("avg_bot50_ret", -1)),
            spx        = float(first.get("spx_prev_ret", 0)),
            sentiment  = float(first.get("news_sentiment", 0)),
            event      = int(first.get("event_flag", 0)),
        )
        
        for _, row in day_feat.iterrows():
            X_list.append([float(row.get(f, 0)) for f in FEATURE_NAMES])
            y_list.append(label)
            w_list.append(float(row.get("weight", 1.0)))

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=int)
    w = np.array(w_list, dtype=np.float32)
    
    counts = {NAMES[i]: int((y == i).sum()) for i in range(4)}
    print(f"\n  Label distribution: {counts}")
    return X, y, w


# ===========================================================================
# 6. XGBOOST TRAINING (chronological split, no shuffle)
# ===========================================================================

def train_xgboost(X: "np.ndarray", y: "np.ndarray", sample_weights: "np.ndarray",
                  n_estimators: int = 150, max_depth: int = 4,
                  lr: float = 0.05, val_split: float = 0.15,
                  round_number: int = 1) -> Dict:
    try:
        import xgboost as xgb
        from sklearn.metrics import accuracy_score, classification_report
        from sklearn.utils.class_weight import compute_class_weight
    except ImportError as exc:
        logger.error("pip install xgboost scikit-learn: %s", exc)
        sys.exit(1)

    NAMES = ["TRENDING", "SIDEWAYS", "VOLATILE", "RISK_OFF"]
    
    # Chronological split (no shuffle)
    split = int(len(X) * (1 - val_split))
    X_tr, X_val = X[:split], X[split:]
    y_tr, y_val = y[:split], y[split:]
    w_tr, w_val = sample_weights[:split], sample_weights[split:]

    # Class balancing
    classes = np.unique(y_tr)
    weights = compute_class_weight(class_weight='balanced', classes=classes, y=y_tr)
    class_weights = dict(zip(classes, weights))
    print(f"  Class weights (balancing): {class_weights}")

    # Combine sample weights with class weights
    final_weights = np.array([w_tr[i] * class_weights.get(y_tr[i], 1.0) for i in range(len(y_tr))])

    print(f"\n  Training NEXUS v2 Round #{round_number}: {len(X_tr)} samples / {len(X_val)} val")
    print(f"  Trees: {n_estimators}  Depth: {max_depth}  LR: {lr}")

    model = xgb.XGBClassifier(
        n_estimators=n_estimators, max_depth=max_depth, learning_rate=lr,
        subsample=0.8, colsample_bytree=0.8,
        objective="multi:softmax", num_class=4,
        eval_metric="mlogloss",
        early_stopping_rounds=20,
        verbosity=0, random_state=42,
    )
    
    t0 = time.time()
    model.fit(X_tr, y_tr, sample_weight=final_weights,
              eval_set=[(X_val, y_val)], sample_weight_eval_set=[w_val],
              verbose=False)
    elapsed = time.time() - t0

    y_pred = model.predict(X_val)
    acc    = float(accuracy_score(y_val, y_pred))
    report = classification_report(y_val, y_pred, target_names=NAMES, output_dict=True)

    print(f"\n  Done in {elapsed:.1f}s  |  Val Accuracy: {acc*100:.1f}%\n")
    for name in NAMES:
        m   = report.get(name, {})
        bar = "█" * int(m.get("f1-score", 0) * 20)
        print(f"    {name:10}  F1={m.get('f1-score',0):.2f}  {bar}")

    fi = dict(zip(FEATURE_NAMES, model.feature_importances_))
    print("\n  Top-10 Feature Importances:")
    sorted_fi = sorted(fi.items(), key=lambda x: -x[1])[:10]
    for k, v in sorted_fi:
        bar = "█" * int(v * 40)
        print(f"    {k:20} {bar:40} {v:.3f}")

    model.save_model(MODEL_PATH)
    meta = {
        "trained_at":         datetime.now().isoformat(),
        "round":              round_number,
        "total_rows":         len(X),
        "train_rows":         len(X_tr),
        "val_rows":           len(X_val),
        "n_features":         X.shape[1],
        "feature_names":      FEATURE_NAMES,
        "accuracy":           round(acc, 4),
        "params":             {"n_estimators": n_estimators, "max_depth": max_depth, "lr": lr},
        "per_class_f1":       {n: round(report.get(n, {}).get("f1-score", 0), 3)
                               for n in NAMES},
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
    return meta


# ===========================================================================
# 7. ROLLING TRAINING LOOP
# ===========================================================================

def training_loop(years: int = 5, top_n: int = 50,
                  retrain_every: int = 7, n_estimators: int = 300,
                  max_depth: int = 5, lr: float = 0.08,
                  val_split: float = 0.15, fresh: bool = False,
                  run_once: bool = False) -> None:
    rnd = 0
    while True:
        rnd += 1
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print()
        print("╔" + "═" * 65 + "╗")
        print(f"║  NEXUS CAUSAL TRAINING  Round #{rnd}   {ts}".ljust(67) + "║")
        print("╚" + "═" * 65 + "╝")

        # 1. Dynamic universe (live from NSE)
        symbols = fetch_universe()
        print(f"\n  Universe: {len(symbols)} NSE symbols (NIFTY 500, dynamic)")

        # 2. Price matrix (incremental append)
        print("\n  [1/4] Price matrix")
        prices = download_prices(symbols, years=years,
                                 fresh=(fresh and rnd == 1))
        if prices.empty:
            logger.error("No prices — retry in 60min")
            if run_once: break
            time.sleep(3600); continue

        # 3. Macro series
        print("\n  [2/4] Macro series")
        macro = download_macro(fresh=(fresh and rnd == 1))

        # 4. Causal features (top-50 gainers/losers per day)
        print("\n  [3/4] Causal feature engineering")
        feat = build_causal_features(prices, macro, top_n=top_n)
        if len(feat) < 100:
            logger.error("Only %d rows — retry in 60min", len(feat))
            if run_once: break
            time.sleep(3600); continue

        # 5. Label + train
        print("\n  [4/4] XGBoost training")
        X, y, w = label_features(feat)
        meta = train_xgboost(X, y, w, n_estimators=n_estimators,
                             max_depth=max_depth, lr=lr,
                             val_split=val_split, round_number=rnd)

        print()
        print(f"  Round #{rnd} complete | Accuracy: {meta['accuracy']*100:.1f}% | "
              f"Samples: {meta['total_rows']} | Features: {meta['n_features']}")

        if run_once:
            print("  --once: done."); break

        nxt = datetime.now() + timedelta(days=retrain_every)
        print(f"\n  Next retrain: {nxt.strftime('%Y-%m-%d %H:%M')} ({retrain_every} days)")
        print("  Only NEW trading days will be downloaded on next run.")
        print("  NEXUS is using the saved model right now. Ctrl+C to stop.\n")

        total = retrain_every * 86400
        slept = 0
        while slept < total:
            chunk = min(3600, total - slept)
            time.sleep(chunk); slept += chunk
            if slept % 21600 == 0 and slept < total:
                logger.info("Next retrain in %.1fh", (total - slept) / 3600)


# ===========================================================================
# 8. CLI
# ===========================================================================

def main() -> None:
    p = argparse.ArgumentParser(
        description="NEXUS Causal Regime Classifier — Dynamic NIFTY500 + Top-50 Gainers/Losers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/train_nexus.py              # run forever (default)
  python scripts/train_nexus.py --once       # train once and exit
  python scripts/train_nexus.py --fresh      # re-download everything
  python scripts/train_nexus.py --top-n 100  # use top 100 gainers/losers
  python scripts/train_nexus.py --years 5 --retrain-every 7
        """)
    p.add_argument("--years",          type=int,   default=5)
    p.add_argument("--top-n",          type=int,   default=50)
    p.add_argument("--retrain-every",  type=int,   default=7)
    p.add_argument("--estimators",     type=int,   default=300)
    p.add_argument("--depth",          type=int,   default=5)
    p.add_argument("--lr",             type=float, default=0.08)
    p.add_argument("--val-split",      type=float, default=0.15)
    p.add_argument("--once",           action="store_true")
    p.add_argument("--fresh",          action="store_true")
    args = p.parse_args()

    missing = []
    for pkg in ["yfinance", "xgboost", "pandas", "numpy"]:
        try: __import__(pkg)
        except ImportError: missing.append(pkg)
    try: from sklearn.metrics import accuracy_score  # noqa
    except ImportError: missing.append("scikit-learn")
    if missing:
        print(f"  Missing: pip install {' '.join(missing)}"); sys.exit(1)

    try:
        with open(META_PATH) as f:
            meta = json.load(f)
        print(f"\n  Previous model: round #{meta.get('round','?')}  "
              f"acc={meta.get('accuracy',0)*100:.1f}%  "
              f"rows={meta.get('total_rows','?')}  features={meta.get('n_features','?')}")
    except Exception:
        print("\n  No previous model — training from scratch.")

    print(f"\n  Universe      : dynamic NIFTY500 (live from NSE)")
    print(f"  Top-N movers  : {args.top_n} gainers + {args.top_n} losers per day")
    print(f"  History       : {args.years} years")
    print(f"  Retrain every : {args.retrain_every} days (incremental download)")
    print(f"  Features      : {len(FEATURE_NAMES)} causal features")
    print(f"  Cache         : {CACHE_DIR}")

    try:
        training_loop(
            years=args.years, top_n=args.top_n,
            retrain_every=args.retrain_every, n_estimators=args.estimators,
            max_depth=args.depth, lr=args.lr, val_split=args.val_split,
            fresh=args.fresh, run_once=args.once,
        )
    except KeyboardInterrupt:
        print("\n\n  Stopped. Model saved. NEXUS will use it.")


if __name__ == "__main__":
    main()
