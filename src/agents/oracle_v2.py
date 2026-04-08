"""
ORACLE V2 - LightGBM Specialized Predictor
src/agents/oracle_v2.py

An upgrade over the standard Oracle/Nexus models. 
Uses Gradient Boosting with GOSS (Gradient-based One-Side Sampling)
to identify rare high-profit breakout patterns.
"""

import logging
import os
import joblib
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional
from datetime import datetime

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

from .oracle_agent import OracleAgent

logger = logging.getLogger("ORACLE_V2")

class OracleV2Agent(OracleAgent):
    def __init__(self, event_bus, config):
        super().__init__(event_bus, config)
        self.name = "ORACLE_V2"
        self.model = None
        self.model_path = os.path.join("models", "oracle_v2_lgbm.txt")
        
        if lgb is None:
            logger.error("LightGBM not installed. ORACLE_V2 will be inactive.")
        
    def predict(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Produce a high-confidence trade prediction using LightGBM.
        """
        if self.model is None and os.path.exists(self.model_path):
            self._load_model()
            
        if self.model is None:
            # Fallback to base Oracle if V2 model not trained
            return super().predict(symbol, df)

        try:
            # Prepare features
            features = self._extract_features(df)
            if features is None:
                return {'symbol': symbol, 'confidence': 0.0, 'action': 'WAIT'}
            
            # LGBM Inference
            prob = self.model.predict(features.reshape(1, -1))[0]
            
            # Logic: LightGBM probability (Classification: 1=Profit > 1R)
            confidence = float(prob)
            action = "BUY" if confidence > 0.65 else "WAIT" # Conservative threshold
            
            return {
                'symbol': symbol,
                'confidence': confidence,
                'action': action,
                'model': 'LGBM_V2',
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"ORACLE_V2 predict failed for {symbol}: {e}")
            return {'symbol': symbol, 'confidence': 0.0, 'action': 'WAIT'}

    def _load_model(self):
        try:
            self.model = lgb.Booster(model_file=self.model_path)
            logger.info(f"ORACLE_V2: LightGBM model loaded from {self.model_path}")
        except Exception as e:
            logger.error(f"ORACLE_V2 load failure: {e}")

    def _extract_features(self, df: pd.DataFrame) -> Optional[np.ndarray]:
        """Extract same features used during training."""
        cols = ['rsi', 'macd', 'atr', 'adx', 'ema20_dist', 'ema50_dist', 'volume_ratio']
        # Distances
        df['ema20_dist'] = (df['close'] - df['ema20']) / df['ema20']
        df['ema50_dist'] = (df['close'] - df['ema50']) / df['ema50']
        
        if not all(c in df.columns for c in cols):
            return None
            
        return df[cols].iloc[-1].values
