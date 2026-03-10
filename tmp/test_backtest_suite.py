
import sys
import os
import logging
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.getcwd())

from src.backtest.engine import BacktestEngine
from src.backtest.forward_walk import ForwardWalk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VERIFY_BACKTEST")

def test_engine():
    logger.info("Initializing BacktestEngine...")
    engine = BacktestEngine(initial_capital=1000000)
    
    # Test symbols (small subset for speed)
    symbols = ['RELIANCE', 'TCS', 'INFY']
    
    # Dates
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    logger.info(f"Running engine test for {symbols} from {start_date.date()} to {end_date.date()}")
    
    results = engine.run(
        start_date.strftime('%Y-%m-%d'),
        end_date.strftime('%Y-%m-%d'),
        symbols
    )
    
    if results and 'metrics' in results:
        logger.info(f"Backtest SUCCESS: Returns={results['metrics'].get('cumulative_return')}, Sharpe={results['metrics'].get('sharpe')}")
        logger.info(f"Trade Stats: {results.get('trade_stats')}")
    else:
        logger.error("Backtest FAILED or NO DATA")

def test_forward_walk():
    logger.info("\nInitializing ForwardWalk...")
    engine = BacktestEngine(initial_capital=1000000)
    fw = ForwardWalk(engine)
    
    symbols = ['RELIANCE']
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)
    
    logger.info(f"Running Forward Walk test for {symbols} over 90 days")
    
    # 30 day train, 15 day test, 15 day step
    fw_results = fw.run(
        start_date.strftime('%Y-%m-%d'),
        end_date.strftime('%Y-%m-%d'),
        symbols,
        train_days=30,
        test_days=15,
        step_days=15
    )
    
    summary = fw.get_summary()
    logger.info(f"Forward Walk Summary: {summary}")

if __name__ == "__main__":
    try:
        test_engine()
        # test_forward_walk() # Skip for now to save time unless needed
    except Exception as e:
        logger.error(f"Verification FAILED: {e}")
        import traceback
        traceback.print_exc()
