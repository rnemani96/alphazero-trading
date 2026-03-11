"""
AlphaZero Capital v18 - Multi-Timeframe Confirmation Agent
src/agents/multi_timeframe_agent.py
"""

import numpy as np
import time
from datetime import datetime
from typing import Dict
import logging

from ..event_bus.event_bus import BaseAgent, EventBus, Event, EventType

logger = logging.getLogger(__name__)


class MultiTimeframeAgent(BaseAgent):

    TIMEFRAMES = ['1min', '5min', '15min', '1h', '1D']

    def __init__(self, event_bus: EventBus, config: Dict, data_fetcher=None):
        super().__init__(event_bus=event_bus, config=config, name="MULTI_TIMEFRAME")

        self.config = config
        self.data_fetcher = data_fetcher

        # guards
        self.last_signal = {}
        self.last_run = {}

        self.subscribe(EventType.SIGNAL_GENERATED, self.on_signal)

        logger.info("MULTI_TIMEFRAME Agent initialized")

    # ─────────────────────────────────────────────────────────────

    def on_signal(self, event: Event):

        symbol = event.payload.get('symbol')
        source = event.payload.get('source')

        if not symbol:
            return

        # 1️⃣ prevent recursive loop
        if source == "MULTI_TIMEFRAME":
            return

        # 2️⃣ throttle execution
        now = time.time()
        if now - self.last_run.get(symbol, 0) < 10:
            return
        self.last_run[symbol] = now

        mtf_result = self.check_timeframe_alignment(symbol)

        final_signal = mtf_result['final_signal']

        if final_signal not in ('STRONG_BUY', 'BUY', 'STRONG_SELL', 'SELL'):
            return

        # 3️⃣ prevent duplicate signals
        if self.last_signal.get(symbol) == final_signal:
            return

        self.last_signal[symbol] = final_signal

        # 4️⃣ publish confirmed signal
        self.publish_event(
            EventType.SIGNAL_CONFIRMED,
            {
                'symbol': symbol,
                'signal': final_signal,
                'confidence': mtf_result['confidence'],
                'source': 'MULTI_TIMEFRAME',
                'mtf_confirmed': True,
                'timeframe_signals': mtf_result['timeframe_signals'],
                'timestamp': datetime.now().isoformat(),
            }
        )

    # ─────────────────────────────────────────────────────────────

    def check_timeframe_alignment(self, symbol: str) -> Dict:

        signals = {}

        for tf in self.TIMEFRAMES:
            signals[tf] = self.get_signal_for_timeframe(symbol, tf)

        buy_votes = sum(1 for s in signals.values() if s == 'BUY')
        sell_votes = sum(1 for s in signals.values() if s == 'SELL')
        hold_votes = sum(1 for s in signals.values() if s == 'HOLD')

        total = len(self.TIMEFRAMES)

        if buy_votes >= 4:
            final_signal = 'STRONG_BUY'
            conf = buy_votes / total

        elif buy_votes == 3:
            final_signal = 'BUY'
            conf = buy_votes / total

        elif sell_votes >= 4:
            final_signal = 'STRONG_SELL'
            conf = sell_votes / total

        elif sell_votes == 3:
            final_signal = 'SELL'
            conf = sell_votes / total

        else:
            final_signal = 'HOLD'
            conf = hold_votes / total

        if final_signal in ('STRONG_BUY', 'STRONG_SELL'):
            votes = buy_votes if 'BUY' in final_signal else sell_votes
            logger.info(f"✅ {symbol} MTF ALIGNED: {final_signal} ({votes}/{total})")

        return {
            'symbol': symbol,
            'final_signal': final_signal,
            'confidence': conf,
            'timeframe_signals': signals
        }

    # ─────────────────────────────────────────────────────────────

    def get_signal_for_timeframe(self, symbol: str, timeframe: str):

        candles = self.get_candle_data(symbol, timeframe, 100)

        if candles is None or len(candles) < 50:
            return 'HOLD'

        close = candles['close']

        ema20 = self.calculate_ema(close, 20)
        ema50 = self.calculate_ema(close, 50)

        rsi = self.calculate_rsi(close)
        macd, signal = self.calculate_macd(close)

        price = close.iloc[-1]

        trend = 'BUY' if ema20.iloc[-1] > ema50.iloc[-1] else 'SELL'
        price_sig = 'BUY' if price > ema20.iloc[-1] else 'SELL'
        macd_sig = 'BUY' if macd.iloc[-1] > signal.iloc[-1] else 'SELL'

        rsi_val = rsi.iloc[-1]

        if rsi_val < 30:
            momentum = 'BUY'
        elif rsi_val > 70:
            momentum = 'SELL'
        else:
            momentum = 'NEUTRAL'

        sigs = [trend, price_sig, macd_sig]

        if momentum != 'NEUTRAL':
            sigs.append(momentum)

        if sigs.count('BUY') > sigs.count('SELL'):
            return 'BUY'
        elif sigs.count('SELL') > sigs.count('BUY'):
            return 'SELL'
        else:
            return 'HOLD'

    # ─────────────────────────────────────────────────────────────

    def get_candle_data(self, symbol, timeframe, periods):

        import pandas as pd

        if self.data_fetcher:
            try:
                candles = self.data_fetcher.get_ohlcv(
                    symbol,
                    interval=timeframe,
                    bars=periods
                )
                if candles:
                    return pd.DataFrame(candles)
            except Exception as e:
                logger.debug(f"MTF fetch failed {symbol} {timeframe}: {e}")

        # Final return if no data found
        return None

    # ─────────────────────────────────────────────────────────────

    def calculate_ema(self, series, period):
        return series.ewm(span=period, adjust=False).mean()

    def calculate_rsi(self, series, period=14):

        delta = series.diff()

        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()

        rs = gain / loss.replace(0, 1e-9)

        return 100 - (100 / (1 + rs))

    def calculate_macd(self, series):

        ema12 = series.ewm(span=12, adjust=False).mean()
        ema26 = series.ewm(span=26, adjust=False).mean()

        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()

        return macd, signal