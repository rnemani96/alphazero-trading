"""
src/risk/drawdown_breaker.py  —  AlphaZero Capital
════════════════════════════════════════════════════
FIX: Rolling 7-day and 30-day drawdown circuit breakers (was PARTIAL)
NEW: Portfolio rebalancing to target weights (was TODO)

DrawdownBreaker:
  - Tracks daily NAV (Net Asset Value) curve
  - Computes peak-to-trough drawdown over rolling 7d / 30d windows
  - Fires CIRCUIT_BREAK event when drawdown exceeds thresholds

PortfolioRebalancer:
  - Weekly rebalance to sigma-weighted target allocations
  - Generates BUY/SELL orders to bring positions back to target
"""

from __future__ import annotations

import os, json, logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from pathlib import Path

import numpy as np

logger = logging.getLogger("DrawdownBreaker")

_ROOT    = Path(__file__).resolve().parents[2]
_LOG_DIR = _ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_NAV_FILE = str(_LOG_DIR / "nav_history.json")


# ── NAV persistence ───────────────────────────────────────────────────────────

def _load_nav() -> Dict[str, float]:
    try:
        with open(_NAV_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_nav(nav: Dict[str, float]):
    with open(_NAV_FILE, "w") as f:
        json.dump(nav, f, indent=2)


# ── DrawdownBreaker ───────────────────────────────────────────────────────────

class DrawdownBreaker:
    """
    Rolling drawdown circuit breaker.

    Thresholds (configurable in .env):
      DRAWDOWN_7D_LIMIT  = 5%   (default) — 7-day rolling drawdown
      DRAWDOWN_30D_LIMIT = 10%  (default) — 30-day rolling drawdown

    When breached: publishes CIRCUIT_BREAK event, suspends trading.
    """

    def __init__(self, event_bus=None, cfg: Optional[Dict] = None):
        self.event_bus = event_bus
        cfg = cfg or {}
        self.limit_7d  = float(os.getenv('DRAWDOWN_7D_LIMIT',  cfg.get('DRAWDOWN_7D_LIMIT',  5.0)))
        self.limit_30d = float(os.getenv('DRAWDOWN_30D_LIMIT', cfg.get('DRAWDOWN_30D_LIMIT', 10.0)))
        self.nav_history = _load_nav()
        self._breached   = False

    def record_nav(self, nav: float):
        """Record today's portfolio NAV. Call once per day at market close."""
        key = date.today().isoformat()
        self.nav_history[key] = nav
        _save_nav(self.nav_history)
        logger.debug(f"NAV recorded: {key} = ₹{nav:,.0f}")

    def _nav_series(self, days: int) -> List[float]:
        """Return NAV values for the last N calendar days."""
        today  = date.today()
        series = []
        for i in range(days, 0, -1):
            d = (today - timedelta(days=i)).isoformat()
            if d in self.nav_history:
                series.append(self.nav_history[d])
        return series

    def rolling_drawdown(self, days: int) -> float:
        """
        Compute peak-to-trough drawdown % over last N days.
        Returns positive number (e.g. 3.5 = 3.5% drawdown).
        """
        series = self._nav_series(days)
        if len(series) < 2:
            return 0.0
        peak = max(series)
        if peak <= 0:
            return 0.0
        trough = min(series)
        return round((peak - trough) / peak * 100, 2)

    def check(self, current_nav: Optional[float] = None) -> Dict:
        """
        Check drawdown limits. Returns status dict.
        Fires CIRCUIT_BREAK event if any limit breached.

        Returns:
          {breached: bool, reason: str, dd_7d: float, dd_30d: float}
        """
        if current_nav is not None:
            self.record_nav(current_nav)

        dd_7d  = self.rolling_drawdown(7)
        dd_30d = self.rolling_drawdown(30)

        status = {
            "breached": False,
            "reason":   "",
            "dd_7d":    dd_7d,
            "dd_30d":   dd_30d,
            "limit_7d": self.limit_7d,
            "limit_30d":self.limit_30d,
        }

        if dd_7d >= self.limit_7d:
            status["breached"] = True
            status["reason"]   = f"7-day drawdown {dd_7d:.1f}% ≥ {self.limit_7d}% limit"
            logger.warning(f"CIRCUIT BREAK: {status['reason']}")
            self._fire_circuit_break(status)

        elif dd_30d >= self.limit_30d:
            status["breached"] = True
            status["reason"]   = f"30-day drawdown {dd_30d:.1f}% ≥ {self.limit_30d}% limit"
            logger.warning(f"CIRCUIT BREAK: {status['reason']}")
            self._fire_circuit_break(status)

        else:
            self._breached = False

        return status

    def _fire_circuit_break(self, status: Dict):
        if not self._breached:   # Fire only once per breach
            self._breached = True
            if self.event_bus:
                try:
                    self.event_bus.publish("CIRCUIT_BREAK", status)
                except Exception as e:
                    logger.error(f"Event bus publish failed: {e}")

    @property
    def is_breached(self) -> bool:
        return self._breached

    def reset(self):
        """Manually reset circuit breaker (e.g. after reviewing positions)."""
        self._breached = False
        logger.info("Circuit breaker manually reset")

    def summary(self) -> Dict:
        return {
            "dd_7d":    self.rolling_drawdown(7),
            "dd_30d":   self.rolling_drawdown(30),
            "limit_7d": self.limit_7d,
            "limit_30d":self.limit_30d,
            "breached": self._breached,
            "nav_days": len(self.nav_history),
        }


# ── Portfolio Rebalancer ──────────────────────────────────────────────────────

class PortfolioRebalancer:
    """
    Weekly portfolio rebalancer.
    Generates BUY/SELL orders to bring current weights back to targets.

    Called by main.py every Sunday night (or configurable schedule).
    """

    def __init__(self, event_bus=None, cfg: Optional[Dict] = None):
        self.event_bus = event_bus
        self.cfg       = cfg or {}
        self.drift_threshold = float(os.getenv('REBALANCE_DRIFT_PCT',
                                    cfg.get('REBALANCE_DRIFT_PCT', 2.0)))

    def compute_rebalance_orders(self,
                                  current_positions: Dict[str, Dict],
                                  target_weights:    Dict[str, float],
                                  current_prices:    Dict[str, float],
                                  total_capital:     float) -> List[Dict]:
        """
        Compute rebalancing orders.

        Args:
          current_positions: {symbol: {shares: int, avg_price: float}}
          target_weights:    {symbol: target_weight_pct (0-100)}
          current_prices:    {symbol: current_price}
          total_capital:     total portfolio value in ₹

        Returns list of orders:
          [{symbol, action: BUY/SELL, shares, reason}]
        """
        orders = []

        # Compute current weights
        current_values = {}
        portfolio_value = 0.0
        for sym, pos in current_positions.items():
            price = current_prices.get(sym, pos.get('avg_price', 0))
            val   = pos.get('shares', 0) * price
            current_values[sym] = val
            portfolio_value     += val

        if portfolio_value <= 0:
            portfolio_value = total_capital

        for sym, target_pct in target_weights.items():
            target_val   = (target_pct / 100.0) * portfolio_value
            current_val  = current_values.get(sym, 0.0)
            drift        = abs(target_val - current_val) / portfolio_value * 100

            if drift < self.drift_threshold:
                continue  # Within tolerance

            price = current_prices.get(sym, 0)
            if price <= 0:
                continue

            diff_val = target_val - current_val
            shares   = int(abs(diff_val) / price)

            if shares == 0:
                continue

            action = "BUY" if diff_val > 0 else "SELL"
            orders.append({
                "symbol":       sym,
                "action":       action,
                "shares":       shares,
                "price":        price,
                "target_pct":   target_pct,
                "current_pct":  round(current_val / portfolio_value * 100, 2),
                "drift_pct":    round(drift, 2),
                "reason":       f"Rebalance: target {target_pct:.1f}% current {current_val/portfolio_value*100:.1f}%",
            })

        if orders:
            logger.info(f"Rebalance: {len(orders)} orders generated")
            if self.event_bus:
                try:
                    self.event_bus.publish("REBALANCE_ORDERS", {"orders": orders})
                except Exception:
                    pass

        return orders

    def should_rebalance(self) -> bool:
        """Return True if today is the configured rebalance day (Sunday by default)."""
        rebalance_day = int(os.getenv('REBALANCE_DAY', '6'))  # 0=Mon, 6=Sun
        return date.today().weekday() == rebalance_day
