"""
Paper Trading Executor
src/execution/paper_executor.py

FIXED: Replaced stub that hardcoded fill_price=2450.50 for every trade.
Real implementation:
  - Uses actual LTP from signal or DataFetcher
  - Realistic slippage model (random 0-16 bps)
  - Tracks open positions with live P&L
  - Stop-loss / target auto-close on price update
"""

import random
import time
import logging
from datetime import datetime
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class PaperExecutor:
    """
    Simulates order execution with real prices and realistic slippage.

    Positions are tracked internally.
    Call update_prices(prices_dict) each iteration to refresh P&L and
    check stop/target hits.
    """

    SLIPPAGE_BPS_MAX = 16   # max one-way slippage in basis points (0.16%)

    def __init__(self, config: Dict):
        self.config   = config
        self.capital  = config.get('INITIAL_CAPITAL', 1_000_000)
        self._positions: Dict[str, Dict] = {}
        self._closed_trades = []
        self._total_pnl = 0.0
        # Shared price cache — updated by main loop via update_prices()
        self._prices: Dict[str, float] = {}

    def _simulate_order_book_fill(self, action: str, qty: int, ltp: float) -> tuple[float, int]:
        """
        Simulate walking the Level 2 Order Book.
        Computes Volume-Weighted Average Price (VWAP) to clear the requested quantity across multiple depth levels.
        """
        if qty <= 0 or ltp <= 0:
            return ltp, 0

        # Assumptions for a NIFTY50 stock:
        # Tick size = 0.05. Average liquid depth per tick = 500-1500 shares.
        tick_size = 0.05
        avg_depth_per_level = random.randint(500, 2000)
        
        remaining = qty
        total_cost = 0.0
        current_level_price = ltp
        
        # Base spread crossing cost
        spread_ticks = random.randint(1, 3)
        if action.upper() in ('BUY', 'LONG'):
            current_level_price += (spread_ticks * tick_size)
        else:
            current_level_price -= (spread_ticks * tick_size)
        
        while remaining > 0:
            filled_at_level = min(remaining, avg_depth_per_level)
            total_cost += (filled_at_level * current_level_price)
            remaining -= filled_at_level
            
            if remaining > 0:
                if action.upper() in ('BUY', 'LONG'):
                    current_level_price += tick_size
                else:
                    current_level_price -= tick_size
                    
                # Market depth gets thinner (or thicker) as you push the book
                avg_depth_per_level = int(avg_depth_per_level * 0.8)
                if avg_depth_per_level < 50:
                    avg_depth_per_level = 50
                    
        vwap_fill = total_cost / qty
        # Calculate resulting slippage in basis points
        slip_bps = abs(vwap_fill - ltp) / ltp * 10000
        return round(vwap_fill, 2), int(slip_bps)

    # ── public API ────────────────────────────────────────────────────────────

    def execute_trade(self, signal: Dict) -> Dict:
        """
        Simulate a trade fill.

        signal dict expected keys:
          symbol, signal/action (BUY/SELL), quantity (optional),
          price/ltp/current_price (optional — falls back to cached price)
        """
        symbol   = signal.get('symbol', 'UNKNOWN')
        action   = (signal.get('signal') or signal.get('action', 'BUY')).upper()
        qty      = signal.get('quantity', 0) or 1

        # --- Get real price (not hardcoded) ---
        raw_price = (
            signal.get('price') or
            signal.get('ltp') or
            signal.get('current_price') or
            signal.get('entry_price') or
            self._prices.get(symbol) or
            0.0
        )

        if not raw_price or raw_price <= 0:
            # Still no price - can't fill
            logger.error(f"[PAPER] No price available for {symbol} — trade rejected")
            return {'success': False, 'error': f'No LTP available for {symbol}'}

        # --- Apply level 2 order book impact ---
        fill_price, slip_bps = self._simulate_order_book_fill(action, qty, raw_price)

        # --- Stop loss and target from signal ---
        atr       = signal.get('atr', raw_price * 0.015)
        stop_loss = signal.get('stop_loss') or round(raw_price - 2 * atr, 2)
        target    = signal.get('target')    or round(raw_price + 3 * atr, 2)

        logger.info(
            f"[PAPER] {action} {symbol} ×{qty} @₹{fill_price:.2f} "
            f"SL=₹{stop_loss:.2f} TGT=₹{target:.2f} (slip={slip_bps}bps)"
        )

        # --- Record position ---
        self._positions[symbol] = {
            'symbol':        symbol,
            'side':          action,
            'quantity':      qty,
            'entry_price':   fill_price,
            'current_price': fill_price,
            'stop_loss':     stop_loss,
            'target':        target,
            'unrealised_pnl': 0.0,
            'source':        signal.get('source', 'TITAN'),
            'mtf_confirmed': signal.get('mtf_confirmed', False),
            'confidence':    signal.get('confidence', 0),
            'opened_at':     datetime.now().isoformat(),
            'slippage_bps':  slip_bps,
        }

        return {
            'success':    True,
            'fill_price': fill_price,
            'quantity':   qty,
            'stop_loss':  stop_loss,
            'target':     target,
            'slippage_bps': slip_bps,
        }

    def close_position(self, position: Dict) -> Dict:
        """Close a position and record realised P&L."""
        symbol = position.get('symbol', '')
        pos    = self._positions.get(symbol) or position

        entry  = pos.get('entry_price', 0)
        qty    = pos.get('quantity', 0)
        side   = pos.get('side', 'BUY').upper()

        # Current price for exit
        exit_price = (
            self._prices.get(symbol) or
            pos.get('current_price', entry)
        )

        # Slippage on exit via Order Book Simulation
        close_action = 'SELL' if side in ('BUY', 'LONG') else 'BUY'
        fill_exit, slip_bps = self._simulate_order_book_fill(close_action, qty, exit_price)

        if side in ('BUY', 'LONG'):
            pnl = (fill_exit - entry) * qty
        else:
            pnl = (entry - fill_exit) * qty

        self._total_pnl += pnl

        # Archive
        closed = {
            **pos,
            'exit_price':    fill_exit,
            'realised_pnl':  round(pnl, 2),
            'closed_at':     datetime.now().isoformat(),
        }
        self._closed_trades.append(closed)
        self._positions.pop(symbol, None)

        logger.info(
            f"[PAPER] Closed {symbol} @ ₹{fill_exit:.2f}  P&L: ₹{pnl:+,.0f}"
        )
        return {'success': True, 'pnl': round(pnl, 2), 'fill_price': fill_exit}

    def update_prices(self, prices: Dict[str, float]):
        """
        Called every iteration by main loop with latest prices.
        Updates unrealised P&L and auto-closes stops/targets.
        """
        self._prices.update(prices)
        to_close = []

        for sym, pos in list(self._positions.items()):
            price = prices.get(sym)
            if not price:
                continue

            pos['current_price'] = price
            entry = pos['entry_price']
            qty   = pos['quantity']
            side  = pos.get('side', 'BUY').upper()

            if side in ('BUY', 'LONG'):
                pos['unrealised_pnl'] = round((price - entry) * qty, 2)
                hit_sl  = price <= pos['stop_loss']
                hit_tgt = price >= pos['target']
            else:
                pos['unrealised_pnl'] = round((entry - price) * qty, 2)
                hit_sl  = price >= pos['stop_loss']
                hit_tgt = price <= pos['target']

            if hit_sl:
                logger.info(f"[PAPER] Stop-loss hit: {sym} @ ₹{price:.2f}")
                to_close.append(pos)
            elif hit_tgt:
                logger.info(f"[PAPER] Target hit: {sym} @ ₹{price:.2f} 🎯")
                to_close.append(pos)

        for pos in to_close:
            self.close_position(pos)

    def get_positions(self) -> Dict[str, Dict]:
        """Return current open positions."""
        return dict(self._positions)

    def get_closed_trades(self):
        return list(self._closed_trades)

    def get_total_pnl(self) -> float:
        return self._total_pnl
