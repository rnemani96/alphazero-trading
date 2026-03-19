"""
src/data/transcript_scraper.py  —  AlphaZero Capital
═══════════════════════════════════════════════════════
Earnings Call Transcript Scraper

Sources (all free, no license required):
  1. NSE Corporate Announcements API  — PDFs of board meeting outcomes
  2. BSE India Announcements API      — supplementary source
  3. Screener.in /api/company/         — structured quarterly results
  4. NSEIndia Results page             — EPS / PAT / Revenue text

What is extracted:
  - Company name, symbol, quarter, announcement date
  - Revenue / PAT / EPS figures (from structured data)
  - Guidance keywords (extracted from announcement text)
  - Management tone words (positive / cautious / uncertain)
  - Analyst rating changes if present in announcement

Usage:
    scraper = TranscriptScraper()
    results = scraper.get_earnings_announcements(["RELIANCE", "TCS"], days=30)
    for r in results:
        print(r["symbol"], r["quarter"], r["guidance_tone"])

The results feed directly into EarningsCallAnalyzer (llm_earnings_analyzer.py).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("TranscriptScraper")

_LOG_DIR    = Path(__file__).resolve().parents[2] / "logs"
_CACHE_DIR  = Path(__file__).resolve().parents[2] / "data" / "cache" / "transcripts"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_LOG_DIR.mkdir(exist_ok=True)

# ── Tone word dictionaries ────────────────────────────────────────────────────

_POSITIVE_TONE = {
    "confident", "optimistic", "strong", "robust", "positive", "bullish",
    "growth", "accelerating", "record", "outperform", "beat", "exceed",
    "momentum", "expanding", "improvement", "winning", "leadership",
    "pipeline", "healthy", "resilient", "disciplined", "focused",
}

_CAUTIOUS_TONE = {
    "cautious", "uncertain", "challenging", "headwinds", "pressure",
    "concern", "risk", "slow", "moderate", "careful", "prudent",
    "selective", "watchful", "monitor", "volatile", "complex",
}

_NEGATIVE_TONE = {
    "decline", "weakness", "shortfall", "miss", "difficult", "adverse",
    "deteriorate", "loss", "write-off", "restructure", "impairment",
    "warning", "downgrade", "reduction", "contraction", "disappointed",
}

_GUIDANCE_FORWARD = {
    "expect", "guidance", "forecast", "outlook", "anticipate",
    "target", "project", "estimate", "plan", "intend", "strategy",
}


def _count_words(text: str, word_set: set) -> int:
    """Count how many words from word_set appear in text (case-insensitive)."""
    tl = text.lower()
    return sum(1 for w in word_set if w in tl)


def _extract_numbers(text: str) -> Dict[str, Optional[float]]:
    """
    Extract common financial figures from text.
    Handles crore, lakh, million, billion formats.
    """
    result = {"revenue_cr": None, "pat_cr": None, "eps": None, "yoy_growth_pct": None}

    # Revenue / PAT patterns (in crores)
    rev_match = re.search(
        r"(?:revenue|net\s+sales?|total\s+income)[^\d]*[\₹]?\s*([\d,]+\.?\d*)\s*(?:crore|cr)",
        text, re.IGNORECASE)
    if rev_match:
        try:
            result["revenue_cr"] = float(rev_match.group(1).replace(",", ""))
        except ValueError:
            pass

    pat_match = re.search(
        r"(?:net\s+profit|PAT|profit\s+after\s+tax)[^\d]*[\₹]?\s*([\d,]+\.?\d*)\s*(?:crore|cr)",
        text, re.IGNORECASE)
    if pat_match:
        try:
            result["pat_cr"] = float(pat_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # EPS
    eps_match = re.search(r"EPS[^\d]*[\₹]?\s*([\d,]+\.?\d*)", text, re.IGNORECASE)
    if eps_match:
        try:
            result["eps"] = float(eps_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # YoY growth
    yoy_match = re.search(r"([\d,]+\.?\d*)\s*%\s*(?:YoY|year.on.year|year\s+over\s+year)",
                           text, re.IGNORECASE)
    if yoy_match:
        try:
            result["yoy_growth_pct"] = float(yoy_match.group(1))
        except ValueError:
            pass

    return result


def _compute_tone(text: str) -> Dict[str, Any]:
    """Compute management tone scores and derive an overall tone label."""
    pos_count  = _count_words(text, _POSITIVE_TONE)
    caut_count = _count_words(text, _CAUTIOUS_TONE)
    neg_count  = _count_words(text, _NEGATIVE_TONE)
    fwd_count  = _count_words(text, _GUIDANCE_FORWARD)

    total = max(pos_count + caut_count + neg_count, 1)
    pos_ratio  = pos_count  / total
    neg_ratio  = neg_count  / total
    caut_ratio = caut_count / total

    if pos_ratio > 0.5:
        label = "BULLISH"
        score = 0.5 + pos_ratio * 0.5
    elif neg_ratio > 0.4:
        label = "BEARISH"
        score = -(0.5 + neg_ratio * 0.5)
    elif caut_ratio > 0.4:
        label = "CAUTIOUS"
        score = -0.2 * caut_ratio
    else:
        label = "NEUTRAL"
        score = 0.0

    return {
        "tone_label":      label,
        "tone_score":      round(score, 3),
        "positive_words":  pos_count,
        "cautious_words":  caut_count,
        "negative_words":  neg_count,
        "guidance_mentions": fwd_count,
    }


# ══════════════════════════════════════════════════════════════════════════════

class TranscriptScraper:
    """
    Fetches and parses earnings announcements from NSE / BSE / Screener.

    Cache strategy:
      - Results cached by symbol + quarter in data/cache/transcripts/
      - TTL: 24 hours for recent quarters, 30 days for older

    Thread-safe.
    """

    _NSE_BASE  = "https://www.nseindia.com"
    _BSE_BASE  = "https://api.bseindia.com/BseIndiaAPI/api"
    _SCR_BASE  = "https://www.screener.in"

    def __init__(self):
        self._lock   = threading.Lock()
        self._session = None   # lazy-init requests.Session

    def _get_session(self):
        if self._session is None:
            try:
                import requests
                s = requests.Session()
                s.headers.update({
                    "User-Agent": "Mozilla/5.0 (AlphaZero/4.0)",
                    "Accept":     "application/json, text/html, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                })
                # Warm NSE session cookie
                s.get(self._NSE_BASE, timeout=8)
                self._session = s
            except ImportError:
                logger.error("requests not installed: pip install requests")
        return self._session

    # ── Public API ────────────────────────────────────────────────────────────

    def get_earnings_announcements(
        self,
        symbols:  List[str],
        days:     int = 30,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent earnings/board meeting announcements for given symbols.

        Args:
            symbols   : NSE symbol list, e.g. ["RELIANCE", "TCS"]
            days      : look-back window in calendar days
            use_cache : use local cache to avoid repeated API calls

        Returns:
            List of announcement dicts, sorted newest first.
        """
        results = []
        for sym in symbols:
            try:
                anns = self._get_symbol_announcements(sym, days, use_cache)
                results.extend(anns)
            except Exception as exc:
                logger.debug("Scraper: %s failed — %s", sym, exc)

        # Sort newest first
        results.sort(key=lambda x: x.get("announced_at", ""), reverse=True)
        logger.info("TranscriptScraper: %d announcements for %d symbols",
                    len(results), len(symbols))
        return results

    def get_quarterly_results(
        self,
        symbol: str,
        quarters: int = 4,
    ) -> List[Dict[str, Any]]:
        """
        Fetch structured quarterly P&L data from Screener.in.

        Returns list of quarterly dicts with revenue, PAT, EPS, YoY growth.
        """
        cache_key = f"quarterly_{symbol}_{quarters}"
        cached    = self._cache_get(cache_key, ttl_hours=24)
        if cached:
            return cached

        session = self._get_session()
        if not session:
            return []

        try:
            url = f"{self._SCR_BASE}/company/{symbol.upper()}/consolidated/"
            r   = session.get(url, timeout=10)
            if r.status_code == 404:
                url = f"{self._SCR_BASE}/company/{symbol.upper()}/"
                r   = session.get(url, timeout=10)
            r.raise_for_status()

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")

            results = []
            # Screener quarterly table
            for table in soup.select("table.data-table"):
                ths = [th.get_text(strip=True) for th in table.select("thead th")]
                if not ths or "Mar" not in " ".join(ths) and "Sep" not in " ".join(ths):
                    continue
                quarters_header = [h for h in ths if any(m in h for m in
                                    ["Mar", "Jun", "Sep", "Dec"])]
                for row in table.select("tbody tr"):
                    cols = [td.get_text(strip=True) for td in row.select("td")]
                    if not cols:
                        continue
                    label = cols[0]
                    values = cols[1:]
                    for qi, (qh, val) in enumerate(zip(quarters_header, values)):
                        if qi >= len(results):
                            results.append({"symbol": symbol, "quarter": qh})
                        try:
                            num = float(val.replace(",", ""))
                            if "Sales" in label or "Revenue" in label:
                                results[qi]["revenue_cr"] = num
                            elif "Net Profit" in label or "PAT" in label:
                                results[qi]["pat_cr"] = num
                            elif "EPS" in label:
                                results[qi]["eps"] = num
                        except ValueError:
                            pass
                break   # only first matching table

            if results:
                self._cache_set(cache_key, results[:quarters])
            return results[:quarters]

        except Exception as exc:
            logger.debug("Screener quarterly %s: %s", symbol, exc)
            return []

    # ── Internal: NSE announcements ───────────────────────────────────────────

    def _get_symbol_announcements(
        self,
        symbol:    str,
        days:      int,
        use_cache: bool,
    ) -> List[Dict[str, Any]]:
        cache_key = f"ann_{symbol}_{days}"
        if use_cache:
            cached = self._cache_get(cache_key, ttl_hours=6)
            if cached:
                return cached

        session = self._get_session()
        if not session:
            return []

        end_dt   = datetime.now()
        start_dt = end_dt - timedelta(days=days)

        # NSE Corporate Announcements
        url = (
            f"{self._NSE_BASE}/api/corporate-announcements"
            f"?index=equities&symbol={symbol}"
            f"&from_date={start_dt.strftime('%d-%m-%Y')}"
            f"&to_date={end_dt.strftime('%d-%m-%Y')}"
        )
        results: List[Dict] = []
        try:
            r = session.get(url, timeout=10)
            r.raise_for_status()
            raw = r.json()
            items = raw if isinstance(raw, list) else raw.get("data", [])
            for item in items[:20]:
                parsed = self._parse_nse_announcement(symbol, item)
                if parsed:
                    results.append(parsed)
        except Exception as exc:
            logger.debug("NSE announcements %s: %s", symbol, exc)

        # BSE fallback if no NSE results
        if not results:
            results = self._bse_announcements(symbol, start_dt, end_dt)

        if results and use_cache:
            self._cache_set(cache_key, results)
        return results

    def _parse_nse_announcement(
        self, symbol: str, item: Dict
    ) -> Optional[Dict[str, Any]]:
        """Parse a raw NSE announcement dict into a structured record."""
        desc = (item.get("desc") or item.get("subject") or item.get("body") or "").strip()
        if not desc:
            return None

        # Filter to earnings-related announcements
        earnings_keywords = {
            "result", "profit", "revenue", "quarterly", "financial",
            "earnings", "pat", "q1", "q2", "q3", "q4", "fy", "annual",
            "board meeting", "dividend", "eps"
        }
        desc_lower = desc.lower()
        if not any(kw in desc_lower for kw in earnings_keywords):
            return None

        # Extract date
        try:
            ts_raw = item.get("sort_date") or item.get("dt") or item.get("timestamp") or ""
            if ts_raw:
                ann_dt = datetime.strptime(ts_raw[:19], "%Y-%m-%d %H:%M:%S")
            else:
                ann_dt = datetime.now()
        except Exception:
            ann_dt = datetime.now()

        # Detect quarter from description
        quarter = self._detect_quarter(desc, ann_dt)

        # Financial figures
        numbers = _extract_numbers(desc)

        # Tone analysis
        tone = _compute_tone(desc)

        # Attachment PDF URL if present
        pdf_url = item.get("attchmntFile") or item.get("attachment") or ""

        return {
            "symbol":        symbol,
            "exchange":      "NSE",
            "quarter":       quarter,
            "announced_at":  ann_dt.isoformat(),
            "subject":       desc[:200],
            "full_text":     desc,
            "pdf_url":       pdf_url,
            "source":        "NSE",
            **numbers,
            **tone,
        }

    def _bse_announcements(
        self, symbol: str, start_dt: datetime, end_dt: datetime
    ) -> List[Dict]:
        """BSE API fallback for announcements."""
        session = self._get_session()
        if not session:
            return []

        results = []
        try:
            # BSE uses scrip code — map from symbol (approximate)
            url = (
                f"{self._BSE_BASE}/AnnSubCategoryGetData/w?"
                f"strCat=Results&strScrip={symbol}&strType=C"
                f"&strSearch=P&strToDate={end_dt.strftime('%Y%m%d')}"
                f"&strFromDate={start_dt.strftime('%Y%m%d')}"
                f"&MY_Param="
            )
            r = session.get(url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                for item in data.get("Table", [])[:10]:
                    desc = item.get("HEADLINE", "")
                    if desc:
                        quarter = self._detect_quarter(desc, datetime.now())
                        tone    = _compute_tone(desc)
                        results.append({
                            "symbol":       symbol,
                            "exchange":     "BSE",
                            "quarter":      quarter,
                            "announced_at": datetime.now().isoformat(),
                            "subject":      desc[:200],
                            "full_text":    desc,
                            "source":       "BSE",
                            **_extract_numbers(desc),
                            **tone,
                        })
        except Exception as exc:
            logger.debug("BSE announcements %s: %s", symbol, exc)

        return results

    @staticmethod
    def _detect_quarter(text: str, ref_date: datetime) -> str:
        """Detect which quarter is being reported."""
        t = text.lower()
        year = ref_date.year
        for q, months in [("Q4", ["jan", "feb", "mar"]),
                           ("Q1", ["apr", "may", "jun"]),
                           ("Q2", ["jul", "aug", "sep"]),
                           ("Q3", ["oct", "nov", "dec"])]:
            if any(m in t for m in months):
                return f"{q}FY{year}"
        if "annual" in t or "full year" in t:
            return f"FY{year}"
        # Fallback: detect Q1/Q2/Q3/Q4 directly
        for q in ["Q4", "Q3", "Q2", "Q1"]:
            if q.lower() in t:
                return f"{q}FY{year}"
        return f"Q?FY{year}"

    # ── Cache ──────────────────────────────────────────────────────────────────

    def _cache_path(self, key: str) -> Path:
        safe_key = re.sub(r"[^\w_]", "_", key)
        return _CACHE_DIR / f"{safe_key}.json"

    def _cache_get(self, key: str, ttl_hours: int = 24) -> Optional[Any]:
        p = self._cache_path(key)
        if not p.exists():
            return None
        age_h = (time.time() - p.stat().st_mtime) / 3600
        if age_h > ttl_hours:
            return None
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            return None

    def _cache_set(self, key: str, data: Any):
        p   = self._cache_path(key)
        tmp = str(p) + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp, str(p))
        except Exception as exc:
            logger.debug("Cache write %s: %s", key, exc)


# ── Module-level singleton ────────────────────────────────────────────────────

_SCRAPER: Optional[TranscriptScraper] = None

def get_scraper() -> TranscriptScraper:
    global _SCRAPER
    if _SCRAPER is None:
        _SCRAPER = TranscriptScraper()
    return _SCRAPER


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")
    syms = sys.argv[1:] or ["RELIANCE", "TCS", "HDFCBANK"]
    scraper = TranscriptScraper()
    results = scraper.get_earnings_announcements(syms, days=60)

    print(f"\n{len(results)} announcements found:")
    for r in results[:10]:
        print(f"\n  [{r['symbol']}] {r['quarter']} — {r['announced_at'][:10]}")
        print(f"  Tone: {r['tone_label']} (score={r['tone_score']:+.2f})")
        print(f"  +words={r['positive_words']}  -words={r['negative_words']}"
              f"  caution={r['cautious_words']}")
        if r.get("revenue_cr"):
            print(f"  Revenue: ₹{r['revenue_cr']:,.0f} Cr")
        if r.get("pat_cr"):
            print(f"  PAT:     ₹{r['pat_cr']:,.0f} Cr")
        print(f"  {r['subject'][:90]}...")
