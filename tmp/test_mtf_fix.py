import pandas as pd
from datetime import datetime
import logging
from src.agents.multi_timeframe_agent import MultiTimeframeAgent
from src.event_bus.event_bus import EventBus, Event, EventType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TEST")

bus = EventBus()
agent = MultiTimeframeAgent(bus, {})

# Mock a signal event
payload = {
    'symbol': 'INFY',
    'signal': 'BUY',
    'confidence': 0.8,
    'source': 'TITAN'
}
event = Event(EventType.SIGNAL_GENERATED, payload)

print("Triggering on_signal in MultiTimeframeAgent...")
try:
    agent.on_signal(event)
    print("SUCCESS: on_signal completed without crash.")
except Exception as e:
    print(f"FAILED: on_signal crashed with: {e}")
    import traceback
    traceback.print_exc()
