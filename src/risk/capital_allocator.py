"""
Capital Allocator
src/risk/capital_allocator.py

FIXED: Replaced stub (returned per_signal = total/n with no real logic).

Real implementation:
  - Uses CHIEF's capital_weight per stock (from sigma_score + sector weight)
  - Hard caps: max 5% per position, max 30% per sector
  - Tracks: total invested, available capital, per-stock allocation
  - Returns a dict the dashboard can display directly
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

# Hard limits (mirroring GUARDIAN)
MAX_PER_POSITION_PCT = 0.05   # 5% of portfolio per stock
MAX_PER_SECTOR_PCT   = 0.30   # 30% of portfolio per sector


class CapitalAllocator:
    """
    Allocates capital across CHIEF-selected portfolio.

    Usage (called in main.py after CHIEF.select_portfolio):
        allocator = CapitalAllocator(total_capital=1_000_000)
        allocation = allocator.allocate(selected_stocks)
        # allocation[sym] = {'amount': ₹X, 'weight': 0.05, 'qty': 10}
    """

    def __init__(self, total_capital: float = 1_000_000):
        self.total_capital  = total_capital
        self._last_alloc: Dict[str, Dict] = {}
        self._total_invested = 0.0

    # ── public API ────────────────────────────────────────────────────────────

    def allocate(self, selected_stocks: List[Dict]) -> Dict[str, Dict]:
        """
        Compute capital allocation for each selected stock.

        selected_stocks: output of CHIEF.select_portfolio()
          Each dict must have: symbol, sigma_score, sector
          Optional: capital_weight (0–1), price

        Returns:
          {
            'RELIANCE': {'amount': 47500, 'weight': 0.0475, 'qty': 10,
                         'pct_of_portfolio': 4.75},
            ...
          }
        """
        if not selected_stocks:
            self._last_alloc = {}
            return {}

        n   = len(selected_stocks)
        cap = self.total_capital

        # ── Step 1: raw weights from CHIEF or equal-weight fallback ──────
        raw_weights = []
        for s in selected_stocks:
            w = s.get('capital_weight')
            if w and w > 0:
                raw_weights.append(float(w))
            else:
                # Derive from sigma_score with slight tilt
                score = s.get('sigma_score', s.get('score', 0.5))
                raw_weights.append(0.9 + 0.2 * float(score))

        total_raw = sum(raw_weights) or 1.0
        norm = [w / total_raw for w in raw_weights]

        # ── Step 2: apply hard position cap ──────────────────────────────
        capped = [min(w, MAX_PER_POSITION_PCT) for w in norm]

        # ── Step 3: apply sector cap ──────────────────────────────────────
        sector_used: Dict[str, float] = {}
        final_weights = []
        for i, s in enumerate(selected_stocks):
            sector = s.get('sector', 'UNKNOWN')
            used   = sector_used.get(sector, 0.0)
            avail  = MAX_PER_SECTOR_PCT - used
            w      = min(capped[i], avail)
            final_weights.append(max(w, 0.0))
            sector_used[sector] = used + w

        # ── Step 4: scale so weights sum to ≤ 1 (leave cash buffer) ──────
        total_wt = sum(final_weights) or 1.0
        if total_wt > 1.0:
            final_weights = [w / total_wt for w in final_weights]

        # ── Step 5: build result dict ─────────────────────────────────────
        result: Dict[str, Dict] = {}
        total_invested = 0.0

        for s, wt in zip(selected_stocks, final_weights):
            sym    = s.get('symbol', '')
            amount = round(cap * wt, 0)
            price  = s.get('price', 0)
            qty    = int(amount / price) if price > 0 else 0
            pct    = round(wt * 100, 2)

            result[sym] = {
                'amount':           amount,
                'weight':           round(wt, 4),
                'qty':              qty,
                'pct_of_portfolio': pct,
                'sector':           s.get('sector', '—'),
                'sigma_score':      s.get('sigma_score', s.get('score', 0)),
            }
            total_invested += amount

        self._last_alloc     = result
        self._total_invested = total_invested

        logger.info(
            f"CapitalAllocator: {len(result)} positions · "
            f"Total deployed: ₹{total_invested:,.0f} "
            f"({total_invested/cap*100:.1f}% of ₹{cap:,.0f})"
        )
        return result

    def get_summary(self) -> Dict[str, Any]:
        """Returns portfolio capital summary for the dashboard."""
        invested   = self._total_invested
        available  = self.total_capital - invested
        return {
            'total_capital':   self.total_capital,
            'invested':        invested,
            'available':       available,
            'invested_pct':    round(invested / self.total_capital * 100, 1) if self.total_capital else 0,
            'num_positions':   len(self._last_alloc),
            'per_stock':       self._last_alloc,
        }

    def get_stock_allocation(self, symbol: str) -> Dict:
        """Return allocation for a single stock."""
        return self._last_alloc.get(symbol, {})

    def update_capital(self, new_capital: float):
        """Call when portfolio value changes (P&L update)."""
        self.total_capital = new_capital
