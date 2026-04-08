"""
BULK FEATURIZE - Catch-up Utility
scripts/bulk_featurize.py

Objective: Scan the data/cache/ohlcv directory and pre-compute 
all features for every stock. This ensures all historical data 
is 100% training-ready.
"""

import os, sys, logging
from pathlib import Path
import pandas as pd
from tqdm import tqdm

# Setup Paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data.indicators import add_all_indicators

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("Featurizer")

def main():
    raw_dir     = ROOT / "data" / "cache" / "ohlcv"
    ready_dir   = ROOT / "data" / "training_ready"
    ready_dir.mkdir(parents=True, exist_ok=True)
    
    files = list(raw_dir.glob("*.parquet"))
    logger.info(f"Scanning {len(files)} raw data files for feature engineering...")
    
    success_count = 0
    
    for f in tqdm(files):
        try:
            # 1. Parse symbol and timeframe from filename (RELIANCE_NS_1d.parquet)
            parts = f.stem.rsplit("_", 1)
            if len(parts) < 2: continue
            sym, tf = parts[0], parts[1]
            
            # 2. Load
            df = pd.read_parquet(f)
            if df.empty: continue
            
            # 3. Featurize
            df_feat = add_all_indicators(df)
            
            # 4. Save to tf-specific subdir
            tf_dir = ready_dir / tf
            tf_dir.mkdir(parents=True, exist_ok=True)
            df_feat.to_parquet(tf_dir / f"{sym}.parquet", index=False)
            
            success_count += 1
        except Exception as e:
            logger.error(f"Error processing {f.name}: {e}")
            
    logger.info(f"\nBulk Featurization Complete!")
    logger.info(f"Processed: {success_count} / {len(files)} files.")
    logger.info(f"Feature store located at: {ready_dir}")

if __name__ == "__main__":
    main()
