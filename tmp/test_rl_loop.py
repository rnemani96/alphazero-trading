
import sys
import os
import time
import logging
from datetime import datetime
from dataclasses import asdict

# Add project root to path
sys.path.append(os.getcwd())

from src.event_bus.event_bus import EventBus, EventType
from src.agents.lens_agent import LensAgent
from src.agents.karma_agent import KarmaAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VERIFY_RL_LOOP")

def test_rl_loop():
    eb = EventBus()
    eb.start()
    
    cfg = {}
    lens = LensAgent(eb, cfg)
    karma = KarmaAgent(eb, cfg)
    
    from src.event_bus.event_bus import Event
    # 1. Simulate a signal generation
    logger.info("Step 1: Publishing SIGNAL_GENERATED event...")
    eb.publish(
        Event(
            type=EventType.SIGNAL_GENERATED,
            source_agent='TITAN',
            payload={
                'symbol': 'RELIANCE',
                'action': 'BUY',
                'confidence': 0.8,
                'source': 'TITAN',
                'price': 2400.0,
                'stop_loss': 2350.0,
                'target': 2500.0,
                'regime': 'TRENDING'
            }
        )
    )
    
    # Observe Lens logs it
    time.sleep(1)
    logger.info(f"Lens pending evaluations: {len(lens.evaluator._pending)}")
    
    # 2. Update prices to trigger evaluation
    logger.info("Step 2: Updating prices to trigger HIT (Target at 2500)...")
    lens.update_prices({'RELIANCE': 2510.0})
    
    # Capture karma episodes before update
    ep_before = karma.learning_episodes
    
    # Trigger update
    lens.update()
    
    # Observe Karma learned
    time.sleep(1)
    ep_after = karma.learning_episodes
    
    logger.info(f"Karma episodes: {ep_before} -> {ep_after}")
    
    if ep_after > ep_before:
        logger.info("✅ SUCCESS: KARMA learned from LENS outcome!")
    else:
        logger.error("❌ FAILURE: KARMA did not receive evaluation event.")
    
    eb.stop()

if __name__ == "__main__":
    try:
        test_rl_loop()
    except Exception as e:
        logger.error(f"Verification FAILED: {e}")
        import traceback
        traceback.print_exc()
