"""
GUARDIAN — Risk Officer Agent
Hard rules. Cannot be overridden by any other agent.
All limits enforced here before any order reaches MERCURY.
"""
import os
from dataclasses import dataclass, field
from datetime import datetime, date
import logging

logger = logging.getLogger("GUARDIAN")


@dataclass
class RiskConfig:
    max_daily_loss_pct:     float = 0.02   # 2% of portfolio → full shutdown
    max_position_pct:       float = 0.05   # max 5% per position
    max_sector_pct:         float = 0.30   # max 30% per sector
    max_positions:          int   = 10
    max_trades_per_day:     int   = 20
    consecutive_loss_limit: int   = 3      # 3 losses → 30-min cooldown
    cooldown_minutes:       int   = 30
    min_rr_ratio:           float = 2.0    # min risk:reward
    vix_reduce_threshold:   float = 20.0   # reduce size by 50%
    vix_halt_threshold:     float = 30.0   # no new entries
    min_trade_gap_minutes:  int   = 5
    no_trade_open_mins:     int   = 5      # no trade 9:15–9:20
    no_trade_close_mins:    int   = 5      # no trade 15:25–15:30


@dataclass
class PortfolioState:
    capital:            float = 100000.0
    cash:               float = 100000.0
    open_positions:     dict  = field(default_factory=dict)
    daily_pnl:          float = 0.0
    daily_trades:       int   = 0
    consecutive_losses: int   = 0
    last_trade_time:    datetime = None
    cooldown_until:     datetime = None
    shutdown:           bool  = False
    trade_date:         date  = None


class GuardianRiskEngine:
    """
    GUARDIAN enforces all hard risk rules.
    Returns (approved: bool, reason: str, adjusted_qty: int)
    """

    def __init__(self, config: RiskConfig = None):
        self.cfg   = config or RiskConfig()
        self.state = PortfolioState()
        self.state.trade_date = date.today()

    def reset_daily(self):
        """Call at market open each day."""
        if self.state.trade_date != date.today():
            self.state.daily_pnl    = 0.0
            self.state.daily_trades = 0
            self.state.trade_date   = date.today()
            self.state.consecutive_losses = 0
            self.state.shutdown     = False
            logger.info("GUARDIAN: Daily counters reset for %s", date.today())

    def update_capital(self, new_capital: float):
        """Update the base capital for risk calculations."""
        if new_capital > 0:
            # Smooth update to prevent sizing shocks
            if self.state.capital == 100000.0: # initial default
                self.state.capital = new_capital
                self.state.cash = new_capital
            else:
                self.state.capital = new_capital
            logger.info(f"GUARDIAN: Capital updated to ₹{new_capital:,.2f}")

    def validate_trade(self, proposal: dict, vix: float, regime: str) -> tuple[bool, str, int]:
        """
        Validate a trade proposal against all hard rules.
        """
        self.reset_daily()
        sym   = proposal["symbol"]
        entry = proposal["entry_price"]
        sl    = proposal["stop_loss"]
        tgt   = proposal["target"]
        qty   = proposal["qty"]
        sector= proposal.get("sector", "Unknown")

        # ── Hard Rule 1: Kill switch ──────────────────────────────────────────
        if self.state.shutdown:
            return False, "KILL SWITCH ACTIVE — no new trades", 0

        # ── Hard Rule 2: Daily loss limit ─────────────────────────────────────
        if self.state.daily_pnl <= -(self.cfg.max_daily_loss_pct * self.state.capital):
            self.state.shutdown = True
            return False, f"Daily loss limit hit: ₹{self.state.daily_pnl:.0f}", 0

        # ── Hard Rule 3: VIX check ────────────────────────────────────────────
        if vix >= self.cfg.vix_halt_threshold:
            return False, f"VIX={vix} >= {self.cfg.vix_halt_threshold} — RISK_OFF, no entries", 0

        # ── Hard Rule 4: Regime filter ────────────────────────────────────────
        if regime == "RISK_OFF":
            return False, "RISK_OFF regime — entries paused by GUARDIAN", 0

        # ── Hard Rule 5: Daily trade limit ────────────────────────────────────
        if self.state.daily_trades >= self.cfg.max_trades_per_day:
            return False, f"Max daily trades ({self.cfg.max_trades_per_day}) reached", 0

        # ── Hard Rule 6: Max concurrent positions ─────────────────────────────
        if len(self.state.open_positions) >= self.cfg.max_positions:
            return False, f"Max positions ({self.cfg.max_positions}) open", 0
            
        # ── Hard Rule 6b: Avoid duplicate positions ───────────────────────────
        if sym in self.state.open_positions:
            return False, f"Position already open for {sym}", 0

        # ── Hard Rule 7: Cooldown check ───────────────────────────────────────
        if self.state.cooldown_until and datetime.now() < self.state.cooldown_until:
            mins = (self.state.cooldown_until - datetime.now()).seconds // 60
            return False, f"Cooldown active — {mins}min remaining after consecutive losses", 0

        # ── Hard Rule 9: Risk:Reward validation ───────────────────────────────
        if entry > sl:  # long
            risk   = entry - sl
            reward = tgt - entry
        else:           # short
            risk   = sl - entry
            reward = entry - tgt

        if risk <= 0:
            return False, "Invalid stop loss (risk=0)", 0
        rr = reward / risk
        if rr < self.cfg.min_rr_ratio:
            return False, f"R:R={rr:.1f} below minimum {self.cfg.min_rr_ratio}", 0

        # ── Hard Rule 10: Position size cap ──────────────────────────────────
        max_pos_value = self.state.capital * self.cfg.max_position_pct
        if vix >= self.cfg.vix_reduce_threshold:
            max_pos_value *= 0.50
            logger.info("GUARDIAN: VIX=%s — position size reduced 50%%", vix)

        # Kelly + ATR sizing
        adjusted_qty = self._size_position(entry, sl, max_pos_value, qty)

        # ── Hard Rule 11: Sector exposure ─────────────────────────────────────
        sector_val = sum(
            pos["qty"] * pos["entry"] for pos in self.state.open_positions.values()
            if pos.get("sector") == sector
        )
        new_val = adjusted_qty * entry
        if (sector_val + new_val) > self.state.capital * self.cfg.max_sector_pct:
            return False, f"Sector {sector} exposure would exceed {self.cfg.max_sector_pct*100:.0f}%", 0

        return True, f"APPROVED | R:R={rr:.1f} | qty={adjusted_qty} | risk=₹{risk*adjusted_qty:.0f}", adjusted_qty

    def _size_position(self, entry: float, sl: float, max_value: float, requested_qty: int) -> int:
        """ATR-based position sizing capped at max_value."""
        risk_per_share = abs(entry - sl)
        if risk_per_share == 0:
            return min(requested_qty, max(1, int(max_value / entry)))
        # Risk 1% of equity per trade
        risk_budget = self.state.capital * 0.01
        atr_qty = max(1, int(risk_budget / risk_per_share))
        cap_qty = max(1, int(max_value / entry))
        return min(atr_qty, cap_qty, requested_qty)

    def sync_with_broker(self, broker_positions: list):
        """Reconciliate internal state with reality (from Mercury)."""
        logger.info(f"GUARDIAN: Syncing with {len(broker_positions)} broker positions")
        
        # 1. Update internal position map
        # We keep the one that's "truer" - usually the broker
        new_positions = {}
        for bp in broker_positions:
            sym = bp['symbol']
            # If we already track it, keep our metadata (sl, tgt, sector) but update qty/entry
            if sym in self.state.open_positions:
                pos = self.state.open_positions[sym]
                pos['qty'] = bp['qty']
                pos['entry'] = bp['entry']
                new_positions[sym] = pos
            else:
                # Discovered a position (manual trade?)
                new_positions[sym] = {
                    "qty": bp['qty'],
                    "entry": bp['entry'],
                    "sl": bp['entry'] * 0.95, # default SL
                    "target": bp['entry'] * 1.10, # default TGT
                    "sector": "Unknown",
                    "time": datetime.now()
                }
        
        self.state.open_positions = new_positions

    def record_trade(self, symbol: str, qty: int, entry: float, sl: float, tgt: float, sector: str):
        """Record a trade once MERCURY confirms execution."""
        self.state.open_positions[symbol] = {
            "qty": qty, "entry": entry, "sl": sl, "target": tgt,
            "sector": sector, "time": datetime.now()
        }
        self.state.daily_trades += 1
        self.state.last_trade_time = datetime.now()
        self.state.cash -= qty * entry
        logger.info("GUARDIAN: Position recorded %s ×%d @₹%.2f", symbol, qty, entry)

    def record_exit(self, symbol: str, exit_price: float):
        """Record position exit and update P&L."""
        if symbol not in self.state.open_positions:
            logger.warning("GUARDIAN: Exit for unknown position %s", symbol)
            return
        pos = self.state.open_positions.pop(symbol)
        pnl = (exit_price - pos["entry"]) * pos["qty"]
        self.state.daily_pnl += pnl
        self.state.cash      += exit_price * pos["qty"]
        if pnl < 0:
            self.state.consecutive_losses += 1
            if self.state.consecutive_losses >= self.cfg.consecutive_loss_limit:
                from datetime import timedelta
                self.state.cooldown_until = datetime.now() + timedelta(minutes=self.cfg.cooldown_minutes)
                logger.warning("GUARDIAN: %d consecutive losses — %dmin cooldown", self.state.consecutive_losses, self.cfg.cooldown_minutes)
        else:
            self.state.consecutive_losses = 0
        logger.info("GUARDIAN: Closed %s PnL=₹%.0f  Daily=₹%.0f", symbol, pnl, self.state.daily_pnl)

    def kill_switch(self, reason: str = "Manual trigger"):
        """Immediate full shutdown — exits all positions via Event Bus."""
        self.state.shutdown = True
        logger.critical("GUARDIAN: KILL SWITCH ACTIVATED — %s", reason)

    def reset_kill_switch(self):
        self.state.shutdown = False
        logger.info("GUARDIAN: Kill switch reset")

    def update_prices(self, quotes: dict):
        """Update current prices for open positions (called by backend poll loop)."""
        for sym, pos in self.state.open_positions.items():
            q = quotes.get(sym, {})
            if q   :
                pos["current_price"] = float(q.get("ltp", pos["entry"]))

    def set_vix(self, vix: float):
        """Update current VIX level (used for position sizing rules)."""
        self._current_vix = vix

    def portfolio_summary(self) -> dict:
        open_val = sum(p["qty"] * p["entry"] for p in self.state.open_positions.values())
        return {
            "capital":    self.state.capital,
            "cash":       self.state.cash,
            "open_value": open_val,
            "daily_pnl":  self.state.daily_pnl,
            "positions":  len(self.state.open_positions),
            "daily_trades": self.state.daily_trades,
            "consecutive_losses": self.state.consecutive_losses,
            "shutdown":   self.state.shutdown,
        }
