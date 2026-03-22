"""
SIGMA Agent - Stock Scoring & Ranking

Scores every candidate stock using an 8-factor model and ranks them
for CHIEF to select the final portfolio.

FIXES / NEW FILE:
- This file was imported in main.py as `from src.agents.sigma_agent import SigmaAgent`
  but did not exist anywhere in the project.  Created from scratch to match the
  design described in AlphaZero_Capital_MasterPlan.docx.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

try:
    from src.event_bus.event_bus import BaseAgent, EventType
except ImportError:
    try:
        from ..event_bus.event_bus import BaseAgent, EventType
    except ImportError:
        # Fallback for static analysis tools
        class BaseAgent:
            def __init__(self, event_bus=None, config=None, name=""):
                self.event_bus = event_bus; self.config = config or {}; self.name = name
                self.is_active = True; self.last_activity = "Initialised"
            def publish_event(self, *a, **k): pass
            def subscribe(self, *a, **k): pass
        class EventType:
            SIGNAL_GENERATED = "signal_generated"

logger = logging.getLogger(__name__)


class SigmaAgent(BaseAgent):
    """
    SIGMA - Stock Scoring Agent

    Responsibilities:
    - Score every candidate stock using 8 factors
    - Rank candidates for CHIEF portfolio selection
    - Emit SIGNAL_GENERATED events for top picks
    - Adapt factor weights based on regime

    KPI: Top-5 selections beat NIFTY50 by > 5% monthly
    """

    # Default factor weights (sum to 1.0)
    DEFAULT_WEIGHTS: Dict[str, float] = {
        'momentum':         0.20,
        'trend_strength':   0.15,
        'earnings_quality': 0.15,
        'relative_strength':0.15,
        'news_sentiment':   0.10,
        'volume_confirm':   0.10,
        'low_volatility':   0.05,   # inverted volatility
        'delivery_pct':     0.05,
        'historical_sharpe':0.05,
    }

    # Regime-adjusted weight overrides
    REGIME_WEIGHTS: Dict[str, Dict[str, float]] = {
        'TRENDING': {
            'momentum': 0.30,
            'trend_strength': 0.20,
            'earnings_quality': 0.10,
            'relative_strength': 0.15,
            'news_sentiment': 0.05,
            'volume_confirm': 0.10,
            'low_volatility': 0.03,
            'delivery_pct': 0.02,
            'historical_sharpe': 0.05,
        },
        'SIDEWAYS': {
            'momentum': 0.10,
            'trend_strength': 0.05,
            'earnings_quality': 0.20,
            'relative_strength': 0.15,
            'news_sentiment': 0.15,
            'volume_confirm': 0.10,
            'low_volatility': 0.10,
            'delivery_pct': 0.05,
            'historical_sharpe': 0.10,   # favor stability in sideways
        },
        'VOLATILE': {
            'momentum': 0.15,
            'trend_strength': 0.10,
            'earnings_quality': 0.10,
            'relative_strength': 0.10,
            'news_sentiment': 0.10,
            'volume_confirm': 0.10,
            'low_volatility': 0.20,
            'delivery_pct': 0.05,
            'historical_sharpe': 0.10,
        },
    }

    def __init__(self, event_bus, config: Dict):
        super().__init__(event_bus=event_bus, config=config, name="SIGMA")

        self.top_n = config.get('SIGMA_TOP_N', 10)   # candidate pool size
        self.score_cache: Dict[str, Dict] = {}        # last scores per symbol
        self.total_scored = 0

        logger.info(f"SIGMA Agent initialized - will rank top {self.top_n} stocks")

    # ── public API ───────────────────────────────────────────────────────────

    def score_stocks(
        self,
        stocks: List[Dict[str, Any]],
        regime: str = 'NEUTRAL'
    ) -> List[Dict[str, Any]]:
        """
        Score and rank a list of candidate stocks.

        Args:
            stocks: List of dicts, each with at minimum {'symbol': str} plus
                    optional factor values (momentum, rsi, volume, etc.)
            regime: Current market regime for weight adaptation.

        Returns:
            Sorted list (highest score first) with 'sigma_score' added.
        """
        weights = self.REGIME_WEIGHTS.get(regime, self.DEFAULT_WEIGHTS)

        scored: List[Dict] = []
        for stock in stocks:
            score = self._calculate_score(stock, weights)
            entry = {**stock, 'sigma_score': score}
            self.score_cache[stock['symbol']] = entry
            scored.append(entry)
            self.total_scored += 1

        ranked = sorted(scored, key=lambda x: x['sigma_score'], reverse=True)

        # Emit top picks as events
        for candidate in ranked[:self.top_n]:
            self.publish_event(
                EventType.SIGNAL_GENERATED,
                {
                    'symbol': candidate['symbol'],
                    'sigma_score': candidate['sigma_score'],
                    'regime': regime,
                    'timestamp': datetime.now().isoformat()
                }
            )

        logger.info(
            f"SIGMA scored {len(stocks)} stocks | "
            f"Top pick: {ranked[0]['symbol']} ({ranked[0]['sigma_score']:.3f})"
            if ranked else "SIGMA: no stocks to score"
        )

        return ranked

    def get_score(self, symbol: str) -> Optional[Dict]:
        """Return the last cached score for a symbol."""
        return self.score_cache.get(symbol)

    # ── internals ────────────────────────────────────────────────────────────

    def _calculate_score(self, stock: Dict[str, Any], weights: Dict[str, float]) -> float:
        """
        8-factor composite score.

        Factor normalisation:
        - momentum / trend_strength / relative_strength / volume_confirm /
          earnings_quality / fii_interest: 0–1 (higher = better)
        - volatility: 0–1 (lower = better → inverted as low_volatility)
        - news_sentiment: 0–1 (0.5 = neutral)
        """
        score = 0.0

        score += stock.get('momentum',          0.0) * weights.get('momentum',          0)
        score += stock.get('trend_strength',     0.0) * weights.get('trend_strength',    0)
        score += stock.get('earnings_quality',   0.0) * weights.get('earnings_quality',  0)
        score += stock.get('relative_strength',  0.0) * weights.get('relative_strength', 0)
        score += stock.get('news_sentiment',     0.5) * weights.get('news_sentiment',    0)
        score += stock.get('volume_confirm',     0.0) * weights.get('volume_confirm',    0)

        # Invert volatility so low-vol stocks score higher
        vol = stock.get('volatility', 0.5)
        score += (1.0 - min(vol, 1.0)) * weights.get('low_volatility', 0)

        score += stock.get('delivery_pct', 0.0) * weights.get('delivery_pct', 0)

        return round(score, 4)

    def get_stats(self) -> Dict[str, Any]:
        """Get SIGMA statistics."""
        top_symbol = (
            max(self.score_cache, key=lambda s: self.score_cache[s]['sigma_score'])
            if self.score_cache else 'N/A'
        )
        return {
            'name': self.name,
            'active': self.is_active,
            'total_scored': self.total_scored,
            'cached_symbols': len(self.score_cache),
            'current_top': top_symbol,
            'kpi': 'Top-5 beats NIFTY50 by > 5% monthly'
        }


# Allow standalone import of Optional for type hint
