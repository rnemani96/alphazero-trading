
import sys, os, time, logging
from datetime import datetime, timedelta

# Project Root
ROOT = os.getcwd()
sys.path.append(ROOT)

from src.data.fetch import DataFetcher
from src.backtest.engine import BacktestEngine
from src.event_bus.event_bus import EventBus, EventType, Event
from src.agents.lens_agent import LensAgent
from src.agents.karma_agent import KarmaAgent

# Configure logging to stdout and a file
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s', stream=sys.stdout)
logger = logging.getLogger("VERIFY")

log_file = os.path.join(ROOT, "verification_log.txt")
file_handler = logging.FileHandler(log_file, mode='w')
file_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(file_handler)

def print_header(title):
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)
    sys.stdout.flush()

def test_data():
    print_header("1. DATA: nsepython integration")
    fetcher = DataFetcher(mode='PAPER')
    symbol = "RELIANCE"
    logger.info(f"Fetching live quote for {symbol}...")
    quote = fetcher.get_market_data(symbol)
    if quote:
        logger.info(f"✅ Quote SUCCESS: {symbol} @ {quote.get('price')} (Source: {quote.get('source')})")
    else:
        logger.error("❌ Quote FAILED")
    
    logger.info(f"Fetching OHLCV for {symbol}...")
    hist = fetcher.get_ohlcv(symbol, interval='1d', bars=5)
    if hist:
        logger.info(f"✅ History SUCCESS: {len(hist)} bars retrieved")
    else:
        logger.error("❌ History FAILED")
    sys.stdout.flush()

def test_backtest():
    print_header("2. BACKTEST: Engine Simulation")
    try:
        from src.backtest.engine import BacktestEngine
        engine = BacktestEngine(initial_capital=1000000)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=10)
        symbols = ['RELIANCE']
        
        logger.info(f"Running 10-day backtest for {symbols}...")
        results = engine.run(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'), symbols)
        
        if results and 'metrics' in results:
            m = results['metrics']
            logger.info(f"✅ Backtest SUCCESS: Total Return {m.get('cumulative_return',0)*100:.2f}%")
            logger.info(f"   Trades: {results.get('trade_stats',{}).get('total_trades',0)}")
        else:
            logger.error("❌ Backtest FAILED (check if date range has data)")
    except Exception as e:
        logger.error(f"❌ Backtest engine error: {e}")
    sys.stdout.flush()

def test_rl_loop():
    print_header("3. RL LOOP: LENS -> KARMA Feedback")
    eb = EventBus()
    eb.start()
    
    try:
        lens = LensAgent(eb, {})
        karma = KarmaAgent(eb, {})
        
        logger.info("Publishing SIGNAL_GENERATED event...")
        eb.publish(Event(
            type=EventType.SIGNAL_GENERATED,
            source_agent='TITAN',
            payload={
                'symbol': 'TCS', 'action': 'BUY', 'confidence': 0.9,
                'source': 'TITAN', 'price': 3000.0, 'stop_loss': 2950.0, 'target': 3100.0
            }
        ))
        
        time.sleep(1)
        logger.info(f"Evaluator pending: {len(lens.evaluator._pending)}")
        
        logger.info("Injecting price update (Target HIT)...")
        lens.update_prices({'TCS': 3150.0})
        
        ep_before = karma.learning_episodes
        lens.update()
        time.sleep(1)
        ep_after = karma.learning_episodes
        
        logger.info(f"Karma reinforcement episodes: {ep_before} -> {ep_after}")
        if ep_after > ep_before:
            logger.info("✅ SUCCESS: KARMA learned from LENS outcome")
        else:
            logger.error("❌ FAILURE: Feedback loop broken")
    except Exception as e:
        logger.error(f"❌ RL Loop error: {e}")
    finally:
        eb.stop()
    sys.stdout.flush()

if __name__ == "__main__":
    print("ALPHAZERO SYSTEM VERIFICATION")
    try:
        test_data()
        test_backtest()
        test_rl_loop()
        print("\n" + "!"*60)
        print(" ALL TESTS COMPLETED ")
        print("!"*60)
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    sys.stdout.flush()
