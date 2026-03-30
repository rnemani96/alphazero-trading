@echo off
echo Testing Capital Sync and Universe Selection... > test_confirmation.log
echo Environment Capital: >> test_confirmation.log
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('INITIAL_CAPITAL'))" >> test_confirmation.log 2>&1
echo Universe Selection Check: >> test_confirmation.log
python -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path.cwd())); from scripts.train_full_history_v4 import select_training_universe; from src.data.market_data import DataFetcher; f=DataFetcher({'MODE':'PAPER'}); s=select_training_universe(f); print(f'Selection OK: {len(s)} symbols')" >> test_confirmation.log 2>&1
echo Done. >> test_confirmation.log
