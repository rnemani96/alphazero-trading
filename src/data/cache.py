"""
src/data/cache.py  —  AlphaZero Capital
════════════════════════════════════════
Historical Data Cache (SQLite + Parquet)

Answers: "Where does the system store historical data to reuse it?"

→ data/cache/prices.db       (SQLite index: symbol, date, interval)
→ data/cache/ohlcv/          (Parquet files: one per symbol+interval)
→ data/cache/fundamentals.db (SQLite: P/E, ROE, debt, etc.)
→ data/cache/metadata.json   (last-update timestamps per symbol)

Cache rules:
  - 1m / 5m data:  valid for 4 hours
  - 15m / 1h data: valid for 6 hours
  - 1d data:       valid until next market open
  - fundamentals:  valid for 7 days
"""

from __future__ import annotations

import os, json, sqlite3, logging, hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

import pandas as pd
import numpy as np

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

logger = logging.getLogger("DataCache")
IST = ZoneInfo("Asia/Kolkata")

_ROOT       = Path(__file__).resolve().parents[2]
CACHE_DIR   = _ROOT / "data" / "cache"
OHLCV_DIR   = CACHE_DIR / "ohlcv"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OHLCV_DIR.mkdir(parents=True, exist_ok=True)

PRICES_DB   = str(CACHE_DIR / "prices.db")
FUND_DB     = str(CACHE_DIR / "fundamentals.db")
META_FILE   = str(CACHE_DIR / "metadata.json")

# ── TTL config ────────────────────────────────────────────────────────────────
TTL = {
    "1m":   4 * 3600,
    "5m":   4 * 3600,
    "15m":  6 * 3600,
    "30m":  6 * 3600,
    "1h":   6 * 3600,
    "1d":   24 * 3600,   # refreshed after market close
    "fund": 7 * 24 * 3600,
}


# ── Metadata helpers ──────────────────────────────────────────────────────────

def _load_meta() -> dict:
    try:
        with open(META_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_meta(meta: dict):
    with open(META_FILE, "w") as f:
        json.dump(meta, f, indent=2)

def _meta_key(symbol: str, interval: str, start: str, end: str) -> str:
    return f"{symbol}|{interval}|{start}|{end}"

def _is_fresh(symbol: str, interval: str, start: str, end: str) -> bool:
    meta  = _load_meta()
    key   = _meta_key(symbol, interval, start, end)
    entry = meta.get(key)
    if not entry:
        return False
    ttl = TTL.get(interval, 86400)
    age = datetime.now().timestamp() - entry.get("ts", 0)
    return age < ttl

def _mark_fresh(symbol: str, interval: str, start: str, end: str, rows: int):
    meta = _load_meta()
    key  = _meta_key(symbol, interval, start, end)
    meta[key] = {"ts": datetime.now().timestamp(), "rows": rows}
    _save_meta(meta)


# ── Parquet OHLCV store ───────────────────────────────────────────────────────

def _parquet_path(symbol: str, interval: str) -> Path:
    safe = symbol.replace(".", "_").replace("/", "_")
    return OHLCV_DIR / f"{safe}_{interval}.parquet"

def save_ohlcv(symbol: str, interval: str, df: pd.DataFrame,
               start: str = "", end: str = "") -> None:
    """Persist OHLCV DataFrame to Parquet cache."""
    if df is None or df.empty:
        return
    path = _parquet_path(symbol, interval)
    try:
        # Merge with existing cache to avoid data gaps
        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df]).drop_duplicates(subset=["datetime"]).sort_values("datetime")
        df.to_parquet(path, index=False, engine="pyarrow")
        _mark_fresh(symbol, interval, start, end, len(df))
        logger.debug(f"Cache saved: {symbol} {interval} → {len(df)} rows")
    except Exception as e:
        logger.warning(f"Cache save failed {symbol}: {e}")

def load_ohlcv(symbol: str, interval: str,
               start: Optional[str] = None, end: Optional[str] = None,
               check_freshness: bool = True) -> Optional[pd.DataFrame]:
    """
    Load OHLCV from cache.
    Returns None if cache miss or stale.
    """
    path = _parquet_path(symbol, interval)
    if not path.exists():
        return None

    if check_freshness:
        s = start or ""
        e = end   or ""
        if not _is_fresh(symbol, interval, s, e):
            logger.debug(f"Cache stale: {symbol} {interval}")
            return None

    try:
        df = pd.read_parquet(path)
        if start:
            df = df[df["datetime"] >= pd.Timestamp(start)]
        if end:
            df = df[df["datetime"] <= pd.Timestamp(end)]
        logger.debug(f"Cache hit: {symbol} {interval} → {len(df)} rows")
        return df if not df.empty else None
    except Exception as e:
        logger.warning(f"Cache read failed {symbol}: {e}")
        return None

def cache_stats() -> Dict[str, int]:
    """Return dict of {symbol_interval: row_count} for all cached files."""
    stats = {}
    for f in OHLCV_DIR.glob("*.parquet"):
        try:
            df = pd.read_parquet(f)
            stats[f.stem] = len(df)
        except Exception:
            pass
    return stats


# ── Fundamentals SQLite store ─────────────────────────────────────────────────

def _fund_conn():
    conn = sqlite3.connect(FUND_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fundamentals (
            symbol      TEXT PRIMARY KEY,
            pe          REAL,
            pb          REAL,
            roe         REAL,
            debt_equity REAL,
            market_cap  REAL,
            revenue     REAL,
            net_profit  REAL,
            eps         REAL,
            dividend    REAL,
            sector      TEXT,
            industry    TEXT,
            updated_at  TEXT
        )
    """)
    conn.commit()
    return conn

def save_fundamentals(symbol: str, data: dict) -> None:
    conn = _fund_conn()
    data["symbol"]     = symbol
    data["updated_at"] = datetime.now().isoformat()
    cols = [c[1] for c in conn.execute("PRAGMA table_info(fundamentals)").fetchall()]
    row  = {k: data.get(k) for k in cols}
    conn.execute(f"""
        INSERT OR REPLACE INTO fundamentals ({','.join(cols)})
        VALUES ({','.join('?' for _ in cols)})
    """, [row[c] for c in cols])
    conn.commit()
    conn.close()

def load_fundamentals(symbol: str) -> Optional[dict]:
    try:
        conn = _fund_conn()
        row  = conn.execute(
            "SELECT * FROM fundamentals WHERE symbol=?", (symbol,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        cols = ["symbol","pe","pb","roe","debt_equity","market_cap",
                "revenue","net_profit","eps","dividend","sector","industry","updated_at"]
        data = dict(zip(cols, row))
        updated = datetime.fromisoformat(data.get("updated_at","2000-01-01"))
        if (datetime.now() - updated).total_seconds() > TTL["fund"]:
            return None           # stale
        return data
    except Exception as e:
        logger.warning(f"Fundamentals load failed {symbol}: {e}")
        return None

def get_all_cached_symbols() -> List[str]:
    """Return all symbols that have any cached OHLCV data."""
    symbols = set()
    for f in OHLCV_DIR.glob("*.parquet"):
        parts = f.stem.rsplit("_", 1)
        if parts:
            symbols.add(parts[0].replace("_", "."))
    return sorted(symbols)

def clear_stale_cache(older_than_days: int = 30):
    """Delete parquet files not updated in N days."""
    cutoff = datetime.now().timestamp() - older_than_days * 86400
    deleted = 0
    for f in OHLCV_DIR.glob("*.parquet"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1
    logger.info(f"Cache cleanup: removed {deleted} stale files")
    return deleted
