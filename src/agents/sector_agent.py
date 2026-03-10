"""
ATLAS Agent - Sector Analysis & Allocation
src/agents/sector_agent.py

Responsibilities:
- Determine optimal sector weights based on market regime
- Score stocks within their respective sectors using multi-factor analysis
- Provide sector context to the CHIEF agent for portfolio construction
- KPI: Sector-weighted alpha > 3% above NIFTY50
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from ..event_bus.event_bus import BaseAgent, EventType
from config.sectors import SECTORS, get_sector

logger = logging.getLogger(__name__)


class SectorAgent(BaseAgent):
    """
    ATLAS - Sector Strategy Agent
    
    Determines WHICH sectors to overweight/underweight based on the regime,
    and HOW to rank stocks within those sectors.
    """

    # Default sector weights (equally weighted)
    DEFAULT_ALLOCATION: Dict[str, float] = {
        sector: 1.0 / len(SECTORS) for sector in SECTORS
    }

    # Regime-based sector allocations (relative weights)
    # These determine how much capital CHIEF allocates to each sector
    REGIME_ALLOCATIONS: Dict[str, Dict[str, float]] = {
        'TRENDING': {
            'BANKING': 0.18, 'IT': 0.18, 'AUTO': 0.12, 'ENERGY': 0.12,
            'FINANCE': 0.10, 'INFRA': 0.08, 'METALS': 0.08, 'PHARMA': 0.05,
            'FMCG': 0.05, 'TELECOM': 0.04
        },
        'SIDEWAYS': {
            'FMCG': 0.20, 'PHARMA': 0.20, 'IT': 0.15, 'BANKING': 0.10,
            'TELECOM': 0.10, 'ENERGY': 0.10, 'AUTO': 0.05, 'FINANCE': 0.05,
            'METALS': 0.03, 'INFRA': 0.02
        },
        'VOLATILE': {
            'PHARMA': 0.25, 'FMCG': 0.25, 'IT': 0.15, 'ENERGY': 0.10,
            'TELECOM': 0.08, 'BANKING': 0.05, 'FINANCE': 0.05, 'AUTO': 0.03,
            'METALS': 0.02, 'INFRA': 0.02
        },
        'RISK_OFF': {
            'PHARMA': 0.30, 'FMCG': 0.30, 'IT': 0.10, 'TELECOM': 0.10,
            'ENERGY': 0.10, 'BANKING': 0.02, 'FINANCE': 0.02, 'AUTO': 0.02,
            'METALS': 0.02, 'INFRA': 0.02
        }
    }

    def __init__(self, event_bus, config: Dict):
        super().__init__(event_bus=event_bus, config=config, name="ATLAS")
        
        self.current_allocations = self.DEFAULT_ALLOCATION.copy()
        self.last_update = datetime.now()
        
        # Internal state for tracking performance
        self.sector_performance: Dict[str, float] = {sector: 0.0 for sector in SECTORS}
        
        logger.info("ATLAS Agent initialized - Sector analysis ready")

    # ── public API ───────────────────────────────────────────────────────────

    def get_sector_allocation(self, regime: str = 'NEUTRAL') -> Dict[str, float]:
        """
        Return the optimal sector weights for the current regime.
        CHIEF uses this to determine position sizing.
        """
        alloc = self.REGIME_ALLOCATIONS.get(regime, self.DEFAULT_ALLOCATION)
        self.current_allocations = alloc
        self.last_update = datetime.now()
        
        self.publish_event(
            EventType.MACRO_UPDATE, # Re-using MACRO_UPDATE for sector shifts
            {
                'source': 'ATLAS',
                'regime': regime,
                'allocations': alloc,
                'timestamp': self.last_update.isoformat()
            }
        )
        
        return alloc

    def score_stocks(self, stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Score stocks using a sector-relative multi-factor model.
        Higher score = better candidate within its sector.
        """
        scored = []
        for stock in stocks:
            symbol = stock.get('symbol', 'UNKNOWN')
            sector = get_sector(symbol)
            
            # 8-factor scoring model (sector-relative)
            score = self._calculate_score(stock)
            
            scored_stock = {
                **stock,
                'sector': sector,
                'atlas_score': score,
                'last_scored': datetime.now().isoformat()
            }
            scored.append(scored_stock)
            
        # Return top 5 as per previous stub requirement, but keep all if needed
        return sorted(scored, key=lambda x: x['atlas_score'], reverse=True)

    # ── internals ────────────────────────────────────────────────────────────

    def _calculate_score(self, stock: Dict[str, Any]) -> float:
        """
        Calculate a composite score (0-1) based on 8 key factors.
        """
        score = 0.0
        
        # Momentum (20%)
        score += stock.get('momentum', 0.5) * 0.20
        
        # Trend Strength (15%)
        score += stock.get('trend_strength', 0.5) * 0.15
        
        # Earnings Quality (15%)
        score += stock.get('earnings_quality', 0.5) * 0.15
        
        # Relative Strength (15%)
        score += stock.get('relative_strength', 0.5) * 0.15
        
        # News Sentiment (10%) - 0.5 is neutral
        score += stock.get('news_sentiment', 0.5) * 0.10
        
        # Volume Confirmation (10%)
        score += stock.get('volume_confirm', 0.5) * 0.10
        
        # Low Volatility (10%) - Invert volatility if it's 0-1
        vol = stock.get('volatility', 0.5)
        score += (1.0 - min(max(vol, 0.0), 1.0)) * 0.10
        
        # Institutional (FII) Interest (5%)
        score += stock.get('fii_interest', 0.5) * 0.05
        
        return round(score, 4)

    def get_stats(self) -> Dict[str, Any]:
        """Get ATLAS statistics."""
        return {
            'name': self.name,
            'active': self.is_active,
            'last_update': self.last_update.isoformat(),
            'top_sector': max(self.current_allocations, key=self.current_allocations.get),
            'kpi': 'Sector-weighted alpha > 3% quarterly'
        }
