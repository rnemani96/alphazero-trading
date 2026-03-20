"""
src/execution/order_manager.py  —  AlphaZero Capital
══════════════════════════════════════════════════════
NEW: Order retry logic, partial fill handling, bracket orders (were TODO)

OrderManager wraps execution calls with:
  1. Retry rejected orders (up to 3× with 500ms backoff)
  2. Partial fill detection and residual re-order
  3. Bracket order (BO) creation via OpenAlgo BO endpoint
  4. Order state machine tracking

Used by MercuryAgent / main.py executor.
"""

from __future__ import annotations

import os, json, time, uuid, logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Callable
from enum import Enum
from pathlib import Path

logger = logging.getLogger("OrderManager")

_ROOT    = Path(__file__).resolve().parents[2]
_LOG_DIR = _ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_ORDER_LOG = str(_LOG_DIR / "orders.json")

MAX_RETRIES   = int(os.getenv('ORDER_MAX_RETRIES', 3))
RETRY_DELAY   = float(os.getenv('ORDER_RETRY_DELAY', 0.5))   # seconds


# ── Order state ───────────────────────────────────────────────────────────────

class OrderStatus(str, Enum):
    PENDING   = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL   = "PARTIAL"
    FILLED    = "FILLED"
    REJECTED  = "REJECTED"
    CANCELLED = "CANCELLED"
    RETRYING  = "RETRYING"


@dataclass
class Order:
    id:          str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    symbol:      str   = ""
    action:      str   = "BUY"      # BUY / SELL
    order_type:  str   = "MARKET"   # MARKET / LIMIT / SL-M
    quantity:    int   = 0
    price:       float = 0.0
    stop_loss:   float = 0.0
    target:      float = 0.0
    product:     str   = "MIS"      # MIS (intraday) / CNC (delivery)
    status:      OrderStatus = OrderStatus.PENDING
    filled_qty:  int   = 0
    avg_price:   float = 0.0
    retries:     int   = 0
    broker_id:   str   = ""
    error:       str   = ""
    created_at:  str   = field(default_factory=lambda: datetime.now().isoformat())
    updated_at:  str   = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['status'] = self.status.value
        return d


# ── Order persistence ─────────────────────────────────────────────────────────

def _load_orders() -> List[Dict]:
    try:
        with open(_ORDER_LOG) as f:
            return json.load(f)
    except Exception:
        return []

def _save_order(order: Order):
    orders = _load_orders()
    # Update existing or append
    found = False
    for i, o in enumerate(orders):
        if o.get('id') == order.id:
            orders[i] = order.to_dict()
            found = True
            break
    if not found:
        orders.append(order.to_dict())
    try:
        with open(_ORDER_LOG, 'w') as f:
            json.dump(orders[-1000:], f, indent=2)   # Keep last 1000 orders
    except Exception as e:
        logger.warning(f"Order log save failed: {e}")


# ── OrderManager ──────────────────────────────────────────────────────────────

class OrderManager:
    """
    Manages order lifecycle: placement, retry, partial fills, brackets.

    Usage:
        om = OrderManager(executor=paper_executor)
        order = om.place_market_order("RELIANCE", "BUY", 10)
        bracket = om.place_bracket_order("TCS", "BUY", 5, 3500, stop=3450, target=3600)
    """

    def __init__(self, executor=None, event_bus=None):
        self.executor  = executor
        self.event_bus = event_bus
        self._orders:  Dict[str, Order] = {}

    # ── Market order with retry ───────────────────────────────────────────────
    def place_market_order(self, symbol: str, action: str, quantity: int,
                            product: str = "MIS") -> Order:
        order = Order(symbol=symbol, action=action, quantity=quantity,
                      order_type="MARKET", product=product)
        self._orders[order.id] = order
        self._submit_with_retry(order)
        return order

    # ── Limit order with retry ────────────────────────────────────────────────
    def place_limit_order(self, symbol: str, action: str, quantity: int,
                           price: float, product: str = "MIS") -> Order:
        order = Order(symbol=symbol, action=action, quantity=quantity,
                      order_type="LIMIT", price=price, product=product)
        self._orders[order.id] = order
        self._submit_with_retry(order)
        return order

    # ── Bracket order (BO) ────────────────────────────────────────────────────
    def place_bracket_order(self, symbol: str, action: str, quantity: int,
                             price: float, stop: float, target: float) -> Order:
        """
        Bracket order: entry + SL + target in one atomic order via OpenAlgo BO endpoint.
        Falls back to manual SL/target tracking in PAPER mode.
        """
        order = Order(symbol=symbol, action=action, quantity=quantity,
                      order_type="BRACKET", price=price,
                      stop_loss=stop, target=target, product="MIS")
        self._orders[order.id] = order

        if self.executor and hasattr(self.executor, 'place_bracket_order'):
            # Live executor supports BO
            self._submit_bracket(order)
        else:
            # Paper / non-BO executor: place entry + register SL/target manually
            self._submit_with_retry(order)
            self._register_sl_target(order)

        return order

    def modify_order(self, order_id: str, symbol: str, new_price: float, 
                     new_trigger: float = 0.0, order_type: str = "SL-M") -> bool:
        """
        Modify an existing open order (e.g., update trailing stop loss).
        """
        if not self.executor:
            # Paper mode simulation
            order = self._orders.get(order_id)
            if order:
                order.stop_loss = new_price
                order.updated_at = datetime.now().isoformat()
                _save_order(order)
            return True

        try:
            # Call underlying executor
            success = self.executor.modify_order(
                order_id=order_id,
                symbol=symbol,
                new_price=new_price,
                new_trigger=new_trigger or new_price,
                order_type=order_type
            )
            
            if success:
                order = self._orders.get(order_id)
                if order:
                    order.stop_loss = new_price
                    order.updated_at = datetime.now().isoformat()
                    _save_order(order)
                return True
            return False
        except Exception as e:
            logger.error(f"OrderManager.modify_order error: {e}")
            return False

    # ── Cancel order ──────────────────────────────────────────────────────────
    def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if not order:
            return False
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return False
        order.status     = OrderStatus.CANCELLED
        order.updated_at = datetime.now().isoformat()
        _save_order(order)
        if self.event_bus:
            try:
                self.event_bus.publish("ORDER_CANCELLED", order.to_dict())
            except Exception:
                pass
        return True

    # ── Internal: submit with retry ───────────────────────────────────────────
    def _submit_with_retry(self, order: Order):
        for attempt in range(MAX_RETRIES):
            order.retries    = attempt
            order.status     = OrderStatus.RETRYING if attempt > 0 else OrderStatus.SUBMITTED
            order.updated_at = datetime.now().isoformat()
            _save_order(order)

            try:
                result = self._call_executor(order)

                if result and result.get('status') in ('complete', 'filled', 'success', 'open', True):
                    self._on_fill(order, result)
                    return

                elif result and result.get('filled_qty', 0) > 0:
                    # Partial fill
                    self._on_partial_fill(order, result)
                    return

                else:
                    err = result.get('error', 'Unknown error') if result else 'No response'
                    logger.warning(f"Order rejected ({attempt+1}/{MAX_RETRIES}): {order.symbol} — {err}")
                    order.error = err
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY * (2 ** attempt))   # exponential backoff

            except Exception as e:
                logger.warning(f"Order submit exception ({attempt+1}): {e}")
                order.error = str(e)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (2 ** attempt))

        order.status     = OrderStatus.REJECTED
        order.updated_at = datetime.now().isoformat()
        _save_order(order)
        logger.error(f"Order REJECTED after {MAX_RETRIES} retries: {order.symbol} {order.action} {order.quantity}")
        if self.event_bus:
            try:
                self.event_bus.publish("ORDER_REJECTED", order.to_dict())
            except Exception:
                pass

    def _call_executor(self, order: Order) -> Optional[Dict]:
        """Call the underlying executor (paper or live)."""
        if self.executor is None:
            # Simulate success for paper mode
            return {
                'status':     'complete',
                'filled_qty': order.quantity,
                'avg_price':  order.price or 100.0,
                'broker_id':  f"PAPER-{order.id}",
            }
        try:
            return self.executor.place_order(
                symbol=order.symbol,
                action=order.action,
                quantity=order.quantity,
                order_type=order.order_type,
                price=order.price,
                product=order.product,
            )
        except Exception as e:
            logger.error(f"Executor.place_order error: {e}")
            return None

    def _submit_bracket(self, order: Order):
        """Submit bracket order via executor's BO endpoint."""
        if self.executor is None:
            self._submit_with_retry(order)
            return
        try:
            result = self.executor.place_bracket_order(
                symbol=order.symbol,
                action=order.action,
                quantity=order.quantity,
                price=order.price,
                stop_loss=order.stop_loss,
                target=order.target,
            )
            if result and result.get('status') in ('complete', 'open', True):
                self._on_fill(order, result)
            else:
                # Fallback to regular order
                logger.warning("Bracket order failed — falling back to market order")
                self._submit_with_retry(order)
        except AttributeError:
            self._submit_with_retry(order)

    def _on_fill(self, order: Order, result: Dict):
        order.status     = OrderStatus.FILLED
        order.filled_qty = result.get('filled_qty', order.quantity)
        order.avg_price  = result.get('avg_price', order.price)
        order.broker_id  = result.get('broker_id', '')
        order.updated_at = datetime.now().isoformat()
        _save_order(order)
        logger.info(f"Order FILLED: {order.symbol} {order.action} {order.filled_qty}@{order.avg_price}")
        if self.event_bus:
            try:
                self.event_bus.publish("ORDER_FILLED", order.to_dict())
            except Exception:
                pass

    def _on_partial_fill(self, order: Order, result: Dict):
        """Handle partial fill — re-submit residual quantity."""
        filled_qty   = result.get('filled_qty', 0)
        residual_qty = order.quantity - filled_qty

        order.status     = OrderStatus.PARTIAL
        order.filled_qty = filled_qty
        order.avg_price  = result.get('avg_price', order.price)
        order.updated_at = datetime.now().isoformat()
        _save_order(order)

        logger.info(f"Order PARTIAL: {order.symbol} filled {filled_qty}/{order.quantity}, re-submitting {residual_qty}")

        if residual_qty > 0:
            residual = Order(
                symbol=order.symbol, action=order.action,
                quantity=residual_qty, order_type=order.order_type,
                price=order.price, product=order.product,
            )
            self._orders[residual.id] = residual
            self._submit_with_retry(residual)

    def _register_sl_target(self, order: Order):
        """Register SL/target with event bus for manual management."""
        if self.event_bus and order.stop_loss and order.target:
            try:
                self.event_bus.publish("REGISTER_SL_TARGET", {
                    "order_id":  order.id,
                    "symbol":    order.symbol,
                    "stop_loss": order.stop_loss,
                    "target":    order.target,
                })
            except Exception:
                pass

    # ── Stats ─────────────────────────────────────────────────────────────────
    def get_active_orders(self) -> List[Dict]:
        return [o.to_dict() for o in self._orders.values()
                if o.status not in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)]

    def get_order_stats(self) -> Dict:
        orders = list(self._orders.values())
        return {
            "total":    len(orders),
            "filled":   sum(1 for o in orders if o.status == OrderStatus.FILLED),
            "partial":  sum(1 for o in orders if o.status == OrderStatus.PARTIAL),
            "rejected": sum(1 for o in orders if o.status == OrderStatus.REJECTED),
            "pending":  sum(1 for o in orders if o.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED)),
        }
