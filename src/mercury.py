"""
MERCURY — Execution Quality Agent + Paper Executor
The ONLY agent that touches OpenAlgo order APIs.
In PAPER mode: simulates orders, tracks fills, monitors slippage.
In LIVE mode: routes to OpenAlgo with all safety checks.
"""
import os
import time
import logging
import requests
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("MERCURY")

MODE = os.getenv("MODE", "PAPER").upper()
OPENALGO_HOST = os.getenv("OPENALGO_HOST", "http://localhost:5000")
OPENALGO_KEY  = os.getenv("OPENALGO_KEY", "")


@dataclass
class OrderResult:
    order_id:     str
    symbol:       str
    direction:    str   # BUY / SELL
    qty:          int
    entry_price:  float
    filled_price: float
    slippage_pct: float
    status:       str   # FILLED / REJECTED / PENDING
    mode:         str   # PAPER / LIVE
    timestamp:    str   = field(default_factory=lambda: datetime.now().isoformat())
    reason:       str   = ""


class PaperExecutor:
    """Simulates order execution with realistic slippage modelling."""

    def __init__(self):
        self.fills: list[OrderResult] = []
        self.slippage_bps = 8   # 0.08% average slippage
        self.fill_rate    = 1.0 # 100% fill rate in paper

    def place_order(self, symbol: str, direction: str, qty: int,
                    entry_price: float, order_type: str = "MARKET") -> OrderResult:
        """Simulate a paper order fill."""
        # Simulate slippage: random 0–16 bps
        import random
        slip_bps = random.randint(0, self.slippage_bps * 2)
        slip_sign = 1 if direction == "BUY" else -1
        filled = entry_price * (1 + slip_sign * slip_bps / 10000)

        result = OrderResult(
            order_id     = f"PAPER-{symbol}-{int(time.time()*1000)}",
            symbol       = symbol,
            direction    = direction,
            qty          = qty,
            entry_price  = entry_price,
            filled_price = round(filled, 2),
            slippage_pct = slip_bps / 100,
            status       = "FILLED",
            mode         = "PAPER",
            reason       = f"Paper fill @ ₹{filled:.2f} (slip={slip_bps}bps)"
        )
        self.fills.append(result)
        logger.info("[PAPER] %s %s ×%d @₹%.2f (slippage %.2fbps)",
                    direction, symbol, qty, filled, slip_bps)
        return result

    def modify_sl(self, order_id: str, new_sl: float) -> bool:
        """Simulate trailing SL modification."""
        logger.info("[PAPER] ModifySL %s → ₹%.2f", order_id, new_sl)
        return True

    def cancel_order(self, order_id: str) -> bool:
        logger.info("[PAPER] Cancel %s", order_id)
        return True

    def get_fill_stats(self) -> dict:
        if not self.fills: return {"fills": 0, "avg_slippage_bps": 0}
        avg_slip = sum(f.slippage_pct for f in self.fills) / len(self.fills) * 100
        return {"fills": len(self.fills), "avg_slippage_bps": avg_slip}


class OpenAlgoExecutor:
    """Live order execution via OpenAlgo API. Called ONLY in LIVE mode."""

    def __init__(self):
        self.host  = OPENALGO_HOST
        self.key   = OPENALGO_KEY
        self.fills: list[OrderResult] = []

    def _headers(self):
        return {"Content-Type": "application/json", "X-API-KEY": self.key}

    def place_order(self, symbol: str, direction: str, qty: int,
                    entry_price: float, order_type: str = "MARKET") -> OrderResult:
        """Place a live order via OpenAlgo."""
        payload = {
            "symbol":    symbol,
            "exchange":  "NSE",
            "action":    direction,
            "quantity":  qty,
            "ordertype": order_type,
            "product":   "MIS",  # intraday; use CNC for delivery
        }
        try:
            resp = requests.post(f"{self.host}/placeorder", json=payload,
                                 headers=self._headers(), timeout=5)
            resp.raise_for_status()
            data = resp.json()
            oid  = data.get("orderid", "UNKNOWN")
            fill = data.get("fill_price", entry_price)
            slip = abs(fill - entry_price) / entry_price * 100
            result = OrderResult(
                order_id=oid, symbol=symbol, direction=direction, qty=qty,
                entry_price=entry_price, filled_price=fill,
                slippage_pct=slip, status="FILLED", mode="LIVE",
                reason=f"OpenAlgo fill @ ₹{fill:.2f}"
            )
            self.fills.append(result)
            logger.info("[LIVE] %s %s ×%d @₹%.2f", direction, symbol, qty, fill)
            return result
        except Exception as e:
            logger.error("[LIVE] Order failed: %s", e)
            return OrderResult(
                order_id="FAILED", symbol=symbol, direction=direction, qty=qty,
                entry_price=entry_price, filled_price=0, slippage_pct=0,
                status="REJECTED", mode="LIVE", reason=str(e)
            )

    def get_positions(self) -> list:
        try:
            resp = requests.get(f"{self.host}/positions", headers=self._headers(), timeout=5)
            return resp.json().get("data", [])
        except Exception as e:
            logger.error("Positions fetch failed: %s", e)
            return []

    def get_pnl(self) -> dict:
        try:
            resp = requests.get(f"{self.host}/pnl", headers=self._headers(), timeout=5)
            return resp.json()
        except Exception as e:
            logger.error("P&L fetch failed: %s", e)
            return {}

    def mass_cancel(self) -> bool:
        """Kill switch: cancel all open orders."""
        try:
            resp = requests.post(f"{self.host}/cancelallorder", headers=self._headers(), timeout=10)
            logger.critical("[LIVE] Mass cancel issued")
            return resp.status_code == 200
        except Exception as e:
            logger.error("Mass cancel failed: %s", e)
            return False


class MercuryAgent:
    """
    MERCURY wraps Paper or Live executor based on MODE env var.
    Guardian must approve every trade before Mercury executes.
    """

    def __init__(self):
        self.mode = MODE
        self.executor = PaperExecutor() if MODE == "PAPER" else OpenAlgoExecutor()
        logger.info("MERCURY: Running in %s mode", self.mode)

    def execute(self, proposal: dict, guardian_approval: tuple) -> Optional[OrderResult]:
        """
        Execute a trade proposal if Guardian approved.
        proposal = {symbol, direction, qty, entry_price, stop_loss, target}
        guardian_approval = (approved: bool, reason: str, adjusted_qty: int)
        """
        approved, reason, adj_qty = guardian_approval
        if not approved:
            logger.warning("MERCURY: Trade BLOCKED by GUARDIAN — %s", reason)
            return None

        sym   = proposal["symbol"]
        dir_  = proposal["direction"]
        entry = proposal["entry_price"]

        result = self.executor.place_order(sym, dir_, adj_qty, entry)
        if result.status == "FILLED":
            logger.info("MERCURY: Order FILLED — %s %s ×%d @₹%.2f [%s]",
                        dir_, sym, adj_qty, result.filled_price, self.mode)
        return result

    def get_stats(self) -> dict:
        return self.executor.get_fill_stats()
