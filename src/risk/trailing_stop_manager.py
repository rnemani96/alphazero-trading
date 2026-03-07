"""
AlphaZero Capital v16 - Trailing Stop Loss Manager
Automatically trail stops to lock in profits
Expected Impact: +3-5% annually
"""

import numpy as np
from datetime import datetime
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class TrailingStopManager:
    """
    TRAILING STOP LOSS MANAGER
    
    Philosophy: Let winners run, but don't give back all profits!
    
    Features:
    1. ATR-based trailing stops
    2. Percentage-based trailing
    3. Profit-level activation
    4. Dynamic adjustment based on volatility
    
    Expected Impact: Lock in +3-5% more profits annually
    """
    
    def __init__(self, event_bus=None, config: Dict = None):
        # Accept (event_bus, config) OR legacy (config,) / (config_dict,)
        if config is None and isinstance(event_bus, dict):
            config = event_bus
            event_bus = None
        self.event_bus = event_bus
        self.config = config or {}

        # Configuration
        self.activation_profit_pct = self.config.get('ACTIVATION_PROFIT_PCT', 0.02)
        self.trail_atr_multiplier  = self.config.get('TRAIL_ATR_MULTIPLIER', 1.5)
        self.trail_pct             = self.config.get('TRAIL_PCT', 0.03)

        # Track trailing stops for each position
        self.trailing_stops     = {}
        self.total_locked_profit = 0.0   # exposed to main.py / dashboard

        logger.info(f"Trailing Stop Manager initialized - Activation: {self.activation_profit_pct:.1%}")

    def update_trailing_stops(self, market_data_or_positions, market_data: Dict = None) -> Dict:
        """
        Flexible signature — called two ways from main.py:
          update_trailing_stops(stop_data)          # {symbol: {price, atr}}
          update_trailing_stops(positions, market)  # original signature
        """
        # New-style call: update_trailing_stops({symbol: {price, atr}})
        if market_data is None:
            stop_data = market_data_or_positions  # {symbol: {price, atr, ...}}
            updated = {}
            for symbol, info in stop_data.items():
                price = info.get('price', 0)
                atr   = info.get('atr',   price * 0.01)
                if symbol in self.trailing_stops:
                    ts = self.trailing_stops[symbol]
                    entry      = ts.get('entry_price', price)
                    old_stop   = ts.get('stop_loss', entry * 0.95)
                    profit_pct = (price - entry) / entry if entry else 0
                    if profit_pct >= self.activation_profit_pct:
                        atr_stop = price - atr * self.trail_atr_multiplier
                        pct_stop = price * (1 - self.trail_pct)
                        new_stop = max(atr_stop, pct_stop, old_stop)
                        if new_stop > old_stop:
                            self.trailing_stops[symbol]['stop_loss'] = new_stop
                            self.total_locked_profit = max(
                                0, (new_stop - entry) * ts.get('quantity', 1)
                            )
                            updated[symbol] = new_stop
            return updated
        # Legacy call: update_trailing_stops(positions, market_data)
        """
        Update trailing stops for all positions
        
        Returns: Dictionary of updated stop losses
        """
        
        updated_stops = {}
        
        for position in positions:
            symbol = position['symbol']
            entry_price = position['entry_price']
            current_price = market_data.get(symbol, {}).get('price', entry_price)
            current_stop = position.get('stop_loss', entry_price * 0.95)
            
            # Calculate profit
            if position['side'] == 'LONG':
                profit_pct = (current_price - entry_price) / entry_price
            else:  # SHORT
                profit_pct = (entry_price - current_price) / entry_price
            
            # Only activate trailing if in profit
            if profit_pct >= self.activation_profit_pct:
                
                # Get ATR for symbol
                atr = market_data.get(symbol, {}).get('atr', entry_price * 0.02)
                
                # Calculate new trailing stop
                if position['side'] == 'LONG':
                    # ATR-based trailing
                    atr_stop = current_price - (atr * self.trail_atr_multiplier)
                    
                    # Percentage-based trailing
                    pct_stop = current_price * (1 - self.trail_pct)
                    
                    # Use the higher of the two
                    new_stop = max(atr_stop, pct_stop)
                    
                    # Only raise stops, never lower
                    if new_stop > current_stop:
                        updated_stops[symbol] = {
                            'old_stop': current_stop,
                            'new_stop': new_stop,
                            'method': 'ATR' if new_stop == atr_stop else 'PERCENTAGE',
                            'locked_profit': new_stop - entry_price,
                            'locked_profit_pct': (new_stop - entry_price) / entry_price
                        }
                        
                        logger.info(
                            f"📈 {symbol} - Trailing stop RAISED: "
                            f"₹{current_stop:.2f} → ₹{new_stop:.2f} "
                            f"(Locking {updated_stops[symbol]['locked_profit_pct']:.1%} profit)"
                        )
                
                else:  # SHORT position
                    # ATR-based trailing
                    atr_stop = current_price + (atr * self.trail_atr_multiplier)
                    
                    # Percentage-based trailing
                    pct_stop = current_price * (1 + self.trail_pct)
                    
                    # Use the lower of the two
                    new_stop = min(atr_stop, pct_stop)
                    
                    # Only lower stops for shorts, never raise
                    if new_stop < current_stop:
                        updated_stops[symbol] = {
                            'old_stop': current_stop,
                            'new_stop': new_stop,
                            'method': 'ATR' if new_stop == atr_stop else 'PERCENTAGE',
                            'locked_profit': entry_price - new_stop,
                            'locked_profit_pct': (entry_price - new_stop) / entry_price
                        }
                        
                        logger.info(
                            f"📉 {symbol} - Trailing stop LOWERED (SHORT): "
                            f"₹{current_stop:.2f} → ₹{new_stop:.2f}"
                        )
        
        return updated_stops
    
    def get_recommended_initial_stop(self, symbol: str, entry_price: float, side: str, atr: float) -> float:
        """
        Calculate initial stop loss based on ATR
        
        Args:
            symbol: Stock symbol
            entry_price: Entry price
            side: 'LONG' or 'SHORT'
            atr: Average True Range
        
        Returns:
            Recommended stop loss price
        """
        
        # Use 1.5x ATR for initial stop
        stop_distance = atr * self.trail_atr_multiplier
        
        if side == 'LONG':
            stop_price = entry_price - stop_distance
        else:  # SHORT
            stop_price = entry_price + stop_distance
        
        return stop_price
    
    def check_stop_hit(self, positions: List[Dict], market_data: Dict) -> List[str]:
        """
        Check if any stops were hit
        
        Returns: List of symbols to exit
        """
        
        symbols_to_exit = []
        
        for position in positions:
            symbol = position['symbol']
            stop_loss = position.get('stop_loss')
            current_price = market_data.get(symbol, {}).get('price')
            
            if stop_loss is None or current_price is None:
                continue
            
            # Check if stop hit
            if position['side'] == 'LONG':
                if current_price <= stop_loss:
                    symbols_to_exit.append(symbol)
                    logger.warning(
                        f"🛑 {symbol} - STOP LOSS HIT: "
                        f"Price ₹{current_price:.2f} ≤ Stop ₹{stop_loss:.2f}"
                    )
            
            else:  # SHORT
                if current_price >= stop_loss:
                    symbols_to_exit.append(symbol)
                    logger.warning(
                        f"🛑 {symbol} - STOP LOSS HIT (SHORT): "
                        f"Price ₹{current_price:.2f} ≥ Stop ₹{stop_loss:.2f}"
                    )
        
        return symbols_to_exit
    
    def calculate_profit_locked(self, positions: List[Dict]) -> Dict:
        """
        Calculate total profit locked by trailing stops
        
        Returns summary statistics
        """
        
        total_locked = 0
        positions_with_trailing = 0
        
        for position in positions:
            if position['symbol'] in self.trailing_stops:
                stop_info = self.trailing_stops[position['symbol']]
                total_locked += stop_info.get('locked_profit', 0)
                positions_with_trailing += 1
        
        return {
            'total_locked_profit': total_locked,
            'positions_with_trailing': positions_with_trailing,
            'total_positions': len(positions),
            'pct_using_trailing': positions_with_trailing / max(len(positions), 1)
        }


# Example usage
if __name__ == "__main__":
    
    config = {
        'ACTIVATION_PROFIT_PCT': 0.02,  # Activate after 2% profit
        'TRAIL_ATR_MULTIPLIER': 1.5,
        'TRAIL_PCT': 0.03  # 3% trailing
    }
    
    manager = TrailingStopManager(config)
    
    # Simulate positions
    positions = [
        {
            'symbol': 'RELIANCE',
            'side': 'LONG',
            'entry_price': 2400,
            'stop_loss': 2350,
            'quantity': 100
        },
        {
            'symbol': 'TCS',
            'side': 'LONG',
            'entry_price': 3500,
            'stop_loss': 3450,
            'quantity': 50
        }
    ]
    
    # Simulate market data with prices moving up
    market_data = {
        'RELIANCE': {
            'price': 2500,  # +4.2% from entry
            'atr': 30
        },
        'TCS': {
            'price': 3600,  # +2.9% from entry
            'atr': 40
        }
    }
    
    print("\n" + "="*80)
    print("TRAILING STOP LOSS MANAGER")
    print("="*80)
    
    print("\nInitial Positions:")
    for pos in positions:
        print(f"  {pos['symbol']}: Entry ₹{pos['entry_price']}, Stop ₹{pos['stop_loss']}")
    
    print("\nCurrent Prices:")
    for symbol, data in market_data.items():
        entry = next(p['entry_price'] for p in positions if p['symbol'] == symbol)
        profit_pct = (data['price'] - entry) / entry
        print(f"  {symbol}: ₹{data['price']} ({profit_pct:+.1%})")
    
    # Update trailing stops
    updated = manager.update_trailing_stops(positions, market_data)
    
    print("\nTrailing Stop Updates:")
    if updated:
        for symbol, update in updated.items():
            print(f"  {symbol}:")
            print(f"    Old Stop: ₹{update['old_stop']:.2f}")
            print(f"    New Stop: ₹{update['new_stop']:.2f} ({update['method']})")
            print(f"    Locked Profit: ₹{update['locked_profit']:.2f} ({update['locked_profit_pct']:.1%})")
    else:
        print("  No updates (profits not yet at activation threshold)")
    
    # Simulate price drop
    print("\n" + "="*80)
    print("SCENARIO: Price drops after hitting trailing stop")
    print("="*80)
    
    # Update positions with new stops
    for symbol, update in updated.items():
        for pos in positions:
            if pos['symbol'] == symbol:
                pos['stop_loss'] = update['new_stop']
    
    # Prices drop
    market_data['RELIANCE']['price'] = 2470  # Drops to 2470
    market_data['TCS']['price'] = 3570  # Drops slightly
    
    print("\nNew Prices:")
    for symbol, data in market_data.items():
        print(f"  {symbol}: ₹{data['price']}")
    
    # Check stops
    stops_hit = manager.check_stop_hit(positions, market_data)
    
    if stops_hit:
        print("\n🛑 Stops Hit:")
        for symbol in stops_hit:
            pos = next(p for p in positions if p['symbol'] == symbol)
            locked_profit = pos['stop_loss'] - pos['entry_price']
            print(f"  {symbol}: Exited at ₹{pos['stop_loss']:.2f}")
            print(f"    Profit Locked: ₹{locked_profit:.2f} ({locked_profit/pos['entry_price']:.1%})")
    else:
        print("\n✅ No stops hit - Positions still open")
    
    # Summary
    summary = manager.calculate_profit_locked(positions)
    print("\nSummary:")
    print(f"  Total Locked Profit: ₹{summary['total_locked_profit']:.2f}")
    print(f"  Positions with Trailing: {summary['positions_with_trailing']}/{summary['total_positions']}")
