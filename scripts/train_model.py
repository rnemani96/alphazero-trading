"""
AlphaZero Capital - ML Model Training Script (8+ Months Data)
scripts/train_model.py

Downloads 8+ months of historical data for NIFTY 50 top stocks, 
computes technical indicators, and trains a predictive Machine Learning model.
"""

import os
import sys
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf
import pickle

# Setup paths
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from src.data.indicators import add_all_indicators

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TrainML")

# Fetch top liquid stocks from dynamic universe
from src.data.universe import get_nifty500_symbols
TRAIN_SYMBOLS = get_nifty500_symbols()[:30] # Top 30 for training efficiency


def fetch_historical_data(symbols, months=8):
    """Fetch 'months' of daily historical data using yfinance."""
    logger.info(f"Fetching {months} months of historical data for {len(symbols)} symbols...")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30 * months)
    
    all_data = []
    
    for sym in symbols:
        try:
            logger.info(f"Downloading {sym}...")
            df = yf.download(sym, start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"), progress=False)
            
            if len(df) < 50:
                logger.warning(f"Not enough data for {sym}. Skipping...")
                continue
                
            # Handle multi-index columns from newer yfinance
            if isinstance(df.columns, pd.MultiIndex):
                # Flatten MultiIndex to simple column names
                df.columns = [col[0] for col in df.columns]

            # Normalize columns for the indicator engine
            df.columns = [str(c).lower() for c in df.columns]
            
            if 'close' not in df.columns:
                continue

            # Target: 1 if next day closes higher, 0 otherwise
            df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
            
            # Compute technical indicators
            df = add_all_indicators(df)
            
            # Drop NaN rows due to indicators and the last row missing the target
            df.dropna(inplace=True)
            
            df['symbol'] = sym
            all_data.append(df)
            
        except Exception as e:
            logger.error(f"Failed to fetch data for {sym}: {e}")

    if not all_data:
        raise ValueError("No data could be fetched.")
        
    final_df = pd.concat(all_data, ignore_index=True)
    logger.info(f"Data fetching complete. Total samples: {len(final_df)}")
    return final_df

def train_model(df):
    """Train a machine learning model on the extracted features."""
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report, accuracy_score
    except ImportError:
        logger.error("scikit-learn not installed. Please run `pip install scikit-learn` to train this model.")
        return None

    # Features to use for training (excluding target and metadata)
    drop_cols = ['open', 'high', 'low', 'close', 'volume', 'target', 'symbol', 'date', 'datetime']
    features = [c for c in df.columns if c not in drop_cols and np.issubdtype(df[c].dtype, np.number)]
    
    logger.info(f"Training using {len(features)} features...")
    
    X = df[features]
    y = df['target']
    
    # Split chronologically or randomly
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    model = RandomForestClassifier(n_estimators=100, max_depth=8, min_samples_split=10, random_state=42, n_jobs=-1)
    
    logger.info("Fitting Random Forest model...")
    model.fit(X_train, y_train)
    
    # Evaluate
    preds = model.predict(X_test)
    acc = accuracy_score(y_test, preds)
    logger.info(f"Validation Accuracy: {acc*100:.2f}%")
    logger.info("\n" + classification_report(y_test, preds))
    
    return model, features

def save_model(model, features, filename="alpha_signal_rf.pkl"):
    """Save the trained model and its feature specification."""
    models_dir = os.path.join(ROOT_DIR, "models")
    os.makedirs(models_dir, exist_ok=True)
    
    filepath = os.path.join(models_dir, filename)
    with open(filepath, 'wb') as f:
        pickle.dump({"model": model, "features": features}, f)
        
    logger.info(f"Model successfully saved to {filepath}")

def main():
    logger.info("=== AlphaZero Model Training Pipeline ===")
    try:
        df = fetch_historical_data(TRAIN_SYMBOLS, months=8)
        model_data = train_model(df)
        if model_data:
            model, features = model_data
            save_model(model, features)
    except Exception as e:
        logger.error(f"Training pipeline failed: {e}")

if __name__ == "__main__":
    main()
