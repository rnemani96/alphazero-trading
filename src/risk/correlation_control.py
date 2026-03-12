"""
src/risk/correlation_control.py  —  AlphaZero Capital
═══════════════════════════════════════════════════════
NEW: Correlation Control (was TODO)

Prevents holding 2 stocks with > 0.8 correlation in the same portfolio.
Uses 60-day rolling returns correlation matrix.

Usage in CHIEF/SIGMA agent:
    from src.risk.correlation_control import CorrelationFilter
    cf = CorrelationFilter(data_fetcher=fetcher)
    approved = cf.filter_signals(candidate_signals, current_positions)
"""

from __future__ import annotations
import logging
from typing import List, Dict, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger("CorrelationControl")

CORRELATION_THRESHOLD = 0.8   # Reject if two stocks have r > this
LOOKBACK_DAYS         = 60    # Rolling window for correlation


class CorrelationFilter:
    """
    Filters out candidate signals that would introduce highly correlated
    stocks into the portfolio.

    Algorithm:
      1. Fetch 60d daily returns for all current positions + candidates
      2. Build correlation matrix
      3. For each candidate: reject if corr > 0.8 with ANY current holding
      4. Among approved candidates: reject duplicates within the same candidate set
    """

    def __init__(self, data_fetcher=None, threshold: float = CORRELATION_THRESHOLD):
        self.fetcher   = data_fetcher
        self.threshold = threshold
        self._corr_cache: Optional[pd.DataFrame] = None
        self._cache_symbols: List[str] = []

    def build_correlation_matrix(self, symbols: List[str]) -> pd.DataFrame:
        """
        Build correlation matrix for the given symbols using 60-day daily returns.
        Returns an (n×n) DataFrame indexed by symbol.
        """
        if not symbols:
            return pd.DataFrame()

        from datetime import datetime, timedelta
        end   = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        price_data = {}
        for sym in symbols:
            try:
                if self.fetcher:
                    df = self.fetcher.get_historical(sym, start, end, "1d")
                else:
                    # Fallback: try yfinance directly
                    import yfinance as yf
                    df = yf.download(sym + ".NS", start=start, end=end, progress=False)
                    if df is not None and not df.empty:
                        df.columns = [c.lower() if isinstance(c, str) else c[0].lower()
                                      for c in df.columns]
                        df['datetime'] = df.index
                        df = df.reset_index(drop=True)

                if df is not None and not df.empty and 'close' in df.columns:
                    price_data[sym] = pd.to_numeric(df['close'], errors='coerce').dropna().values[-LOOKBACK_DAYS:]
            except Exception as e:
                logger.debug(f"Correlation data fetch failed {sym}: {e}")

        if len(price_data) < 2:
            return pd.DataFrame()

        # Align lengths
        min_len = min(len(v) for v in price_data.values())
        if min_len < 10:
            return pd.DataFrame()

        returns = pd.DataFrame(
            {sym: np.diff(np.log(price_data[sym][-min_len:] + 1e-9))
             for sym in price_data}
        )
        corr = returns.corr()
        self._corr_cache    = corr
        self._cache_symbols = list(corr.columns)
        return corr

    def get_correlation(self, sym1: str, sym2: str) -> float:
        """
        Get pairwise correlation between two symbols.
        Uses cached matrix if both symbols are in it.
        Returns 0.0 if data unavailable.
        """
        if (self._corr_cache is not None and
                sym1 in self._corr_cache.columns and
                sym2 in self._corr_cache.columns):
            return float(self._corr_cache.loc[sym1, sym2])
        # Build on demand
        corr = self.build_correlation_matrix([sym1, sym2])
        if corr.empty or sym1 not in corr.columns or sym2 not in corr.columns:
            return 0.0
        return float(corr.loc[sym1, sym2])

    def filter_signals(self,
                        candidates: List[Dict],
                        current_positions: List[str]) -> List[Dict]:
        """
        Filter candidate signals to remove stocks too correlated
        with existing holdings.

        candidates        : list of signal dicts with 'symbol' key
        current_positions : list of currently held symbols

        Returns filtered list of approved candidates.
        """
        if not candidates:
            return []

        candidate_syms = [c['symbol'] for c in candidates]
        all_syms       = list(set(current_positions + candidate_syms))

        if len(all_syms) < 2:
            return candidates

        # Build correlation matrix
        try:
            corr = self.build_correlation_matrix(all_syms)
        except Exception as e:
            logger.warning(f"Correlation matrix build failed: {e} — skipping filter")
            return candidates

        if corr.empty:
            return candidates

        approved  = []
        rejected  = []

        for signal in candidates:
            sym     = signal['symbol']
            blocked = False

            # Check against all current holdings
            for held in current_positions:
                if held == sym:
                    continue
                if sym not in corr.columns or held not in corr.columns:
                    continue
                r = abs(float(corr.loc[sym, held]))
                if r > self.threshold:
                    logger.info(f"Correlation block: {sym} ↔ {held} r={r:.2f} > {self.threshold}")
                    blocked = True
                    break

            # Also check against already-approved candidates
            if not blocked:
                for prev in approved:
                    prev_sym = prev['symbol']
                    if sym not in corr.columns or prev_sym not in corr.columns:
                        continue
                    r = abs(float(corr.loc[sym, prev_sym]))
                    if r > self.threshold:
                        logger.info(f"Correlation block (candidate-pair): {sym} ↔ {prev_sym} r={r:.2f}")
                        blocked = True
                        break

            if blocked:
                rejected.append(sym)
            else:
                approved.append(signal)

        if rejected:
            logger.info(f"Correlation filter: {len(rejected)} rejected {rejected}, {len(approved)} approved")

        return approved

    def most_correlated_pairs(self, symbols: List[str], top_n: int = 10) -> List[Dict]:
        """
        Return top N most-correlated symbol pairs. Useful for dashboard reporting.
        """
        corr = self.build_correlation_matrix(symbols)
        if corr.empty:
            return []

        pairs = []
        cols  = list(corr.columns)
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                r = float(corr.iloc[i, j])
                pairs.append({
                    'sym1':        cols[i],
                    'sym2':        cols[j],
                    'correlation': round(r, 3),
                })
        pairs.sort(key=lambda x: abs(x['correlation']), reverse=True)
        return pairs[:top_n]
