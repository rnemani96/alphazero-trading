import os, sys, logging
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MiniTrainTest")

try:
    from scripts.train_full_history_v4 import HistoricalDeepTrainer
    # Mocking select_training_universe to just 2 stocks
    def mock_select(fetcher):
        return ["RELIANCE", "TCS"]
    
    import scripts.train_full_history_v4 as tfh
    tfh.select_training_universe = mock_select
    
    print("Initializing trainer...")
    trainer = HistoricalDeepTrainer()
    # Modify trainer config for mini run
    trainer.symbols = ["RELIANCE", "TCS"]
    trainer.timeframes = ["1d"]
    
    print("Starting mini sweep...")
    # I won't run full run_training_sweep because it's too long, 
    # but I'll see if we can get past initialization
    print(f"Trainer ready for symbols: {trainer.symbols}")
    
except Exception as e:
    import traceback
    traceback.print_exc()
