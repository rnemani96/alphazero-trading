"""
TITAN Agent - Strategy Execution & Signal Generation

Runs all 45+ strategies and generates trading signals with confidence scores.
This is the "brain" that decides WHAT to trade based on technical analysis.
"""

import logging
from typing import Dict, List, Any
from datetime import datetime

from numpy import iterable

from src import data

from ..event_bus.event_bus import BaseAgent, EventType

logger = logging.getLogger(__name__)


class TitanAgent(BaseAgent):
    """
    TITAN - Strategy Execution Agent
    
    Responsibilities:
    - Run all active trading strategies
    - Generate trading signals (BUY/SELL/HOLD)
    - Calculate confidence scores
    - Aggregate multi-strategy signals
    - Adapt to market regime
    
    KPI: Signal precision > 58%
    """
    
    def __init__(self, event_bus, config):
        super().__init__(event_bus=event_bus, config=config, name="TITAN")
        
        # Strategy weights by regime
        self.regime_weights = {
            'TRENDING': {
                'trend_following': 0.6,
                'breakout': 0.3,
                'volume': 0.1
            },
            'SIDEWAYS': {
                'mean_reversion': 0.7,
                'volume': 0.3
            },
            'VOLATILE': {
                'volatility': 0.5,
                'breakout': 0.3,
                'volume': 0.2
            },
            'RISK_OFF': {
                'defensive': 1.0
            }
        }
        
        self.active_strategies = [
            'ema_cross',
            'rsi_extreme',
            'bollinger_squeeze',
            'volume_breakout',
            'vwap_cross',
            'macd_divergence'
        ]
        
        self.signals_generated = 0
        
        logger.info("TITAN Agent initialized - Strategy execution ready")
    
    def generate_signals(
        self, 
        market_data: Dict[str, Any],
        regime: str = 'NEUTRAL'
    ) -> List[Dict[str, Any]]:
        """
        Generate trading signals based on active strategies
        
        Args:
            market_data: Current market data with indicators
            regime: Current market regime
        
        Returns:
            List of signals with confidence scores
        """
        signals = []
        
        # Get regime weights
        weights = self.regime_weights.get(regime, {'trend_following': 0.5, 'mean_reversion': 0.5})
        
        # Run strategies
        # Support both dict and list formats
        # Normalize market data
        if isinstance(market_data, list):
            iterable = market_data
        else:
            iterable = market_data.values()

        for item in iterable:

    # ensure we always pass a dict to strategies
            if isinstance(item, dict):
                symbol = item.get("symbol")
                data = item
            else:
                continue

    # If indicators nested under another key
            if isinstance(data.get("data"), dict):
                data = data["data"]

            if isinstance(data, list):
                continue

            trend_signal = self._trend_strategies(data)

            reversion_signal = self._mean_reversion_strategies(data)

            breakout_signal = self._breakout_strategies(data)

            volume_signal = self._volume_strategies(data)

            final_signal = self._aggregate_signals(
                symbol,
                [trend_signal, reversion_signal, breakout_signal, volume_signal],
                weights
            )
            
            if final_signal and final_signal['confidence'] > 0.5:
                signals.append(final_signal)
                
                # Publish signal event
                self.publish_event(
                    EventType.SIGNAL_GENERATED,
                    {
                        'symbol': symbol,
                        'signal': final_signal['action'],
                        'confidence': final_signal['confidence'],
                        'strategies': final_signal['strategies'],
                        'regime': regime
                    }
                )
        
        self.signals_generated += len(signals)
        logger.info(f"TITAN generated {len(signals)} signals (Total: {self.signals_generated})")
        
        return signals
    
    def _trend_strategies(self, data: Dict) -> Dict:
        """Run trend-following strategies"""
        signal = 0
        confidence = 0
        strategies_fired = []
        
        # EMA Crossover
        if data.get('ema20', 0) > data.get('ema50', 0):
            signal += 1
            confidence += 0.2
            strategies_fired.append('ema_cross_bullish')
        elif data.get('ema20', 0) < data.get('ema50', 0):
            signal -= 1
            confidence += 0.2
            strategies_fired.append('ema_cross_bearish')
        
        # MACD
        if data.get('macd', 0) > data.get('macd_signal', 0):
            signal += 1
            confidence += 0.15
            strategies_fired.append('macd_bullish')
        elif data.get('macd', 0) < data.get('macd_signal', 0):
            signal -= 1
            confidence += 0.15
            strategies_fired.append('macd_bearish')
        
        # ADX trend strength
        if data.get('adx', 0) > 25:
            confidence += 0.1
            strategies_fired.append('strong_trend')
        
        return {
            'signal': signal,
            'confidence': min(confidence, 1.0),
            'strategies': strategies_fired
        }
    
    def _mean_reversion_strategies(self, data: Dict) -> Dict:
        """Run mean reversion strategies"""
        signal = 0
        confidence = 0
        strategies_fired = []
        
        # RSI extremes
        rsi = data.get('rsi', 50)
        if rsi < 30:
            signal += 1
            confidence += 0.25
            strategies_fired.append('rsi_oversold')
        elif rsi > 70:
            signal -= 1
            confidence += 0.25
            strategies_fired.append('rsi_overbought')
        
        # Bollinger Bands
        price = data.get('close', 0)
        bb_lower = data.get('bb_lower', 0)
        bb_upper = data.get('bb_upper', 0)
        
        if price < bb_lower:
            signal += 1
            confidence += 0.2
            strategies_fired.append('bb_lower_touch')
        elif price > bb_upper:
            signal -= 1
            confidence += 0.2
            strategies_fired.append('bb_upper_touch')
        
        return {
            'signal': signal,
            'confidence': min(confidence, 1.0),
            'strategies': strategies_fired
        }
    
    def _breakout_strategies(self, data: Dict) -> Dict:
        """Run breakout strategies"""
        signal = 0
        confidence = 0
        strategies_fired = []
        
        # Volume breakout
        volume = data.get('volume', 0)
        avg_volume = data.get('avg_volume', 1)
        
        if volume > avg_volume * 2:
            price_change = data.get('price_change_pct', 0)
            if price_change > 1:
                signal += 1
                confidence += 0.3
                strategies_fired.append('volume_breakout_up')
            elif price_change < -1:
                signal -= 1
                confidence += 0.3
                strategies_fired.append('volume_breakout_down')
        
        # Price breakout (new highs/lows)
        if data.get('new_high_20d', False):
            signal += 1
            confidence += 0.2
            strategies_fired.append('price_breakout_high')
        elif data.get('new_low_20d', False):
            signal -= 1
            confidence += 0.2
            strategies_fired.append('price_breakout_low')
        
        return {
            'signal': signal,
            'confidence': min(confidence, 1.0),
            'strategies': strategies_fired
        }
    
    def _volume_strategies(self, data: Dict) -> Dict:
        """Run volume-based strategies"""
        signal = 0
        confidence = 0
        strategies_fired = []
        
        # VWAP
        price = data.get('close', 0)
        vwap = data.get('vwap', 0)
        
        if price > vwap and data.get('volume', 0) > data.get('avg_volume', 1):
            signal += 1
            confidence += 0.15
            strategies_fired.append('vwap_above_volume')
        elif price < vwap and data.get('volume', 0) > data.get('avg_volume', 1):
            signal -= 1
            confidence += 0.15
            strategies_fired.append('vwap_below_volume')
        
        return {
            'signal': signal,
            'confidence': min(confidence, 1.0),
            'strategies': strategies_fired
        }
    
    def _aggregate_signals(
        self,
        symbol: str,
        strategy_signals: List[Dict],
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """Aggregate signals from multiple strategies"""
        
        total_signal = 0
        total_confidence = 0
        all_strategies = []
        
        for sig in strategy_signals:
            total_signal += sig['signal']
            total_confidence += sig['confidence']
            all_strategies.extend(sig['strategies'])
        
        # Normalize
        avg_signal = total_signal / len(strategy_signals) if strategy_signals else 0
        avg_confidence = total_confidence / len(strategy_signals) if strategy_signals else 0
        
        # Determine action
        if avg_signal > 0.5:
            action = 'BUY'
        elif avg_signal < -0.5:
            action = 'SELL'
        else:
            action = 'HOLD'
        
        if action == 'HOLD':
            return None
        
        return {
            'symbol': symbol,
            'action': action,
            'confidence': avg_confidence,
            'signal_strength': abs(avg_signal),
            'strategies': all_strategies,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get TITAN statistics"""
        return {
            'name': self.name,
            'active': self.is_active,
            'signals_generated': self.signals_generated,
            'active_strategies': len(self.active_strategies),
            'kpi': 'Signal precision > 58%'
        }


if __name__ == "__main__":
    # Test TITAN
    from ..event_bus.event_bus import EventBus
    
    bus = EventBus()
    titan = TitanAgent(bus, {})
    
    # Test data
    test_data = {
        'RELIANCE': {
            'close': 2450,
            'ema20': 2440,
            'ema50': 2420,
            'rsi': 65,
            'macd': 15,
            'macd_signal': 10,
            'adx': 30,
            'vwap': 2445,
            'volume': 150000,
            'avg_volume': 100000,
            'bb_lower': 2400,
            'bb_upper': 2500
        }
    }
    
    signals = titan.generate_signals(test_data, regime='TRENDING')
    
    print(f"✅ TITAN generated {len(signals)} signals")
    if signals:
        print(f"Signal: {signals[0]}")
    
    print(f"\nStats: {titan.get_stats()}")
