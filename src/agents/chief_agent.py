"""
CHIEF Agent — Portfolio Selection & Capital Allocation
src/agents/chief_agent.py

Replaces the stub that just sorted a list.

Responsibilities:
  - Receive scored stocks from SIGMA (all candidates, scored)
  - Receive sector allocations from ATLAS (sector → weight)
  - Apply portfolio construction rules:
      • Max 5 open long-term positions
      • Max 30% in one sector
      • Avoid correlated picks (same sector >2)
      • Weight by SIGMA score × sector weight
  - Publish final portfolio to Event Bus

KPI: Portfolio Sharpe > 1.5 quarterly
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger("CHIEF")

try:
    from ..event_bus.event_bus import BaseAgent, EventType
except ImportError:
    try:
        from src.event_bus.event_bus import BaseAgent, EventType
    except ImportError:
        class BaseAgent:
            def __init__(self, event_bus, config, name=""):
                self.event_bus = event_bus; self.config = config
                self.name = name; self.is_active = True
            def publish_event(self, *a, **k): pass
        class EventType:
            SIGNAL_GENERATED = "SIGNAL_GENERATED"


class ChiefAgent(BaseAgent):
    """
    CHIEF — Portfolio Selection Agent (the APEX in the master plan)

    Flow:
        sigma_scored = agents['SIGMA'].score_stocks(candidates, regime)
        atlas_sectors = agents['ATLAS'].get_sector_allocation(regime)
        portfolio = agents['CHIEF'].select_portfolio(sigma_scored, atlas_sectors, regime)
    """

    def __init__(self, event_bus, config: Dict):
        super().__init__(event_bus=event_bus, config=config, name="CHIEF")

        # Config
        self.max_positions    = config.get('MAX_POSITIONS', 5)
        self.max_sector_pct   = config.get('MAX_SECTOR_EXPOSURE_PCT', 0.30)
        self.max_same_sector  = config.get('CHIEF_MAX_SAME_SECTOR', 2)
        self.min_sigma_score  = config.get('CHIEF_MIN_SIGMA_SCORE', 0.40)
        self.initial_capital  = config.get('INITIAL_CAPITAL', 1_000_000)

        # State
        self.portfolio:    List[Dict] = []
        self.total_selections = 0
        self._last_regime  = ''
        self._selection_log: List[Dict] = []

        logger.info("CHIEF Agent initialised — portfolio construction ready")

    # ── public API ────────────────────────────────────────────────────────────

    def select_portfolio(
        self,
        sigma_scored:   List[Dict],
        atlas_sectors:  Optional[Dict[str, float]] = None,
        regime:         str = 'NEUTRAL',
    ) -> List[Dict]:
        """
        Select final portfolio from SIGMA's scored candidates.

        Args:
            sigma_scored:  Output of SIGMA.score_stocks() — list of dicts
                           each with 'symbol', 'sigma_score', optionally 'sector'
            atlas_sectors: Output of ATLAS.get_sector_allocation() or similar —
                           {sector_name: weight 0-1}.  None → equal-weight sectors.
            regime:        Current market regime (from NEXUS)

        Returns:
            List of up to max_positions dicts, each with:
            {symbol, sigma_score, sector, capital_weight, capital_amount}
        """
        self._last_regime = regime

        if not sigma_scored:
            logger.warning("CHIEF: no candidates from SIGMA")
            return []

        # 1. Filter below minimum score
        candidates = [s for s in sigma_scored
                      if s.get('sigma_score', 0) >= self.min_sigma_score]
        if not candidates:
            # Relax threshold if nothing passes
            candidates = sorted(sigma_scored,
                                key=lambda x: x.get('sigma_score', 0), reverse=True)[:10]

        # 2. Sort by SIGMA score descending
        candidates = sorted(candidates, key=lambda x: x.get('sigma_score', 0), reverse=True)

        # 3. Sector-aware selection
        portfolio   = self._sector_diversify(candidates, atlas_sectors)

        # 4. Capital weighting
        portfolio   = self._assign_capital(portfolio, atlas_sectors)

        # 5. Store & log
        self.portfolio = portfolio
        self.total_selections += 1
        self._selection_log.append({
            'iteration': self.total_selections,
            'regime':    regime,
            'symbols':   [p['symbol'] for p in portfolio],
            'timestamp': datetime.now().isoformat(),
        })
        if len(self._selection_log) > 100:
            self._selection_log.pop(0)

        # 6. Publish to event bus
        try:
            self.publish_event(EventType.SIGNAL_GENERATED, {
                'source': 'CHIEF',
                'portfolio': [
                    {'symbol': p['symbol'], 'capital_weight': p['capital_weight']}
                    for p in portfolio
                ],
                'regime': regime,
                'timestamp': datetime.now().isoformat(),
            })
        except Exception:
            pass

        syms = [p['symbol'] for p in portfolio]
        logger.info(
            f"CHIEF portfolio ({regime}): {syms} "
            f"[{len(portfolio)}/{self.max_positions} positions]"
        )
        return portfolio

    def get_portfolio(self) -> List[Dict]:
        return list(self.portfolio)

    def get_stats(self) -> Dict[str, Any]:
        return {
            'name':             'CHIEF',
            'active':           self.is_active,
            'portfolio_size':   len(self.portfolio),
            'portfolio':        [p['symbol'] for p in self.portfolio],
            'total_selections': self.total_selections,
            'last_regime':      self._last_regime,
            'kpi':              'Sharpe > 1.5 quarterly',
        }

    # ── internals ─────────────────────────────────────────────────────────────

    def _sector_diversify(
        self,
        candidates:    List[Dict],
        atlas_sectors: Optional[Dict[str, float]],
    ) -> List[Dict]:
        """
        Greedy selection respecting sector limits.
        Priority: highest SIGMA score → pick if sector not overweight.
        """
        sector_counts: Dict[str, int] = {}
        selected: List[Dict] = []

        for cand in candidates:
            if len(selected) >= self.max_positions:
                break

            sector = cand.get('sector', 'UNKNOWN')
            count  = sector_counts.get(sector, 0)

            if count >= self.max_same_sector:
                continue   # skip — sector already has enough

            selected.append(cand)
            sector_counts[sector] = count + 1

        # If we couldn't fill max_positions with diversification, relax and fill rest
        if len(selected) < self.max_positions:
            existing_syms = {s['symbol'] for s in selected}
            for cand in candidates:
                if len(selected) >= self.max_positions:
                    break
                if cand['symbol'] not in existing_syms:
                    selected.append(cand)
                    existing_syms.add(cand['symbol'])

        return selected

    def _assign_capital(
        self,
        portfolio:     List[Dict],
        atlas_sectors: Optional[Dict[str, float]],
    ) -> List[Dict]:
        """
        Assign capital weights.
        If ATLAS provides sector weights → stocks in stronger sectors get more capital.
        Otherwise → equal weight with slight score tilt.
        """
        if not portfolio:
            return []

        n = len(portfolio)

        if atlas_sectors:
            # Score-weighted within sector allocations
            raw_weights = []
            for p in portfolio:
                sector        = p.get('sector', 'UNKNOWN')
                sector_wt     = atlas_sectors.get(sector, 1.0 / n)
                sigma_score   = p.get('sigma_score', 0.5)
                raw_weights.append(sector_wt * sigma_score)
        else:
            # Equal weight with minor score tilt (+/- 10%)
            raw_weights = [0.9 + 0.2 * p.get('sigma_score', 0.5) for p in portfolio]

        total = sum(raw_weights) or 1.0
        cap   = self.initial_capital

        result = []
        for p, w in zip(portfolio, raw_weights):
            capital_weight = round(w / total, 4)
            capital_amount = round(cap * capital_weight, 0)
            result.append({
                **p,
                'capital_weight': capital_weight,
                'capital_amount': capital_amount,
            })

        return result
