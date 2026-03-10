
import sys
import os
import logging
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

from src.data.fetch import DataFetcher
from src.data.market_data import MarketDataEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TEST_MIGRATION")

def test_fetcher():
    logger.info("Testing DataFetcher (src/data/fetch.py)...")
    fetcher = DataFetcher(mode='PAPER')
    
    # Test quote
    symbol = "RELIANCE"
    logger.info(f"Fetching quote for {symbol}...")
    quote = fetcher.get_market_data(symbol)
    if quote:
        logger.info(f"Quote SUCCESS: Price={quote.get('price')}, Source={quote.get('source')}")
    else:
        logger.error("Quote FAILED")

    # Test history
    logger.info(f"Fetching history for {symbol}...")
    hist = fetcher.get_ohlcv(symbol, interval='1d', bars=5)
    if hist:
        logger.info(f"History SUCCESS: {len(hist)} bars, Source={fetcher._fetch_ohlcv_real(symbol, '1d', 1)[0].get('source', 'unknown') if fetcher._fetch_ohlcv_real(symbol, '1d', 1) else 'unknown'}")
    else:
        logger.error("History FAILED")

def test_market_data():
    logger.info("\nTesting MarketDataEngine (src/data/market_data.py)...")
    engine = MarketDataEngine()
    
    # Test Index / VIX
    logger.info("Fetching Nifty/VIX...")
    nifty, bnk, vix = engine.get_nifty_vix()
    logger.info(f"Indices SUCCESS: Nifty={nifty}, BankNifty={bnk}, VIX={vix}")

def test_oracle():
    logger.info("\nTesting OracleAgent (src/agents/oracle_agent.py)...")
    from src.agents.oracle_agent import OracleAgent
    oracle = OracleAgent(None, {})
    
    stats = oracle.get_stats()
    logger.info(f"Oracle Stats: {stats}")

if __name__ == "__main__":
    try:
        test_fetcher()
        test_market_data()
        test_oracle()
    except Exception as e:
        logger.error(f"Migration test failed: {e}")
