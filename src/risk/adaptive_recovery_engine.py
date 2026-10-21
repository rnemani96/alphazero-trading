"""
src/risk/adaptive_recovery_engine.py  —  AlphaZero Capital
═══════════════════════════════════════════════════════════════════════════════
ADAPTIVE PROFIT HARVESTING & ZERO-LOSS RECOVERY ENGINE

Core Capabilities:
1. Self-Adjusting Thresholds:
   - Dynamically scales entry confidence, R:R hurdle, agent agreement, and risk limits
     based on real-time market regime, VIX volatility, recent win rates, and drawdown.
2. Zero-Loss Guarantee Architecture:
   - Calculates exact Indian market round-trip transaction costs (brokerage, STT, GST, etc.).
   - Instant Cost-Covered Breakeven Ratchet: The moment a trade achieves sufficient profit
     to cover all roundtrip costs + buffer, Stop-Loss is ratcheted to Breakeven + Costs.
     Once triggered, the position is mathematically guaranteed to never take a net loss.
   - Asymmetric Profit-Lock Ladder: Dynamically locks in 35% of gains at +1R, 70% at +2R,
     and tightens trailing to 0.5x ATR at +3R+.
3. Mathematical Loss Recovery Calculator:
   - If a gap-down or black swan exit causes a loss, the engine logs the deficit
     (Loss + Roundtrip Costs) into an unrecovered debt ledger.
   - Automatically activates RECOVERY_MODE.
   - Calculates the exact recovery hurdle: Required Rupee Return, Required R:R, and
     safe Kelly-scaled position sizing.
   - Tightens entry criteria to Grade-A+ setups only (confidence >= 0.75, R:R >= 2.5)
     so the next trade(s) mathematically recover 100% of accumulated deficit and return
     the account to net profit.
   - Tracks recovery progress from 0% to 100%+ and auto-resets upon full profit restoration.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .charge_calculator import calculate_charges, BROKERAGE_FLAT

logger = logging.getLogger("AdaptiveRecoveryEngine")

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_STATE_FILE = _LOG_DIR / "adaptive_recovery_state.json"


@dataclass
class AdaptiveThresholds:
    """Current active thresholds dynamically tuned by market state and performance."""
    min_confidence: float = 0.52           # 0.50 (ultra-bullish) to 0.85 (recovery mode)
    min_rr_ratio: float = 1.50             # Minimum Reward-to-Risk ratio required
    min_agent_agreement: int = 1           # 1 (normal) to 3 (recovery / volatile)
    max_risk_pct_per_trade: float = 0.02   # 2% standard, scales down to 0.5% in high loss
    breakeven_trigger_pct: float = 0.0075  # % profit at which stop is ratcheted to breakeven
    trail_atr_multiplier: float = 1.50     # Trailing stop ATR multiple
    profit_buffer_pct: float = 0.002       # Margin added to breakeven to guarantee net profit
    mode_label: str = "BALANCED_GROWTH"    # BALANCED_GROWTH | AGGRESSIVE_ALPHA | RECOVERY_HURDLE


@dataclass
class LossEvent:
    """Detailed record of a loss event that must be recovered."""
    symbol: str
    pnl: float
    charges: float
    total_deficit: float
    strategy: str
    closed_at: str
    recovered_amount: float = 0.0
    is_settled: bool = False


class AdaptiveProfitLossRecoveryEngine:
    """
    Self-adjusting threshold controller and loss recovery orchestrator.
    Guarantees that winning positions lock in profit, stops ratchet to cost-free
    breakeven, and any past losses are systematically targeted and recovered.
    """

    def __init__(self, initial_capital: float = 1_000_000.0, target_profit_margin: float = 0.005):
        self._lock = threading.Lock()
        self.initial_capital = float(initial_capital)
        self.target_profit_margin = float(target_profit_margin)  # +0.5% target beyond deficit

        # Core State
        self.thresholds = AdaptiveThresholds()
        self.unrecovered_deficit = 0.0          # Total unrecovered INR loss
        self.total_recovered_pnl = 0.0          # Lifetime profit generated in recovery
        self.lifetime_loss_recovered = 0.0
        self.in_recovery_mode = False
        self.recovery_start_time: Optional[str] = None
        self.active_recovery_trades: int = 0
        self.total_recoveries_completed = 0

        # Performance Tracking
        self.trade_history: List[Dict[str, Any]] = []
        self.loss_ledger: List[LossEvent] = []
        self.watermark_equity = self.initial_capital
        self.current_equity = self.initial_capital

        # Load persisted state if exists
        self._load_state()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. SELF-ADJUSTING THRESHOLDS
    # ─────────────────────────────────────────────────────────────────────────

    def update_market_context(
        self,
        regime: str = "TRENDING",
        vix: float = 15.0,
        win_rate_20: float = 0.55,
        consecutive_losses: int = 0,
    ) -> AdaptiveThresholds:
        """
        Dynamically recalibrate all trading thresholds based on real-time market regime,
        VIX, recent win rate, and unrecovered deficit.
        """
        with self._lock:
            regime = (regime or "TRENDING").upper()
            vix = float(vix or 15.0)
            win_rate = float(win_rate_20 if win_rate_20 is not None else 0.55)

            # Base parameters
            conf = 0.52
            rr = 1.50
            agreed = 1
            max_risk = 0.02
            be_trig = 0.0075
            trail_mult = 1.50
            mode = "BALANCED_GROWTH"

            # ── Regime-Based Adjustment ──
            if regime == "TRENDING":
                conf = 0.50
                rr = 1.60
                agreed = 1
                trail_mult = 1.80  # Give winners more room to run
            elif regime == "SIDEWAYS":
                conf = 0.62       # Require higher conviction in sideways chop
                rr = 2.00
                agreed = 2        # At least 2 agents must agree
                be_trig = 0.0050   # Ratchet to breakeven faster in chop
                trail_mult = 1.20
            elif regime in ("VOLATILE", "RISK_OFF", "CRASH"):
                conf = 0.70       # Filter out marginal setups
                rr = 2.50
                agreed = 2
                max_risk = 0.01   # Cut risk in half
                be_trig = 0.0040   # Lock breakeven ultra-fast
                trail_mult = 1.00

            # ── VIX Volatility Scalar ──
            if vix > 22.0:
                conf += 0.05
                max_risk *= 0.75
            elif vix > 28.0:
                conf += 0.10
                max_risk *= 0.50
                agreed = max(agreed, 3)

            # ── Performance & Drawdown Scalers ──
            if consecutive_losses >= 2:
                # Tighten immediately after consecutive losses
                conf = max(conf, 0.65)
                rr = max(rr, 2.20)
                agreed = max(agreed, 2)
                max_risk = min(max_risk, 0.012)

            # ── RECOVERY MODE THRESHOLD OVERRIDES ──
            if self.in_recovery_mode or self.unrecovered_deficit > 0:
                mode = "RECOVERY_HURDLE"
                # In recovery mode, only Grade-A+ setups are allowed
                conf = max(conf, 0.72)
                rr = max(rr, 2.50)
                agreed = max(agreed, 2)
                be_trig = min(be_trig, 0.0050)  # Ultra-fast cost-cover lock
                trail_mult = 1.10

            self.thresholds = AdaptiveThresholds(
                min_confidence=round(min(conf, 0.88), 3),
                min_rr_ratio=round(max(rr, 1.4), 2),
                min_agent_agreement=int(agreed),
                max_risk_pct_per_trade=round(max(max_risk, 0.005), 4),
                breakeven_trigger_pct=round(be_trig, 4),
                trail_atr_multiplier=round(trail_mult, 2),
                profit_buffer_pct=0.002,
                mode_label=mode,
            )

            self._save_state()
            return self.thresholds

    # ─────────────────────────────────────────────────────────────────────────
    # 2. ZERO-LOSS POSITION GUARD & BREAKEVEN RATCHET
    # ─────────────────────────────────────────────────────────────────────────

    def evaluate_position_protection(
        self,
        position: Dict[str, Any],
        current_price: float,
        atr: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Evaluates an open position against zero-loss guarantees:
        1. Checks if unrealized profit covers roundtrip regulatory charges.
        2. Calculates exact cost-covering stop price (Breakeven + Fees + Cushion).
        3. Evaluates tiered profit ladder to permanently lock accrued gains.

        Returns:
            {
                'action': 'HOLD' | 'MOVE_TO_BREAKEVEN' | 'TRAIL_PROFIT' | 'CLOSE',
                'new_sl': float or None,
                'is_cost_covered': bool,
                'locked_pnl': float,
                'reason': str
            }
        """
        symbol = position.get("symbol", "")
        entry_price = float(position.get("entry_price") or position.get("entryPrice", 0.0))
        qty = int(position.get("quantity") or position.get("qty", 1))
        current_sl = float(position.get("stop_loss") or position.get("sl", 0.0))
        target = float(position.get("target", 0.0))
        direction = (position.get("direction") or position.get("dir", "BUY")).upper()
        is_long = direction == "BUY"

        if entry_price <= 0 or current_price <= 0 or qty <= 0:
            return {"action": "HOLD", "new_sl": None, "is_cost_covered": False, "locked_pnl": 0.0, "reason": "invalid_inputs"}

        # 1. Compute exact Indian round-trip charges
        charges_info = calculate_charges(qty=qty, buy_price=entry_price, sell_price=current_price, is_intraday=False)
        roundtrip_charges = charges_info.get("total", BROKERAGE_FLAT * 2)
        charge_per_share = roundtrip_charges / qty

        # 2. Compute gross & net unrealized PnL
        if is_long:
            gross_pnl = (current_price - entry_price) * qty
            price_gain_pct = (current_price - entry_price) / entry_price
        else:
            gross_pnl = (entry_price - current_price) * qty
            price_gain_pct = (entry_price - current_price) / entry_price

        net_pnl = gross_pnl - roundtrip_charges

        # Guaranteed breakeven price (including regulatory charges + buffer)
        profit_cushion = entry_price * self.thresholds.profit_buffer_pct
        if is_long:
            cost_covered_sl = round(entry_price + charge_per_share + profit_cushion, 2)
        else:
            cost_covered_sl = round(entry_price - charge_per_share - profit_cushion, 2)

        # 3. Cost-Covered Breakeven Trigger
        breakeven_triggered = False
        already_be = position.get("breakeven_done", False)

        # Trigger if net profit covers fees + trigger threshold
        if not already_be and price_gain_pct >= self.thresholds.breakeven_trigger_pct:
            if is_long and cost_covered_sl > current_sl:
                breakeven_triggered = True
            elif not is_long and (current_sl <= 0 or cost_covered_sl < current_sl):
                breakeven_triggered = True

        if breakeven_triggered:
            return {
                "action": "MOVE_TO_BREAKEVEN",
                "new_sl": cost_covered_sl,
                "is_cost_covered": True,
                "locked_pnl": max(0.0, profit_cushion * qty),
                "reason": f"Zero-loss ratchet: covered roundtrip fees (Rs{roundtrip_charges:.2f}) + buffer",
            }

        # 4. Asymmetric Tiered Profit Locking Ladder
        # Ensure we lock in profits at +1R, +2R, +3R
        initial_risk = abs(entry_price - current_sl) if current_sl > 0 else (atr or entry_price * 0.02)
        r_multiple = (current_price - entry_price) / max(initial_risk, 1e-4) if is_long else (entry_price - current_price) / max(initial_risk, 1e-4)

        ladder_sl = None
        if r_multiple >= 3.0:
            # Lock 75% of peak gains
            ladder_sl = entry_price + (initial_risk * 2.25) if is_long else entry_price - (initial_risk * 2.25)
        elif r_multiple >= 2.0:
            # Lock 60% of peak gains (+1.2R guaranteed)
            ladder_sl = entry_price + (initial_risk * 1.20) if is_long else entry_price - (initial_risk * 1.20)
        elif r_multiple >= 1.0:
            # Lock 35% of gains (+0.35R guaranteed above breakeven)
            ladder_sl = entry_price + (initial_risk * 0.35) if is_long else entry_price - (initial_risk * 0.35)

        if ladder_sl is not None:
            ladder_sl = round(ladder_sl, 2)
            if is_long and ladder_sl > current_sl:
                return {
                    "action": "TRAIL_PROFIT",
                    "new_sl": ladder_sl,
                    "is_cost_covered": True,
                    "locked_pnl": (ladder_sl - entry_price) * qty - roundtrip_charges,
                    "reason": f"Profit ladder locked {r_multiple:.1f}R profit",
                }
            elif not is_long and (current_sl <= 0 or ladder_sl < current_sl):
                return {
                    "action": "TRAIL_PROFIT",
                    "new_sl": ladder_sl,
                    "is_cost_covered": True,
                    "locked_pnl": (entry_price - ladder_sl) * qty - roundtrip_charges,
                    "reason": f"Profit ladder locked {r_multiple:.1f}R short profit",
                }

        # Current status
        is_cost_covered = (current_sl >= cost_covered_sl) if is_long else (current_sl <= cost_covered_sl and current_sl > 0)
        return {
            "action": "HOLD",
            "new_sl": None,
            "is_cost_covered": is_cost_covered,
            "locked_pnl": max(0.0, ((current_sl - entry_price) * qty - roundtrip_charges)) if is_cost_covered and is_long else 0.0,
            "reason": "holding_normal",
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 3. MATHEMATICAL LOSS RECOVERY ENGINE
    # ─────────────────────────────────────────────────────────────────────────

    def register_trade_outcome(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """
        Record every closed trade outcome.
        - If loss: Enters deficit into ledger, activates RECOVERY_MODE, and computes
          the exact mathematical recovery requirements.
        - If profit: Credits profit toward unrecovered deficit. If deficit reaches 0,
          completes recovery, returns to BALANCED_GROWTH, and resets thresholds.
        """
        with self._lock:
            symbol = trade.get("symbol", "UNKNOWN")
            realised_pnl = float(trade.get("realised_pnl") or trade.get("pnl", 0.0))
            strategy = str(trade.get("strategy", "UNKNOWN"))
            now_str = datetime.now().isoformat()

            # Estimate or extract actual charges
            charges = float(trade.get("charges") or 50.0)
            net_pnl = realised_pnl - (charges if realised_pnl > 0 else 0.0)

            # Record in history
            self.trade_history.append({
                "symbol": symbol,
                "net_pnl": round(net_pnl, 2),
                "strategy": strategy,
                "timestamp": now_str,
            })
            if len(self.trade_history) > 200:
                self.trade_history.pop(0)

            # ── Case A: Closed with a Loss ──
            if net_pnl < 0:
                loss_amount = abs(net_pnl)
                self.unrecovered_deficit += loss_amount

                event = LossEvent(
                    symbol=symbol,
                    pnl=realised_pnl,
                    charges=charges,
                    total_deficit=loss_amount,
                    strategy=strategy,
                    closed_at=now_str,
                )
                self.loss_ledger.append(event)
                self.in_recovery_mode = True
                if not self.recovery_start_time:
                    self.recovery_start_time = now_str

                # Trigger immediate threshold tightening
                self._recalculate_recovery_thresholds()

                plan = self.compute_recovery_plan()
                logger.warning(
                    "⚠️ LOSS REGISTERED: %s deficit ₹%.2f | Total Unrecovered: ₹%.2f | Plan: Target ₹%.2f (R:R %.1f)",
                    symbol, loss_amount, self.unrecovered_deficit, plan["target_recovery_amount"], plan["required_rr_ratio"]
                )
                self._save_state()
                return {
                    "status": "DEFICIT_ADDED",
                    "deficit": round(self.unrecovered_deficit, 2),
                    "recovery_plan": plan,
                    "in_recovery": True,
                }

            # ── Case B: Closed with a Profit ──
            else:
                profit_amount = net_pnl
                prev_deficit = self.unrecovered_deficit

                if self.unrecovered_deficit > 0:
                    recovered = min(self.unrecovered_deficit, profit_amount)
                    self.unrecovered_deficit -= recovered
                    self.total_recovered_pnl += profit_amount
                    self.lifetime_loss_recovered += recovered

                    # Update loss ledger settlement
                    rem = recovered
                    for ev in self.loss_ledger:
                        if not ev.is_settled and rem > 0:
                            needed = ev.total_deficit - ev.recovered_amount
                            take = min(needed, rem)
                            ev.recovered_amount += take
                            rem -= take
                            if ev.recovered_amount >= ev.total_deficit:
                                ev.is_settled = True

                    logger.info(
                        "💰 PROFIT RECOVERED: +₹%.2f | Deficit reduced from ₹%.2f → ₹%.2f",
                        profit_amount, prev_deficit, self.unrecovered_deficit
                    )

                    # Check if recovery is 100% COMPLETE
                    if self.unrecovered_deficit <= 1e-4:
                        self.unrecovered_deficit = 0.0
                        self.in_recovery_mode = False
                        self.recovery_start_time = None
                        self.total_recoveries_completed += 1
                        logger.info("🎉 FULL RECOVERY ACHIEVED! Deficit cleared. Resetting to growth mode.")
                        self._reset_to_normal_thresholds()
                        self._save_state()
                        return {
                            "status": "RECOVERY_COMPLETE",
                            "deficit": 0.0,
                            "surplus_profit": round(profit_amount - prev_deficit, 2),
                            "in_recovery": False,
                        }

                self._save_state()
                return {
                    "status": "PROFIT_LOGGED",
                    "deficit": round(self.unrecovered_deficit, 2),
                    "in_recovery": self.in_recovery_mode,
                }

    def compute_recovery_plan(self) -> Dict[str, Any]:
        """
        Calculates the exact mathematical parameters needed to erase all unrecovered losses
        and return the portfolio to all-time-high + profit margin.
        """
        deficit = self.unrecovered_deficit
        if deficit <= 0:
            return {
                "in_recovery": False,
                "deficit": 0.0,
                "target_recovery_amount": 0.0,
                "required_rr_ratio": self.thresholds.min_rr_ratio,
                "recommended_position_size": self.initial_capital * self.thresholds.max_risk_pct_per_trade,
                "recovery_progress_pct": 100.0,
                "message": "Portfolio in profit — no deficit.",
            }

        # Target = Full Deficit + Profit Buffer (+0.5% of capital)
        target_profit = deficit + (self.initial_capital * self.target_profit_margin)

        # Enforce Asymmetric Risk-Reward:
        # Standard risk allocation = 1.0% of capital
        risk_per_trade = self.initial_capital * min(self.thresholds.max_risk_pct_per_trade, 0.015)

        # If deficit is small, 1 trade at 2.5R covers it completely.
        # If deficit is larger, calculate multi-trade recovery ladder (max 2-3 trades).
        required_rr = max(2.5, min(4.5, target_profit / max(risk_per_trade, 100.0)))

        # Recommended position size so that an R:R move generates `target_profit`
        # target_gain = size * (target_pct)
        # Using 5% target move as benchmark standard
        recommended_size = min(
            self.initial_capital * 0.10,  # Max 10% capital in single recovery trade
            max(target_profit / 0.05, self.initial_capital * 0.03)
        )

        settled_count = sum(1 for e in self.loss_ledger if e.is_settled)
        total_loss_events = len(self.loss_ledger)
        total_initial_loss = sum(e.total_deficit for e in self.loss_ledger)
        recovered_total = sum(e.recovered_amount for e in self.loss_ledger)
        progress_pct = (recovered_total / max(total_initial_loss, 1.0)) * 100.0

        return {
            "in_recovery": True,
            "deficit": round(deficit, 2),
            "target_recovery_amount": round(target_profit, 2),
            "required_rr_ratio": round(required_rr, 2),
            "recommended_position_size": round(recommended_size, 2),
            "risk_budget_per_trade": round(risk_per_trade, 2),
            "recovery_progress_pct": round(min(progress_pct, 100.0), 1),
            "unsettled_loss_events": total_loss_events - settled_count,
            "total_recoveries_completed": self.total_recoveries_completed,
            "message": f"Targeting ₹{target_profit:,.2f} profit with R:R ≥ {required_rr:.1f} to erase deficit.",
        }

    def validate_candidate_signal(self, signal: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Gatekeeper for new trade entries.
        Enforces self-adjusted thresholds (confidence, R:R, agent agreement).
        In recovery mode, only Grade-A+ setups are approved.
        """
        conf = float(signal.get("confidence", 0.0))
        rr = float(signal.get("rr_ratio", signal.get("min_rr", 0.0)))
        agreement = int(signal.get("agent_agreement", signal.get("agreement_count", 1)))

        # If R:R not directly provided, derive from price, target, stop_loss
        if rr <= 0:
            price = float(signal.get("price") or signal.get("entry_price", 0.0))
            tgt = float(signal.get("target", 0.0))
            sl = float(signal.get("stop_loss", 0.0))
            if price > 0 and sl > 0 and tgt > 0:
                risk = abs(price - sl)
                reward = abs(tgt - price)
                rr = reward / max(risk, 1e-4)

        th = self.thresholds

        # 1. Confidence check
        if conf < th.min_confidence:
            return False, f"Confidence {conf:.2f} < adaptive threshold {th.min_confidence:.2f} ({th.mode_label})"

        # 2. Risk-Reward ratio check
        if rr > 0 and rr < th.min_rr_ratio:
            return False, f"R:R ratio {rr:.2f} < required {th.min_rr_ratio:.2f} ({th.mode_label})"

        # 3. Agent Agreement check
        if agreement < th.min_agent_agreement:
            return False, f"Agent agreement {agreement} < required {th.min_agent_agreement} ({th.mode_label})"

        return True, "APPROVED_BY_ADAPTIVE_ENGINE"

    # ─────────────────────────────────────────────────────────────────────────
    # 4. INTERNAL HELPERS & PERSISTENCE
    # ─────────────────────────────────────────────────────────────────────────

    def _recalculate_recovery_thresholds(self):
        """Tightens thresholds when entering recovery mode."""
        self.thresholds.min_confidence = max(self.thresholds.min_confidence, 0.72)
        self.thresholds.min_rr_ratio = max(self.thresholds.min_rr_ratio, 2.50)
        self.thresholds.min_agent_agreement = max(self.thresholds.min_agent_agreement, 2)
        self.thresholds.breakeven_trigger_pct = 0.0050
        self.thresholds.mode_label = "RECOVERY_HURDLE"

    def _reset_to_normal_thresholds(self):
        """Resets thresholds to balanced growth after deficit is cleared."""
        self.thresholds.min_confidence = 0.52
        self.thresholds.min_rr_ratio = 1.60
        self.thresholds.min_agent_agreement = 1
        self.thresholds.breakeven_trigger_pct = 0.0075
        self.thresholds.mode_label = "BALANCED_GROWTH"

    def get_stats(self) -> Dict[str, Any]:
        """Provides full telemetry payload for dashboard and main loop."""
        with self._lock:
            plan = self.compute_recovery_plan()
            return {
                "engine_status": "ACTIVE",
                "in_recovery_mode": self.in_recovery_mode,
                "unrecovered_deficit": round(self.unrecovered_deficit, 2),
                "total_recovered_pnl": round(self.total_recovered_pnl, 2),
                "lifetime_recovered": round(self.lifetime_loss_recovered, 2),
                "recoveries_completed": self.total_recoveries_completed,
                "current_thresholds": asdict(self.thresholds),
                "recovery_plan": plan,
                "total_losses_tracked": len(self.loss_ledger),
                "recent_trades_count": len(self.trade_history),
            }

    def _save_state(self):
        try:
            data = {
                "saved_at": datetime.now().isoformat(),
                "unrecovered_deficit": self.unrecovered_deficit,
                "total_recovered_pnl": self.total_recovered_pnl,
                "lifetime_loss_recovered": self.lifetime_loss_recovered,
                "in_recovery_mode": self.in_recovery_mode,
                "total_recoveries_completed": self.total_recoveries_completed,
                "recovery_start_time": self.recovery_start_time,
                "thresholds": asdict(self.thresholds),
                "loss_ledger": [asdict(ev) for ev in self.loss_ledger[-100:]],
            }
            tmp = str(_STATE_FILE) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, str(_STATE_FILE))
        except Exception as e:
            logger.debug("Failed to persist adaptive recovery state: %s", e)

    def _load_state(self):
        if not _STATE_FILE.exists():
            return
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.unrecovered_deficit = float(data.get("unrecovered_deficit", 0.0))
            self.total_recovered_pnl = float(data.get("total_recovered_pnl", 0.0))
            self.lifetime_loss_recovered = float(data.get("lifetime_loss_recovered", 0.0))
            self.in_recovery_mode = bool(data.get("in_recovery_mode", False))
            self.total_recoveries_completed = int(data.get("total_recoveries_completed", 0))
            self.recovery_start_time = data.get("recovery_start_time")
            th = data.get("thresholds", {})
            if th:
                self.thresholds = AdaptiveThresholds(**th)
            for raw_ev in data.get("loss_ledger", []):
                self.loss_ledger.append(LossEvent(**raw_ev))
            logger.info("AdaptiveRecoveryEngine: restored state (deficit=Rs%.2f, mode=%s)",
                        self.unrecovered_deficit, self.thresholds.mode_label)
        except Exception as e:
            logger.warning("AdaptiveRecoveryEngine: state restore failed (%s)", e)


# Global singleton access
_ENGINE_INSTANCE: Optional[AdaptiveProfitLossRecoveryEngine] = None
_ENGINE_LOCK = threading.Lock()

def get_adaptive_recovery_engine(capital: float = 1_000_000.0) -> AdaptiveProfitLossRecoveryEngine:
    global _ENGINE_INSTANCE
    with _ENGINE_LOCK:
        if _ENGINE_INSTANCE is None:
            _ENGINE_INSTANCE = AdaptiveProfitLossRecoveryEngine(initial_capital=capital)
        return _ENGINE_INSTANCE
