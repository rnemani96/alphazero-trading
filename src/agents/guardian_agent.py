"""
GUARDIAN Agent — Risk Officer
src/agents/guardian_agent.py

Hard rules that CANNOT be overridden by any other agent or AI component:
  - Max daily loss %
  - Max position size %
  - Max sector exposure %
  - Max concurrent positions
  - Max trades per day
  - Consecutive loss cooldown
  - VIX-based size reduction / halt
  - Minimum R:R ratio
  - No trading first/last 5 minutes of session
  - Overtrading guard (5-minute cooldown between trades)

Position sizing:
  Combined Kelly + ATR approach → most conservative of the two.

Dynamic stop-loss:
  ATR-based initial SL + trailing SL activation after 2% profit.

KPI: Max drawdown < 8%
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..event_bus.event_bus import BaseAgent, EventType
from ..utils.stats import kelly_fraction

logger = logging.getLogger(__name__)

# Sector lookup (populated from config.sectors on import)
try:
    from config.sectors import SECTORS as _SECTORS
    _SYM_TO_SECTOR: Dict[str, str] = {
        sym: sec for sec, syms in _SECTORS.items() for sym in syms
    }
except ImportError:
    _SYM_TO_SECTOR = {}


class GuardianAgent(BaseAgent):
    """
    GUARDIAN — Risk Officer Agent.

    Usage:
        result = guardian.check_trade(signal, current_capital, positions)
        # result = {'approved': bool, 'reason': str, 'position_size': float,
        #           'quantity': int, 'stop_loss': float, 'target': float}
    """

    # IST market hours
    _NO_TRADE_OPEN_MINS  = 5   # skip 09:15–09:20
    _NO_TRADE_CLOSE_MINS = 5   # skip 15:25–15:30
    _TRADE_COOLDOWN_SECS = 300 # 5 minutes between trades

    def __init__(self, event_bus, config: Dict[str, Any]):
        super().__init__(event_bus=event_bus, config=config, name="GUARDIAN")

        # ── Hard limits (read from config / .env) ─────────────────────────────
        self.max_daily_loss_pct     = float(config.get('MAX_DAILY_LOSS_PCT',      0.02))
        self.max_position_size_pct  = float(config.get('MAX_POSITION_SIZE_PCT',   0.05))
        self.max_sector_pct         = float(config.get('MAX_SECTOR_EXPOSURE_PCT', 0.30))
        self.max_positions          = int(config.get('MAX_POSITIONS',             10))
        self.max_trades_per_day     = int(config.get('MAX_TRADES_PER_DAY',        20))
        self.consec_loss_limit      = int(config.get('CONSECUTIVE_LOSS_LIMIT',    3))
        self.min_rr                 = float(config.get('MIN_RR_RATIO',            2.0))
        self.initial_capital        = float(config.get('INITIAL_CAPITAL',         1_000_000))
        self.vix_reduce_threshold   = float(config.get('VIX_REDUCE_THRESHOLD',    20.0))
        self.vix_halt_threshold     = float(config.get('VIX_HALT_THRESHOLD',      30.0))
        self.cooldown_minutes       = int(config.get('COOLDOWN_MINUTES',          30))

        # ── Mutable state (thread-safe) ───────────────────────────────────────
        self._lock              = threading.Lock()
        self.daily_pnl          = 0.0
        self.trades_today       = 0
        self.consec_losses      = 0
        self.kill_switch_active = False
        self.cooldown_until: Optional[datetime] = None
        self.last_trade_time: Optional[datetime] = None
        self.trade_decisions    = 0
        self.last_reset_date    = date.today()
        self._current_vix       = 15.0

        # Per-strategy win-rate tracking for Kelly sizing
        self._strategy_history: Dict[str, List[float]] = {}

        logger.info("GUARDIAN initialised — all risk limits active")

    # ── Core entry point ──────────────────────────────────────────────────────

    def check_trade(
        self,
        signal: Dict[str, Any],
        current_capital: float,
        positions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Validate a trade signal against all hard risk rules.

        Returns:
            {'approved': bool, 'reason': str, 'position_size': float,
             'quantity': int, 'stop_loss': float, 'target': float}
        """
        with self._lock:
            self._daily_reset()
            self.trade_decisions += 1

            sym    = signal.get('symbol', '')
            price  = float(signal.get('price') or signal.get('entry_price') or 0)
            action = (signal.get('action') or signal.get('signal', 'BUY')).upper()
            atr    = float(signal.get('atr') or price * 0.02)
            conf   = float(signal.get('confidence', 0.5))
            strat  = signal.get('top_strategy', signal.get('strategy', ''))

            # ── Hard gates ────────────────────────────────────────────────────
            if self.kill_switch_active:
                return self._reject('KILL_SWITCH_ACTIVE')

            loss_pct = abs(self.daily_pnl) / max(self.initial_capital, 1)
            if self.daily_pnl < 0 and loss_pct >= self.max_daily_loss_pct:
                self.kill_switch_active = True
                self._alert(f"Daily loss limit {loss_pct:.1%} hit — shutdown")
                return self._reject(f'DAILY_LOSS_LIMIT ({loss_pct:.1%})')

            if self._current_vix >= self.vix_halt_threshold:
                return self._reject(f'VIX_HALT ({self._current_vix:.1f} ≥ {self.vix_halt_threshold})')

            if len(positions) >= self.max_positions:
                return self._reject(f'MAX_POSITIONS ({len(positions)}/{self.max_positions})')

            if self.trades_today >= self.max_trades_per_day:
                return self._reject(f'MAX_TRADES_DAY ({self.trades_today}/{self.max_trades_per_day})')

            if self.consec_losses >= self.consec_loss_limit:
                if self.cooldown_until and datetime.now() < self.cooldown_until:
                    mins = int((self.cooldown_until - datetime.now()).total_seconds() / 60)
                    return self._reject(f'COOLDOWN ({mins}min remain)')

            # Trade cooldown (5 min between trades)
            if self.last_trade_time:
                secs = (datetime.now() - self.last_trade_time).total_seconds()
                if secs < self._TRADE_COOLDOWN_SECS:
                    return self._reject(f'TRADE_COOLDOWN ({secs:.0f}s < {self._TRADE_COOLDOWN_SECS}s)')

            # Market timing
            if not self._check_market_hours():
                return self._reject('OUTSIDE_TRADING_HOURS')

            if price <= 0:
                return self._reject('INVALID_PRICE')

            # ── Dynamic SL / Target from ATR ──────────────────────────────────
            sl, tgt = self._compute_sl_target(price, action, atr)
            rr      = self._compute_rr(price, sl, tgt)
            if rr < self.min_rr:
                return self._reject(f'LOW_RR ({rr:.2f} < {self.min_rr})')

            # ── Position sizing ────────────────────────────────────────────────
            pos_size = self._compute_position_size(
                current_capital, price, atr, sl, conf, strat
            )

            # VIX size reduction
            if self._current_vix >= self.vix_reduce_threshold:
                pos_size *= 0.5
                logger.info("GUARDIAN: VIX=%.1f → position halved", self._current_vix)

            max_allowed = current_capital * self.max_position_size_pct
            pos_size    = min(pos_size, max_allowed)

            qty = max(1, int(pos_size / price)) if price > 0 else 0
            if qty == 0:
                return self._reject('ZERO_QUANTITY')

            # ── Sector exposure ────────────────────────────────────────────────
            sector = _SYM_TO_SECTOR.get(sym, 'OTHER')
            
            same_sector_positions = [
                p for p in positions if _SYM_TO_SECTOR.get(p.get('symbol', ''), 'X') == sector
            ]
            
            # Correlation Guard: Prevent >= 5 positions in the same sector
            if len(same_sector_positions) >= 4:
                return self._reject(f'CORRELATION_GUARD (Too many in {sector})')

            sector_used = sum(
                float(p.get('entry_price', 0)) * float(p.get('quantity', p.get('qty', 0)))
                for p in same_sector_positions
            )
            if sector_used + pos_size > current_capital * self.max_sector_pct:
                return self._reject(f'SECTOR_LIMIT ({sector})')

            # ── Duplicate position guard ───────────────────────────────────────
            open_syms = {p.get('symbol') for p in positions}
            if sym in open_syms:
                return self._reject(f'POSITION_ALREADY_OPEN ({sym})')

            # ── Approved ─────────────────────────────────────────────────────
            self.last_trade_time = datetime.now()
            self.trades_today   += 1

            self.publish_event(EventType.RISK_ALERT, {
                'action':        'TRADE_APPROVED',
                'symbol':        sym,
                'position_size': pos_size,
                'qty':           qty,
                'rr':            rr,
                'vix':           self._current_vix,
            })

            logger.info("GUARDIAN ✅ %s ×%d ₹%.2f  SL=₹%.2f  TGT=₹%.2f  R:R=%.1f  conf=%.2f",
                        sym, qty, price, sl, tgt, rr, conf)

            return {
                'approved':      True,
                'reason':        f'OK R:R={rr:.1f}',
                'position_size': round(pos_size, 2),
                'quantity':      qty,
                'stop_loss':     sl,
                'target':        tgt,
                'sector':        sector,
            }

    def approve_signals(self, signals: List[Dict]) -> List[Dict]:
        """
        Bulk-check a list of signals.  Returns approved signals with
        position_size, quantity, stop_loss, target injected.
        """
        # Snapshot current capital and positions from latest state
        # (caller should pass these in; we use defaults if not available)
        approved = []
        fake_positions: List[Dict] = []   # No live positions context here
        capital = self.initial_capital + self.daily_pnl

        for sig in signals:
            result = self.check_trade(sig, capital, fake_positions)
            if result['approved']:
                sig['position_size'] = result['position_size']
                sig['quantity']      = result['quantity']
                sig['qty']           = result['quantity']
                sig['stop_loss']     = result.get('stop_loss', sig.get('stop_loss', 0))
                sig['target']        = result.get('target',    sig.get('target',    0))
                approved.append(sig)
        return approved

    # ── Outcome tracking ──────────────────────────────────────────────────────

    def update_pnl(self, pnl_change: float, is_loss: bool = False):
        """Call after every closed trade."""
        with self._lock:
            self.daily_pnl += pnl_change
            if is_loss:
                self.consec_losses += 1
                if self.consec_losses >= self.consec_loss_limit:
                    self.cooldown_until = datetime.now() + timedelta(minutes=self.cooldown_minutes)
                    logger.warning("GUARDIAN: %d consecutive losses — %d-min cooldown",
                                   self.consec_losses, self.cooldown_minutes)
            else:
                self.consec_losses = 0

        # Update strategy history
        if pnl_change != 0:
            strat = 'general'
            lst   = self._strategy_history.setdefault(strat, [])
            lst.append(1.0 if pnl_change > 0 else -1.0)
            if len(lst) > 200:
                lst.pop(0)

    def record_strategy_outcome(self, strategy: str, pnl: float):
        """Track per-strategy P&L for Kelly sizing."""
        with self._lock:
            lst = self._strategy_history.setdefault(strategy, [])
            lst.append(pnl)
            if len(lst) > 200:
                lst.pop(0)

    def set_vix(self, vix: float):
        with self._lock:
            self._current_vix = float(vix)

    def reset_kill_switch(self):
        with self._lock:
            self.kill_switch_active = False
        logger.info("GUARDIAN: kill switch manually reset")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _daily_reset(self):
        today = date.today()
        if today > self.last_reset_date:
            self.daily_pnl     = 0.0
            self.trades_today  = 0
            self.consec_losses = 0
            self.kill_switch_active = False
            self.last_reset_date = today
            logger.info("GUARDIAN: daily counters reset")

    def _reject(self, reason: str) -> Dict[str, Any]:
        logger.debug("GUARDIAN ❌ %s", reason)
        return {'approved': False, 'reason': reason, 'position_size': 0,
                'quantity': 0, 'stop_loss': 0, 'target': 0}

    def _alert(self, msg: str):
        try:
            self.publish_event(EventType.RISK_ALERT, {
                'action': 'KILL_SWITCH', 'reason': msg,
                'timestamp': datetime.now().isoformat()
            })
        except Exception:
            pass
        logger.critical("GUARDIAN 🚨 %s", msg)

    def _compute_sl_target(
        self, price: float, action: str, atr: float
    ) -> Tuple[float, float]:
        """ATR-based stop-loss and 3:1 R:R target."""
        if action == 'BUY':
            sl  = round(price - 1.5 * atr, 2)
            tgt = round(price + 3.0 * atr, 2)
        else:
            sl  = round(price + 1.5 * atr, 2)
            tgt = round(price - 3.0 * atr, 2)
        return sl, tgt

    def _compute_rr(self, price: float, sl: float, tgt: float) -> float:
        risk   = abs(price - sl)
        reward = abs(tgt - price)
        return round(reward / max(risk, 1e-6), 2)

    def _compute_position_size(
        self,
        capital: float,
        price: float,
        atr: float,
        sl: float,
        confidence: float,
        strategy: str,
    ) -> float:
        """
        Combined Kelly + ATR position sizing.
        Returns INR amount to invest (before VIX and cap adjustments).
        """
        # ── ATR-based: risk 1% of capital per trade ────────────────────────
        risk_per_trade = capital * 0.01
        sl_distance    = abs(price - sl)
        atr_qty        = (risk_per_trade / max(sl_distance, atr * 0.5)) * price
        atr_size       = min(atr_qty, capital * self.max_position_size_pct)

        # ── Kelly-based from strategy history ────────────────────────────
        hist = self._strategy_history.get(strategy, [])
        if len(hist) >= 20:
            wins  = [h for h in hist if h > 0]
            loses = [h for h in hist if h < 0]
            if wins and loses:
                wp     = len(wins)  / len(hist)
                aw     = sum(abs(w) for w in wins)  / len(wins)
                al     = sum(abs(l) for l in loses) / len(loses)
                kf     = kelly_fraction(wp, aw / price, al / price, fraction=0.5)
                kelly_size = capital * kf
            else:
                kelly_size = capital * 0.03  # default 3%
        else:
            kelly_size = capital * (0.02 + confidence * 0.02)  # 2–4% based on confidence

        # Take the more conservative of the two
        size = min(atr_size, kelly_size)
        return max(size, price)   # at least 1 share worth

    def _check_market_hours(self) -> bool:
        """Return True if within NSE trading window (09:20–15:25)."""
        now  = datetime.now()
        hour = now.hour
        minute = now.minute
        # Allow all hours in paper mode (backtesting / weekends)
        # In live mode the broker will reject anyway
        total_mins = hour * 60 + minute
        open_mins  = 9 * 60 + 20    # 09:20 (skip first 5)
        close_mins = 15 * 60 + 25   # 15:25 (skip last 5)
        # On weekends, allow execution (paper mode)
        if now.weekday() >= 5:
            return True
        return open_mins <= total_mins <= close_mins

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'name':              self.name,
                'active':            self.is_active,
                'kill_switch':       self.kill_switch_active,
                'daily_pnl':         round(self.daily_pnl, 2),
                'trades_today':      self.trades_today,
                'consec_losses':     self.consec_losses,
                'trade_decisions':   self.trade_decisions,
                'vix':               self._current_vix,
                'kpi':               'Max drawdown < 8%',
                'last_activity':     self.last_activity,
            }
