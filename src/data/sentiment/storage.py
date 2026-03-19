"""
src/data/sentiment/storage.py  —  AlphaZero Capital
══════════════════════════════════════════════════
Handles persistent Parquet storage and daily metric aggregation.
Calculates sentiment momentum, volatility, and volume features.
"""

import os, logging, pandas as pd, numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger("SentimentStorage")

STORAGE_DIR = "data/sentiment"
os.makedirs(STORAGE_DIR, exist_ok=True)

class SentimentStorage:
    def __init__(self, storage_dir: str = STORAGE_DIR):
        self.storage_dir = storage_dir

    def save_headlines(self, headlines: List[Dict[str, Any]]):
        """Saves processed headlines to a daily Parquet file."""
        if not headlines: return
        
        df = pd.DataFrame(headlines)
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df['date'] = df['timestamp'].dt.date
        
        # Save by date to avoid massive files
        for date, group in df.groupby('date'):
            fname = os.path.join(self.storage_dir, f"sentiment_{date}.parquet")
            if os.path.exists(fname):
                try:
                    existing = pd.read_parquet(fname)
                    # Deduplicate by headline hash (if present) or headline text
                    group = pd.concat([existing, group]).drop_duplicates(subset=['headline'])
                except Exception as e:
                    logger.debug(f"Error merging with existing Parquet: {e}")
            group.to_parquet(fname, index=False)

    def load_recent_sentiment(self, days: int = 7) -> pd.DataFrame:
        """Loads sentiment data from the last 'days'."""
        all_dfs = []
        end_date = datetime.now().date()
        for i in range(days + 1):
            date = end_date - timedelta(days=i)
            fname = os.path.join(self.storage_dir, f"sentiment_{date}.parquet")
            if os.path.exists(fname):
                try:
                    all_dfs.append(pd.read_parquet(fname))
                except Exception: pass
        
        if not all_dfs: return pd.DataFrame()
        return pd.concat(all_dfs).sort_values('timestamp')

class SentimentAggregator:
    def __init__(self, storage: SentimentStorage):
        self.storage = storage

    def compute_daily_metrics(self) -> Dict[str, Any]:
        """Calculates daily sentiment score, volatility, and momentum."""
        df = self.storage.load_recent_sentiment(days=7)
        if df.empty: return {}

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        today = datetime.now().date()
        
        # Filter for today's news
        today_df = df[df['timestamp'].dt.date == today]
        if today_df.empty:
            # If no data for today, use the most recent day in the DF
            latest_date = df['timestamp'].dt.date.max()
            today_df = df[df['timestamp'].dt.date == latest_date]

        # 1. Base Sentiment (Weighted by source reliability/confidence)
        if 'weight' not in today_df.columns: today_df['weight'] = 1.0
        if 'sentiment_conf' not in today_df.columns: today_df['sentiment_conf'] = 1.0
        
        total_weight = (today_df['weight'] * today_df['sentiment_conf']).sum()
        weighted_score = (today_df['sentiment_score'] * today_df['weight'] * today_df['sentiment_conf']).sum() / max(total_weight, 1e-6)

        # 2. Ratios
        pos_count = len(today_df[today_df['sentiment_score'] > 0.15])
        neg_count = len(today_df[today_df['sentiment_score'] < -0.15])
        total_count = len(today_df)
        
        pos_ratio = pos_count / max(total_count, 1)
        neg_ratio = neg_count / max(total_count, 1)

        # 3. Volatility (stdev over last 5 days)
        daily_means = df.groupby(df['timestamp'].dt.date)['sentiment_score'].mean()
        volatility = daily_means.tail(5).std() if len(daily_means) >= 2 else 0.0

        # 4. Momentum (Today vs rolling mean of last 3 days)
        prev_mean = daily_means.iloc[:-1].tail(3).mean() if len(daily_means) >= 2 else 0.0
        momentum = weighted_score - prev_mean

        # 5. Extreme Sentiment Flag
        extreme_flag = 1 if abs(weighted_score) > 0.4 or (pos_ratio > 0.7 or neg_ratio > 0.7) else 0

        return {
            'sentiment_score': round(float(weighted_score), 4),
            'sentiment_volatility': round(float(volatility), 4),
            'sentiment_momentum': round(float(momentum), 4),
            'sentiment_pos_ratio': round(pos_ratio, 4),
            'sentiment_neg_ratio': round(neg_ratio, 4),
            'news_volume': total_count,
            'extreme_sentiment_flag': extreme_flag,
            'timestamp': datetime.now().isoformat()
        }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    storage = SentimentStorage()
    aggregator = SentimentAggregator(storage)
    metrics = aggregator.compute_daily_metrics()
    print(f"Daily Metrics: {metrics}")
