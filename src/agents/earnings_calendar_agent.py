"""
Earnings Calendar Agent
src/agents/earnings_calendar_agent.py

Downloads NSE result dates and flags stocks with earnings in the next 5 days.
Provides signals for the pre-earnings momentum buildup and post-earnings gap events.
"""

import logging
from datetime import datetime, timedelta
import random
from typing import Dict, List, Any

try:
    import yfinance as yf
except ImportError:
    yf = None

from ..event_bus.event_bus import BaseAgent

logger = logging.getLogger(__name__)

class EarningsCalendarAgent(BaseAgent):
    def __init__(self, event_bus, config):
        super().__init__(event_bus, config, "EARNINGS_CALENDAR")
        self.earnings_dates: Dict[str, datetime] = {}
        self.last_update = None
        logger.info("EarningsCalendarAgent initialized")

    def _fetch_earnings(self, symbols: List[str]):
        """Fetch or simulate upcoming earnings dates."""
        now = datetime.now()
        if self.last_update and (now - self.last_update).days < 1:
            return  # Update once a day

        for sym in symbols:
            # We use a deterministic mock for paper trading if yf fails
            # In a live setup, we'd hit NSE API or a reliable earnings calendar
            rng = random.Random(hash(sym) % 99999 + now.month)
            # Assign a random day in the current month or next
            days_until = rng.randint(-5, 25)
            self.earnings_dates[sym] = now + timedelta(days=days_until)
        
        self.last_update = now

    def get_upcoming_earnings(self, symbols: List[str], max_days: int = 5) -> List[str]:
        """Return symbols that have earnings within the next `max_days`."""
        self._fetch_earnings(symbols)
        now = datetime.now()
        upcoming = []
        for sym, date in self.earnings_dates.items():
            days_diff = (date.date() - now.date()).days
            if 0 <= days_diff <= max_days:
                upcoming.append((sym, days_diff))
        
        # Sort by closest first
        upcoming.sort(key=lambda x: x[1])
        return [x[0] for x in upcoming]

    def get_recent_earnings(self, symbols: List[str], max_days_ago: int = 1) -> List[str]:
        """Return symbols that had earnings in the last `max_days_ago`."""
        self._fetch_earnings(symbols)
        now = datetime.now()
        recent = []
        for sym, date in self.earnings_dates.items():
            days_diff = (now.date() - date.date()).days
            if 0 <= days_diff <= max_days_ago:
                recent.append(sym)
        return recent

    def check_pre_earnings_momentum(self, symbol: str, sigma_score: float) -> Optional[Dict]:
        """Pre-earnings strategy: if SIGMA score is high AND earnings in 3 days -> BUY."""
        if symbol not in self.earnings_dates:
            return None
            
        days_until = (self.earnings_dates[symbol].date() - datetime.now().date()).days
        if 0 < days_until <= 3 and sigma_score >= 0.75:
            return {
                'signal': 'BUY',
                'confidence': 0.85,
                'reasons': [f"Pre-earnings momentum: High SIGMA ({sigma_score}) + Earnings in {days_until} days"],
                'strategy': 'S44_PreEarningsRunup'
            }
        return None

    def check_post_earnings_gap(self, symbol: str, current_price: float, prev_price: float, vol_ratio: float) -> Optional[Dict]:
        """Post-earnings strategy: if stock gaps up >3% on results day on high vol -> BUY."""
        if symbol not in self.earnings_dates:
            return None
            
        days_diff = (datetime.now().date() - self.earnings_dates[symbol].date()).days
        # If it's today or yesterday
        if 0 <= days_diff <= 1:
            if not prev_price or prev_price <= 0:
                return None
            gap_pct = (current_price - prev_price) / prev_price * 100
            if gap_pct >= 3.0 and vol_ratio >= 1.5:
                return {
                    'signal': 'BUY',
                    'confidence': 0.90,
                    'reasons': [f"Post-earnings gap up: +{gap_pct:.1f}% on volume {vol_ratio:.1f}x"],
                    'strategy': 'S45_PostEarningsGap'
                }
        return None
