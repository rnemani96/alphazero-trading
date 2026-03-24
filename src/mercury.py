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
    external_id:  str   = ""    # Broker's ID
    symbol:       str   = ""
    direction:    str   = ""   # BUY / SELL
    qty:          int   = 0
    entry_price:  float = 0.0
    filled_price: float = 0.0
    slippage_pct: float = 0.0
    status:       str   = "PENDING"   # FILLED / REJECTED / PENDING / COMPLETED
    mode:         str   = "PAPER"     # PAPER / LIVE
    timestamp:    str   = field(default_factory=lambda: datetime.now().isoformat())
    reason:       str   = ""
    data:         dict  = field(default_factory=dict) # Raw response from broker


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

    def execute_trade(self, signal: dict) -> dict:
        """Requirement for MercuryAgent: unified entry point."""
        res = self.place_order(
            signal['symbol'], signal['action'], signal['quantity'], signal['price']
        )
        return {
            'success': res.status == "FILLED",
            'fill_price': res.filled_price,
            'quantity': res.qty,
            'order_id': res.order_id
        }

    def modify_sl(self, order_id: str, new_sl: float) -> bool:
        """Simulate trailing SL modification."""
        logger.info("[PAPER] ModifySL %s → ₹%.2f", order_id, new_sl)
        return True

    def cancel_order(self, order_id: str) -> bool:
        logger.info("[PAPER] Cancel %s", order_id)
        return True

    def modify_order(self, order_id: str, symbol: str, new_price: float, **kwargs) -> bool:
        """Simulate order modification (SL/Target)."""
        logger.info("[PAPER] ModifyOrder %s %s → ₹%.2f", order_id, symbol, new_price)
        return True

    def close_position(self, position: dict) -> dict:
        """Simulate closing an open position."""
        logger.info("[PAPER] Closing position %s", position.get('symbol'))
        return {'success': True, 'pnl': 0.0, 'fill_price': 0.0}

    def get_fill_stats(self) -> dict:
        if not self.fills: return {"fills": 0, "avg_slippage_bps": 0}
        avg_slip = sum(f.slippage_pct for f in self.fills) / len(self.fills) * 100
        return {"fills": len(self.fills), "avg_slippage_bps": avg_slip}


class OpenAlgoExecutor:
    """Live order execution via OpenAlgo API. Called ONLY in LIVE mode."""

    MAX_RETRIES      = 3
    RETRY_DELAY_S    = 0.05  # 50 ms between retries (Optimized for NSE Co-Location latency)

    def __init__(self):
        self.host  = OPENALGO_HOST
        self.key   = OPENALGO_KEY
        self.fills: list[OrderResult] = []

    def _headers(self):
        return {"Content-Type": "application/json", "X-API-KEY": self.key}

    def _post_with_retry(self, endpoint: str, payload: dict) -> dict:
        """POST with 3× retry + 500ms backoff. Raises on final failure."""
        url      = f"{self.host}{endpoint}"
        last_err = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = requests.post(url, json=payload,
                                     headers=self._headers(), timeout=5)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError:
                raise   # 4xx/5xx — don't retry broker rejections
            except Exception as e:
                last_err = e
                logger.warning("[LIVE] %s attempt %d/%d failed: %s",
                               endpoint, attempt, self.MAX_RETRIES, e)
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY_S)
        raise ConnectionError(f"{endpoint} failed after {self.MAX_RETRIES} retries: {last_err}")

    def place_order(self, symbol: str, direction: str, qty: int,
                    entry_price: float, order_type: str = "MARKET",
                    product: str = "MIS") -> OrderResult:
        """Place a live order via OpenAlgo with retry logic."""
        payload = {
            "symbol":    symbol,
            "exchange":  "NSE",
            "action":    direction,
            "quantity":  qty,
            "ordertype": order_type,
            "product":   product,
            "price":     str(round(entry_price, 2)) if order_type != "MARKET" else "0",
        }
        try:
            data = self._post_with_retry("/placeorder", payload)
            oid        = data.get("orderid", "UNKNOWN")
            fill       = data.get("fill_price", entry_price)
            qty_filled = int(data.get("qty_filled") or data.get("filled_quantity") or qty)
            slip       = abs(fill - entry_price) / entry_price * 100 if entry_price else 0
            # Partial fill handling — broker may return qty_filled < requested qty
            status = "FILLED" if qty_filled >= qty else ("PARTIAL" if qty_filled > 0 else "REJECTED")
            if qty_filled < qty:
                logger.warning("[LIVE] Partial fill: requested=%d  filled=%d  symbol=%s",
                               qty, qty_filled, symbol)
            result = OrderResult(
                order_id=oid, external_id=oid, symbol=symbol, direction=direction, qty=qty_filled,
                entry_price=entry_price, filled_price=fill,
                slippage_pct=slip, status=status, mode="LIVE",
                reason=f"OpenAlgo fill @ ₹{fill:.2f} ({qty_filled}/{qty} filled)",
                data=data
            )
            self.fills.append(result)
            logger.info("[LIVE] %s %s ×%d @₹%.2f", direction, symbol, qty, fill)
            return result
        except Exception as e:
            logger.error("[LIVE] Order FAILED after retries: %s", e)
            return OrderResult(
                order_id="FAILED", symbol=symbol, direction=direction, qty=qty,
                entry_price=entry_price, filled_price=0, slippage_pct=0,
                status="REJECTED", mode="LIVE", reason=str(e)
            )

    def execute_trade(self, signal: dict) -> dict:
        """Requirement for MercuryAgent: high-precision live execution."""
        # Check if we should use patient limit execution (Requirement #3.4)
        use_patient = signal.get('confidence', 0) > 0.7  # Use for high-conviction trades
        
        if use_patient:
            res = self.execute_with_patience(
                signal['symbol'], signal['action'], signal['quantity'], signal['price']
            )
        else:
            res = self.place_order(
                signal['symbol'], signal['action'], signal['quantity'], signal['price']
            )
            
        return {
            'success': res.status == "FILLED",
            'fill_price': res.filled_price,
            'quantity': res.qty,
            'order_id': res.order_id,
            'error': res.reason if res.status != "FILLED" else ""
        }

    def execute_with_patience(self, symbol: str, direction: str, qty: int,
                              entry_price: float, wait_seconds: int = 30) -> OrderResult:
        """Requirement #3.4: Patient Limit Order (Wait 30s before market buy)."""
        logger.info(f"[PATIENT] Placing limit order for {symbol} @ ₹{entry_price:.2f} (wait {wait_seconds}s)")
        
        # 1. Place Limit Order
        limit_result = self.place_order(symbol, direction, qty, entry_price, order_type="LIMIT")
        if limit_result.status == "FILLED":
            return limit_result
            
        # 2. Wait and poll status (Simulation for now; OpenAlgo needs /orderstatus endpoint)
        start_time = time.time()
        while time.time() - start_time < wait_seconds:
            # check_status = self._get_with_retry(f"/orderstatus/{limit_result.order_id}")
            # if check_status.get('status') == 'FILLED': return ...
            time.sleep(2) # Polling interval
            
        # 3. If still pending, cancel and go market
        logger.info(f"[PATIENT] {symbol} limit not filled. Switching to MARKET.")
        self.cancel_order(limit_result.order_id)
        return self.place_order(symbol, direction, qty, entry_price, order_type="MARKET")

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order via OpenAlgo."""
        try:
            self._post_with_retry("/cancelorder", {"orderid": order_id})
            return True
        except Exception:
            return False

    def place_bracket_order(self, symbol: str, direction: str, qty: int,
                             entry_price: float, stop_loss: float,
                             target: float) -> OrderResult:
        """
        Bracket order — exchange manages SL + target automatically (MIS/BO product).
        SL and squareoff are point distances from entry, not absolute prices.
        """
        sl_pts  = abs(entry_price - stop_loss)
        tgt_pts = abs(target - entry_price)
        payload = {
            "symbol":      symbol,
            "exchange":    "NSE",
            "action":      direction,
            "quantity":    qty,
            "ordertype":   "MARKET",
            "product":     "BO",
            "price":       "0",
            "stoploss":    str(round(sl_pts, 2)) if sl_pts > 0 else "0",
            "squareoff":   str(round(tgt_pts, 2)) if tgt_pts > 0 else "0",
            "trailing_sl": "0",
        }
        try:
            data = self._post_with_retry("/placeorder", payload)
            oid  = data.get("orderid", "UNKNOWN")
            fill = data.get("fill_price", entry_price)
            result = OrderResult(
                order_id=oid, symbol=symbol, direction=direction, qty=qty,
                entry_price=entry_price, filled_price=fill,
                slippage_pct=0.0, status="FILLED", mode="LIVE",
                reason=f"Bracket order @ ₹{fill:.2f}  SL={sl_pts:.2f}pts  TGT={tgt_pts:.2f}pts"
            )
            self.fills.append(result)
            logger.info("[LIVE BO] %s %s ×%d  SL=₹%.2f  TGT=₹%.2f",
                        direction, symbol, qty, stop_loss, target)
            return result
        except Exception as e:
            logger.error("[LIVE BO] Bracket order failed: %s", e)
            return OrderResult(
                order_id="FAILED", symbol=symbol, direction=direction, qty=qty,
                entry_price=entry_price, filled_price=0, slippage_pct=0,
                status="REJECTED", mode="LIVE", reason=str(e)
            )

    def modify_order(self, order_id: str, symbol: str,
                     new_price: float = 0.0, new_trigger: float = 0.0,
                     order_type: str = "SL") -> bool:
        """Modify an open order — used for trailing stop-loss updates."""
        payload = {
            "orderid":       order_id,
            "symbol":        symbol,
            "exchange":      "NSE",
            "ordertype":     order_type,
            "price":         str(round(new_price, 2)),
            "trigger_price": str(round(new_trigger, 2)),
        }
        try:
            data = self._post_with_retry("/modifyorder", payload)
            ok   = data.get("status", "").upper() in ("SUCCESS", "MODIFIED", "COMPLETE", "")
            logger.info("[LIVE] ModifyOrder %s → ₹%.2f  ok=%s", order_id, new_price, ok)
            return ok
        except Exception as e:
            logger.error("[LIVE] ModifyOrder failed: %s", e)
            return False

    def cancel_order(self, order_id: str, symbol: str = "") -> bool:
        """Cancel a specific open order."""
        payload = {"orderid": order_id, "symbol": symbol, "exchange": "NSE"}
        try:
            data = self._post_with_retry("/cancelorder", payload)
            ok   = data.get("status", "").upper() in ("SUCCESS", "CANCELLED", "COMPLETE", "")
            logger.info("[LIVE] CancelOrder %s  ok=%s", order_id, ok)
            return ok
        except Exception as e:
            logger.error("[LIVE] CancelOrder failed: %s", e)
            return False

    def close_position(self, position: dict) -> dict:
        """Requirement #3.4: Live position closure."""
        symbol = position.get('symbol')
        qty    = position.get('quantity', position.get('qty', 0))
        # For simple square off, we place an opposite market order
        direction = "SELL" if "BUY" in str(position.get('side', 'BUY')).upper() else "BUY"
        logger.info(f"[LIVE] Squaring off {symbol} ({qty} units)")
        
        try:
            res = self.place_order(symbol, direction, qty, 0.0, order_type="MARKET")
            return {
                'success': res.status == "FILLED",
                'fill_price': res.filled_price,
                'pnl': (res.filled_price - position.get('entry_price', 0)) * qty if direction == "SELL" else 0
            }
        except Exception as e:
            logger.error(f"Live close failed: {e}")
            return {'success': False, 'error': str(e)}

    def get_positions(self) -> list:
        try:
            resp = requests.get(f"{self.host}/positionbook",
                                headers=self._headers(), timeout=5)
            return resp.json().get("data", [])
        except Exception as e:
            logger.error("Positions fetch failed: %s", e)
            return []

    def get_orderbook(self) -> list:
        """Today's full order book."""
        try:
            resp = requests.get(f"{self.host}/orderbook",
                                headers=self._headers(), timeout=5)
            return resp.json().get("data", [])
        except Exception as e:
            logger.error("Orderbook fetch failed: %s", e)
            return []

    def get_pnl(self) -> dict:
        try:
            resp = requests.get(f"{self.host}/pnl", headers=self._headers(), timeout=5)
            return resp.json()
        except Exception as e:
            logger.error("P&L fetch failed: %s", e)
            return {}

    def get_balance(self) -> float:
        """Fetch available margin/balance from broker."""
        try:
            # OpenAlgo endpoint for margin/funds
            resp = requests.get(f"{self.host}/funds", headers=self._headers(), timeout=5)
            data = resp.json()
            if data.get("status") == "success":
                # Typical format: {"status": "success", "data": {"available_margin": 123000}}
                return float(data.get("data", {}).get("available_margin", 0))
            return 0.0
        except Exception as e:
            logger.error(f"Balance fetch failed: {e}")
            return 0.0

    def sync_positions(self) -> list:
        """Fetch live positions and standardize format."""
        try:
            positions = self.get_positions()
            # Standardize: AlphaZero expects [{symbol, qty, entry, pnl, ...}]
            standardized = []
            for p in positions:
                standardized.append({
                    "symbol": p.get("symbol"),
                    "qty": int(p.get("quantity", 0)),
                    "entry": float(p.get("average_price", 0)),
                    "pnl": float(p.get("pnl", 0)),
                    "product": p.get("product"),
                    "raw": p
                })
            return standardized
        except Exception as e:
            logger.error(f"Position sync failed: {e}")
            return []

    def mass_cancel(self) -> bool:
        """Kill switch: cancel ALL open orders immediately."""
        try:
            resp = requests.post(f"{self.host}/cancelallorder",
                                 headers=self._headers(), timeout=10)
            logger.critical("[LIVE] ⚠ MASS CANCEL issued")
            return resp.status_code == 200
        except Exception as e:
            logger.error("Mass cancel failed: %s", e)
            return False

    def get_fill_stats(self) -> dict:
        if not self.fills:
            return {"fills": 0, "avg_slippage_bps": 0, "rejected": 0}
        filled   = [f for f in self.fills if f.status == "FILLED"]
        rejected = [f for f in self.fills if f.status == "REJECTED"]
        avg_slip = sum(f.slippage_pct for f in filled) / max(len(filled), 1) * 100
        return {"fills": len(filled), "rejected": len(rejected),
                "avg_slippage_bps": round(avg_slip, 2)}


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

    def modify_order(self, order_id: str, symbol: str, new_price: float, 
                     new_trigger: float = 0.0, order_type: str = "SL-M") -> bool:
        """Forward modification request to executor."""
        try:
            return self.executor.modify_order(
                order_id=order_id,
                symbol=symbol,
                new_price=new_price,
                new_trigger=new_trigger or new_price,
                order_type=order_type
            )
        except Exception as e:
            logger.error(f"MERCURY: Modify order failed: {e}")
            return False

    def get_stats(self) -> dict:
        return self.executor.get_fill_stats()
