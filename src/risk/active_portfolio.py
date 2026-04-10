"""
src/risk/active_portfolio.py  —  AlphaZero Capital
═══════════════════════════════════════════════════════
Active Portfolio State Manager  (v2.0)

PURPOSE:
  - Persistently tracks every open (non-intraday) position
  - Once a stock is invested, it stays locked until:
      a) Target price is reached  → auto-close, mark COMPLETED
      b) Stop-loss is hit          → auto-close, mark STOPPED
      c) Manual override          → force-close, mark OVERRIDE
  - While a position is OPEN, the system will NOT take another
    position in the same stock (or new stocks beyond MAX_POSITIONS)
  - Intraday trades bypass this guard (they have their own manager)

STORAGE:
  - JSON file at  data/active_portfolio.json  (auto-created)
  - Updated on every price tick and on every trade event
  - Human-readable, editable for manual overrides

USAGE (in main.py):
    from src.risk.active_portfolio import ActivePortfolio
    ap = ActivePortfolio()
    # Check before sending a new swing/positional trade
    if ap.can_add_position(symbol):
        ap.open_position(symbol, entry_price, qty, target, stop_loss, strategy)
    # Update prices every tick
    ap.update_prices({"RELIANCE": 2450, "TCS": 3600})
    # Get summary for dashboard
    summary = ap.get_summary()
"""

from __future__ import annotations
import json
import logging
import os
import threading
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("ActivePortfolio")
IST    = ZoneInfo("Asia/Kolkata")

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "active_portfolio.json")


class PositionStatus:
    OPEN      = "OPEN"
    TARGET    = "TARGET_HIT"
    STOPPED   = "STOP_HIT"
    OVERRIDE  = "FORCE_CLOSED"
    EXPIRED   = "EXPIRED"


class ActivePortfolio:
    """
    Persistent, thread-safe active portfolio manager.

    Positions dict schema per symbol:
    {
      "symbol":       "RELIANCE",
      "entry_price":  2400.0,
      "quantity":     10,
      "target":       2550.0,    # auto-calc if not provided: +6% ATR-based
      "stop_loss":    2350.0,    # auto-calc if not provided: -2.5%
      "current_price": 2430.0,
      "unrealised_pnl": 300.0,
      "pnl_pct":      1.25,
      "strategy":     "T1 EMA Cross",
      "trade_type":   "SWING",   # SWING | POSITIONAL | INTRADAY
      "status":       "OPEN",
      "opened_at":    "2026-03-12T09:15:00",
      "closed_at":    null,
      "close_reason": null,
      "max_days":     30,        # force-close after N days (positional default)
      "days_open":    3,
      "highest_price": 2460.0,  # for trailing stop tracking
      "trailing_stop": 2400.0,
      "target_pct":   6.25,
      "sl_pct":       2.08,
    }
    """

    def __init__(
        self,
        path:         str   = _DEFAULT_PATH,
        max_positions:int   = 10,
        default_target_pct: float = 6.0,   # 6% default target
        default_sl_pct:     float = 2.5,   # 2.5% default stop loss
        max_swing_days:     int   = 30,    # max holding period for SWING
        max_positional_days:int   = 90,    # max holding period for POSITIONAL
        initial_capital:    float = 1000000,
    ):
        self.path               = os.path.abspath(path)
        self.max_positions      = max_positions
        self.initial_capital     = initial_capital
        self.default_target_pct = default_target_pct
        self.default_sl_pct     = default_sl_pct
        self.max_swing_days     = max_swing_days
        self.max_positional_days = max_positional_days
        self._lock              = threading.Lock()

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._state: Dict[str, Any] = self._load()
        logger.info(
            "ActivePortfolio loaded — %d open positions | path=%s",
            len(self.open_positions), self.path,
        )

    # ── I/O ──────────────────────────────────────────────────────────────────

    def _load(self) -> Dict[str, Any]:
        """Load state from disk; create empty file if missing."""
        if not os.path.exists(self.path):
            empty = {"positions": {}, "history": [], "last_updated": ""}
            self._write(empty)
            return empty
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load portfolio state: %s — starting fresh", e)
            return {"positions": {}, "history": [], "last_updated": ""}

    def _write(self, state: Optional[Dict] = None):
        """Write current state to disk (atomic via temp file)."""
        s = state if state else self._state
        s["last_updated"] = datetime.now(IST).isoformat()
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(s, f, indent=2, default=str)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.error("Failed to write portfolio state: %s", e)

    def _save(self):
        """Thread-safe save (call while holding self._lock)."""
        self._write()

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def positions(self) -> Dict[str, Dict]:
        return self._state.get("positions", {})

    @property
    def open_positions(self) -> Dict[str, Dict]:
        return {k: v for k, v in self.positions.items() if v.get("status") == PositionStatus.OPEN}

    @property
    def history(self) -> List[Dict]:
        return self._state.get("history", [])

    # ── Core API ─────────────────────────────────────────────────────────────

    def can_add_position(self, symbol: str, trade_type: str = "SWING") -> Tuple[bool, str]:
        """
        Check whether the system is allowed to open a new position.

        Rules:
          1. Intraday trades always pass (managed separately).
          2. If the symbol already has an OPEN position → BLOCK.
          3. If total open positions >= max_positions → BLOCK.
          4. Otherwise → ALLOW.

        Returns (allowed: bool, reason: str).
        """
        from typing import Tuple  # local import to avoid top-level circular
        if trade_type == "INTRADAY":
            return True, "Intraday always allowed"
        with self._lock:
            key = f"{symbol}:{trade_type}"
            if key in self.open_positions:
                pos    = self.open_positions[symbol]
                target = pos.get("target", 0)
                curr   = pos.get("current_price", pos.get("entry_price", 0))
                pnl_pct = pos.get("pnl_pct", 0)
                return (
                    False,
                    f"{symbol} already invested | Entry ₹{pos['entry_price']:.0f} → "
                    f"Target ₹{target:.0f} | Current ₹{curr:.0f} | P&L {pnl_pct:+.2f}%",
                )
            open_count = len(self.open_positions)
            if open_count >= self.max_positions:
                return (
                    False,
                    f"Max positions reached ({open_count}/{self.max_positions}). "
                    f"Wait for existing positions to hit target before adding new ones.",
                )
        return True, "OK"

    def open_position(
        self,
        symbol:     str,
        entry_price: float,
        quantity:   int,
        target:     Optional[float] = None,
        stop_loss:  Optional[float] = None,
        strategy:   str = "",
        trade_type: str = "SWING",   # SWING | POSITIONAL | INTRADAY
        atr:        float = 0.0,
        sector:     str   = "",
        confidence: float = 0.0,
        broker_id:  str   = "",
        regime:     str   = "UNKNOWN",
        direction:  str   = "BUY",    # BUY (Long) | SELL (Short)
    ) -> Dict:
        """Register a new open position."""
        with self._lock:
            # Fallback targets if not provided
            if direction.upper() == "BUY":
                t = target    or round(entry_price * (1 + self.default_target_pct / 100), 2)
                sl = stop_loss or round(entry_price * (1 - self.default_sl_pct / 100), 2)
            else:
                t = target    or round(entry_price * (1 - self.default_target_pct / 100), 2)
                sl = stop_loss or round(entry_price * (1 + self.default_sl_pct / 100), 2)

            max_days = self.max_positional_days if trade_type == "POSITIONAL" else self.max_swing_days
            pos = {
                "symbol":        symbol,
                "entry_price":   round(entry_price, 2),
                "quantity":      quantity,
                "target":        round(t, 2),
                "stop_loss":     round(sl, 2),
                "current_price": round(entry_price, 2),
                "unrealised_pnl": 0.0,
                "pnl_pct":       0.0,
                "strategy":      strategy,
                "trade_type":    trade_type,
                "regime":        regime,
                "direction":     direction.upper(),
                "status":        PositionStatus.OPEN,
                "opened_at":     datetime.now(IST).isoformat(),
                "closed_at":     None,
                "close_reason":  None,
                "max_days":      max_days,
                "days_open":     0,
                "highest_price": round(entry_price, 2),
                "lowest_price":  round(entry_price, 2),
                "trailing_stop": round(sl, 2),
                "target_dist":   abs(t - entry_price),
                "sl_dist":       abs(entry_price - sl),
                "scale_out_done": False,
                "breakeven_done": False,
                "atr":           round(atr, 2),
                "sector":        sector,
                "confidence":    round(confidence, 3),
                "invested_amount": round(entry_price * quantity, 2),
                "broker_id":     broker_id,
            }
            key = f"{symbol}:{trade_type}"
            self._state["positions"][key] = pos
            self._save()
            logger.info(
                "[ActivePortfolio] OPENED %s %s × %d @ ₹%.2f | Target ₹%.2f | SL ₹%.2f | %s",
                pos["direction"], symbol, quantity, entry_price, t, sl, strategy,
            )
            return pos

    def update_prices(self, price_map: Dict[str, float]):
        """
        Update current prices for all open positions and check target/SL.
        direction-aware P&L and exits.
        Returns: (closed_positions, updated_stops, partial_exits)
        """
        closed_this_tick: List[Dict] = []
        updated_stops: List[Dict]    = []
        partial_exits: List[Dict]    = []
        with self._lock:
            for key, pos in list(self.positions.items()):
                sym = pos.get("symbol")
                if pos.get("status") != PositionStatus.OPEN:
                    continue
                price = price_map.get(sym)
                if not price:
                    continue

                ep     = pos["entry_price"]
                qty    = pos["quantity"]
                target = pos["target"]
                sl     = pos["stop_loss"]
                side   = pos.get("direction", "BUY")
                is_long = (target >= ep) if target else (side == "BUY")

                # ── Update current price & P&L (Direction Aware) ─────────────────
                if is_long:
                    pnl     = (price - ep) * qty
                    pnl_pct = (price - ep) / ep * 100
                else:
                    pnl     = (ep - price) * qty
                    pnl_pct = (ep - price) / ep * 100

                pos["current_price"]  = round(price, 2)
                pos["unrealised_pnl"] = round(pnl, 2)
                pos["pnl_pct"]        = round(pnl_pct, 2)

                # Track peaks for trailing
                highest = pos.get("highest_price", price)
                lowest  = pos.get("lowest_price", price)
                if price > highest: pos["highest_price"] = round(price, 2)
                if price < lowest:  pos["lowest_price"]  = round(price, 2)

                # ── Requirement #6: 0.5R Move -> Breakeven ───────────────────────
                initial_risk_dist = pos.get("sl_dist", abs(ep - sl))
                profit_dist = abs(price - ep) if pnl > 0 else 0
                
                if not pos.get("breakeven_done") and profit_dist >= (0.5 * initial_risk_dist):
                    new_sl = round(ep * 1.005 if is_long else ep * 0.995, 2)
                    pos["stop_loss"] = new_sl
                    pos["breakeven_done"] = True
                    updated_stops.append({
                        "symbol": sym, "new_sl": new_sl, "broker_id": pos.get("broker_id")
                    })
                    logger.info("🛡️ BREAKEVEN: %s %s moved to entry + 0.5%% after 0.5R move.", side, sym)

                # ── Requirement #6: 1.0R Move -> Partial Profit (50%) ───────────
                if not pos.get("scale_out_done") and profit_dist >= initial_risk_dist:
                    pos["scale_out_done"] = True
                    reduced_qty = max(1, pos["quantity"] // 2)
                    pos["quantity"] = pos["quantity"] - reduced_qty
                    pos["realised_pnl"] = pos.get("realised_pnl", 0) + (profit_dist * reduced_qty)
                    
                    partial_exits.append({
                        "symbol": sym,
                        "quantity": reduced_qty,
                        "action": "SELL" if is_long else "BUY",
                        "price": price,
                        "reason": "1R_SCALE_OUT"
                    })
                    logger.info("🚀 SCALE-OUT: %s %s 1R reached! Selling 50%% (%d shares).", side, sym, reduced_qty)

                # ── Dynamic Adaptive Trailing & Profit Preservation ──────────────
                atr = pos.get("atr", ep * 0.02)
                
                # ADAPTIVE TIGHTENING: The more we gain, the tighter we lock.
                trail_mult = 2.5
                if pnl_pct >= 3.0:    trail_mult = 1.0
                elif pnl_pct >= 2.0:  trail_mult = 1.5
                
                trail_buffer = max(ep * 0.015, trail_mult * atr)
                
                close_status = None
                reason = None
                
                if is_long:
                    trail_sl = round(pos["highest_price"] - trail_buffer, 2)
                    if trail_sl > pos.get("trailing_stop", 0):
                        pos["trailing_stop"] = trail_sl
                        updated_stops.append({"symbol": sym, "new_sl": trail_sl, "broker_id": pos.get("broker_id")})
                    
                    # ── Requirement #8: 'In-Hand' Protection ──────────────────
                    if pnl_pct > 1.25 and price < (ep * 1.005):
                        close_status = PositionStatus.STOPPED
                        reason = f"Profit Preservation: Protecting {pnl_pct:.1f}% gain. Closing at break-even+."
                else:
                    trail_sl = round(pos["lowest_price"] + trail_buffer, 2)
                    if trail_sl < pos.get("trailing_stop", float('inf')):
                        pos["trailing_stop"] = trail_sl
                        updated_stops.append({"symbol": sym, "new_sl": trail_sl, "broker_id": pos.get("broker_id")})
                    
                    if pnl_pct > 1.25 and price > (ep * 0.995):
                        close_status = PositionStatus.STOPPED
                        reason = f"Profit Preservation (Short): Protecting {pnl_pct:.1f}% gain."

                # ── Check exit conditions ──────────────────────────────────────
                if not close_status:
                    reason = None
                    if is_long:
                        eff_sl = max(sl, pos.get("trailing_stop", 0))
                        if price >= target:
                            reason = f"Target ₹{target:.2f} reached! P&L: ₹{pnl:+.0f}"
                            close_status = PositionStatus.TARGET
                        elif price <= eff_sl:
                            reason = f"Stop-loss ₹{eff_sl:.2f} hit. P&L: ₹{pnl:+.0f}"
                            close_status = PositionStatus.STOPPED
                    else:
                        # Shorting logic: SL is ABOVE, Target is BELOW
                        eff_sl = min(sl, pos.get("trailing_stop", float('inf')))
                        if price <= target:
                            reason = f"Short Target ₹{target:.2f} reached! P&L: ₹{pnl:+.0f}"
                            close_status = PositionStatus.TARGET
                        elif price >= eff_sl:
                            reason = f"Short SL ₹{eff_sl:.2f} hit. P&L: ₹{pnl:+.0f}"
                            close_status = PositionStatus.STOPPED
                
                if not close_status and pos["days_open"] >= pos.get("max_days", 30):
                    reason       = f"Max holding period {pos['max_days']} days reached."
                    close_status = PositionStatus.EXPIRED

                if close_status:
                    pos["status"]       = close_status
                    pos["closed_at"]    = datetime.now(IST).isoformat()
                    pos["close_reason"] = reason
                    pos["realised_pnl"] = round(pnl, 2)
                    pos["realised_pct"] = round(pnl_pct, 2)
                    closed_this_tick.append(pos.copy())
                    self._state["history"].append(pos.copy())
                    logger.info("[ActivePortfolio] CLOSED %s %s — %s | %s", side, sym, close_status, reason)

            self._save()
        return closed_this_tick, updated_stops, partial_exits

    def force_close(self, symbol: str, current_price: float, reason: str = "Manual override") -> Optional[Dict]:
        """Force-close a position (manual override / risk kill-switch)."""
        with self._lock:
            # Try to find exactly matched trade_type if possible, or any open for that symbol
            key = next((k for k, p in self.open_positions.items() if p['symbol'] == symbol), None)
            pos = self.positions.get(key)
            if not pos or pos.get("status") != PositionStatus.OPEN:
                logger.warning("[ActivePortfolio] %s not found in open positions.", symbol)
                return None
            
            ep  = pos["entry_price"]
            qty = pos["quantity"]
            side = pos.get("direction", "BUY")
            target = pos.get("target", ep)
            
            if target < ep:
                pnl = (ep - current_price) * qty
            else:
                pnl = (current_price - ep) * qty
                
            pos["current_price"]  = round(current_price, 2)
            pos["unrealised_pnl"] = round(pnl, 2)
            pos["pnl_pct"]        = round(pnl / (ep * qty) * 100, 2) if ep else 0
            pos["status"]         = PositionStatus.OVERRIDE
            pos["closed_at"]      = datetime.now(IST).isoformat()
            pos["close_reason"]   = reason
            pos["realised_pnl"]   = round(pnl, 2)
            pos["realised_pct"]   = pos["pnl_pct"]
            self._state["history"].append(pos.copy())
            self._save()
            logger.info("[ActivePortfolio] FORCE CLOSED %s %s @ ₹%.2f — %s", side, symbol, current_price, reason)
            return pos

    def adjust_target(self, symbol: str, new_target: float, trade_type: str = "SWING"):
        """Manually adjust target price for an open position."""
        with self._lock:
            key = f"{symbol}:{trade_type}"
            pos = self.positions.get(key)
            if pos and pos.get("status") == PositionStatus.OPEN:
                old = pos["target"]
                pos["target"]     = round(new_target, 2)
                pos["target_pct"] = round((new_target - pos["entry_price"]) / pos["entry_price"] * 100, 2)
                self._save()
                logger.info("[ActivePortfolio] %s target adjusted: ₹%.2f → ₹%.2f", symbol, old, new_target)

    def adjust_stop_loss(self, symbol: str, new_sl: float, trade_type: str = "SWING"):
        """Manually adjust stop-loss for an open position."""
        with self._lock:
            key = f"{symbol}:{trade_type}"
            pos = self.positions.get(key)
            if pos and pos.get("status") == PositionStatus.OPEN:
                old = pos["stop_loss"]
                pos["stop_loss"] = round(new_sl, 2)
                pos["sl_pct"]    = round((pos["entry_price"] - new_sl) / pos["entry_price"] * 100, 2)
                self._save()
                logger.info("[ActivePortfolio] %s SL adjusted: ₹%.2f → ₹%.2f", symbol, old, new_sl)

    # ── Summary / Dashboard API ───────────────────────────────────────────────

    def get_summary(self) -> Dict[str, Any]:
        """Return complete portfolio summary for dashboard rendering."""
        with self._lock:
            open_pos  = list(self.open_positions.values())
            hist      = self.history[-500:]  # Consider last 500 for stats

            total_invested = sum(p["invested_amount"] for p in open_pos)
            total_pnl      = sum(p["unrealised_pnl"] for p in open_pos)
            closed_pnl     = sum(p.get("realised_pnl", 0) for p in hist)

            winning  = [p for p in hist if p.get("realised_pnl", 0) > 0]
            losing   = [p for p in hist if p.get("realised_pnl", 0) <= 0]
            win_rate = len(winning) / max(len(hist), 1) * 100

            near_target = [
                p for p in open_pos
                if p["target"] > 0 and p["current_price"] > 0 and
                (p["target"] - p["current_price"]) / p["target"] < 0.02
            ]
            near_sl = [
                p for p in open_pos
                if p["stop_loss"] > 0 and p["current_price"] > 0 and
                (p["current_price"] - p["stop_loss"]) / p["current_price"] < 0.015
            ]

            return {
                "open_positions":   open_pos,
                "total_open":       len(open_pos),
                "max_positions":    self.max_positions,
                "slots_available":  self.max_positions - len(open_pos),
                "initial_capital":  round(self.initial_capital, 2),
                "total_invested":   round(total_invested, 2),
                "total_unrealised_pnl": round(total_pnl, 2),
                "total_realised_pnl":   round(closed_pnl, 2),
                "win_rate_pct":     round(win_rate, 1),
                "total_trades":     len(hist),
                "winning_trades":   len(winning),
                "losing_trades":    len(losing),
                "near_target":      [p["symbol"] for p in near_target],
                "near_sl":          [p["symbol"] for p in near_sl],
                "history":          hist,                 # send full relevant history to dashboard
                "last_updated":     self._state.get("last_updated", ""),
                "blocked_symbols":  [p["symbol"] for p in open_pos if p.get("trade_type") != "INTRADAY"],
            }

    def get_position(self, symbol: str, trade_type: str = "SWING") -> Optional[Dict]:
        """Get current position data for a specific symbol and type."""
        return self.positions.get(f"{symbol}:{trade_type}")

    def is_invested(self, symbol: str, trade_type: str = "SWING") -> bool:
        """Quick check if a symbol has an active open position of specified type."""
        return f"{symbol}:{trade_type}" in self.open_positions

    def get_progress(self, symbol: str) -> Optional[Dict]:
        """
        Return progress toward target for a symbol.

        Returns:
          {
            "pct_to_target": 42.5,    # how far to target (% of distance covered)
            "pct_to_sl":     85.0,    # how far from SL
            "status_label":  "On Track",
            "action_needed": False,
          }
        """
        pos = self.open_positions.get(symbol)
        if not pos:
            return None
        ep    = pos["entry_price"]
        curr  = pos["current_price"]
        tgt   = pos["target"]
        sl    = pos["stop_loss"]

        dist_total = tgt - ep
        dist_done  = curr - ep
        pct_to_tgt = round(dist_done / dist_total * 100, 1) if dist_total else 0

        dist_sl    = curr - sl
        dist_total_sl = ep - sl
        pct_from_sl = round(dist_sl / max(dist_total_sl, 0.01) * 100, 1)

        if pct_to_tgt >= 90:
            label = "🎯 Almost at Target"
        elif pct_to_tgt > 50:
            label = "✅ On Track"
        elif pct_to_tgt > 0:
            label = "📈 In Progress"
        elif pct_from_sl < 20:
            label = "⚠️ Near Stop Loss"
        else:
            label = "📉 Below Entry"

        return {
            "symbol":        symbol,
            "entry":         ep,
            "current":       curr,
            "target":        tgt,
            "stop_loss":     sl,
            "pct_to_target": pct_to_tgt,
            "pct_from_sl":   pct_from_sl,
            "pnl_pct":       pos["pnl_pct"],
            "unrealised_pnl": pos["unrealised_pnl"],
            "status_label":  label,
            "days_open":     pos.get("days_open", 0),
            "max_days":      pos.get("max_days", 30),
            "action_needed": pct_from_sl < 15,
        }

    # ── Performance Stats ─────────────────────────────────────────────────────

    def get_performance_stats(self, days: int = 30) -> Dict:
        """Compute performance metrics over the last N days."""
        cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat()
        recent = [p for p in self.history if p.get("closed_at", "") >= cutoff]
        if not recent:
            return {"trades": 0}
        pnls     = [p.get("realised_pnl", 0) for p in recent]
        win_pnls = [p for p in pnls if p > 0]
        los_pnls = [p for p in pnls if p <= 0]
        total    = sum(pnls)
        avg_win  = sum(win_pnls) / max(len(win_pnls), 1)
        avg_los  = sum(los_pnls) / max(len(los_pnls), 1)
        pf       = abs(sum(win_pnls)) / max(abs(sum(los_pnls)), 1)
        return {
            "period_days":    days,
            "trades":         len(recent),
            "winners":        len(win_pnls),
            "losers":         len(los_pnls),
            "win_rate":       round(len(win_pnls) / max(len(recent), 1) * 100, 1),
            "total_pnl":      round(total, 2),
            "avg_win":        round(avg_win, 2),
            "avg_loss":       round(avg_los, 2),
            "profit_factor":  round(pf, 2),
            "best_trade":     max(pnls) if pnls else 0,
            "worst_trade":    min(pnls) if pnls else 0,
            "target_hits":    len([p for p in recent if p.get("status") == PositionStatus.TARGET]),
            "sl_hits":        len([p for p in recent if p.get("status") == PositionStatus.STOPPED]),
        }


# ── Module-level singleton (use in main.py) ───────────────────────────────────
from typing import Tuple  # ensure Tuple is imported for can_add_position type hint

_AP_INSTANCE: Optional[ActivePortfolio] = None
_AP_LOCK = threading.Lock()

def get_active_portfolio(max_positions: int = 10, initial_capital: float = 1000000) -> ActivePortfolio:
    global _AP_INSTANCE
    with _AP_LOCK:
        if _AP_INSTANCE is None:
            _AP_INSTANCE = ActivePortfolio(max_positions=max_positions, initial_capital=initial_capital)
    return _AP_INSTANCE


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    ap = ActivePortfolio()

    # Test open position
    ap.open_position("RELIANCE", 2400, 10, target=2550, stop_loss=2360, strategy="T1 EMA Cross")
    ap.open_position("TCS",      3500, 5,  target=3700, stop_loss=3450, strategy="B2 Vol Breakout")

    # Can we add more?
    allowed, msg = ap.can_add_position("RELIANCE")
    print(f"Add RELIANCE: {allowed} — {msg}")

    allowed, msg = ap.can_add_position("INFY")
    print(f"Add INFY: {allowed} — {msg}")

    # Update prices
    ap.update_prices({"RELIANCE": 2555, "TCS": 3510})

    print("\nSummary:")
    summary = ap.get_summary()
    print(f"Open: {summary['total_open']}, Invested: ₹{summary['total_invested']:,.0f}, "
          f"P&L: ₹{summary['total_unrealised_pnl']:+,.0f}")
    print(f"Near target: {summary['near_target']}")
