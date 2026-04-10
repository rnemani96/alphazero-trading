"""
SHADOW LSTM - Sequence Predictor
src/agents/lstm_agent.py

Uses a PyTorch-based LSTM to analyze the last 30 bars of price action.
Captures sequential patterns (head-and-shoulders, flag patterns) 
that tabular models like XGBoost/LGBM might miss.
"""

import logging
import os
import torch
import torch.nn as nn
import numpy as np
import pandas as pd
from typing import Dict, Optional
from datetime import datetime

try:
    from src.event_bus.event_bus import BaseAgent
except ImportError:
    from ..event_bus.event_bus import BaseAgent

logger = logging.getLogger("LSTM_AGENT")

class LSTMModel(nn.Module):
    def __init__(self, input_size=5, hidden_size=64, num_layers=2):
        super(LSTMModel, self).__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=0.2)
        self.fc = nn.Linear(hidden_size, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        out, _ = self.lstm(x)
        out = self.fc(out[:, -1, :])
        return self.sigmoid(out)

class LSTMAgent(BaseAgent):
    def __init__(self, event_bus, config):
        super().__init__(event_bus, config, "SHADOW_LSTM")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = LSTMModel().to(self.device).eval()
        self.model_path = os.path.join("models", "shadow_lstm.pth")
        
        if os.path.exists(self.model_path):
            self._load_model()

    def predict(self, symbol: str, df: pd.DataFrame) -> Dict:
        """
        Returns a confidence score 0-1 from sequence analysis.
        """
        if len(df) < 30:
            return {'symbol': symbol, 'confidence': 0.5, 'action': 'WAIT'}

        try:
            # 1. Prepare sequence (last 30 bars, OHLCV normalized)
            seq = self._prepare_seq(df)
            if seq is None:
                return {'symbol': symbol, 'confidence': 0.0, 'action': 'WAIT'}

            # 2. Inference
            with torch.no_grad():
                input_tensor = torch.FloatTensor(seq).unsqueeze(0).to(self.device)
                prob = self.model(input_tensor).item()

            return {
                'symbol': symbol,
                'confidence': float(prob),
                'action': 'BUY' if prob > 0.70 else 'WAIT',
                'model': 'LSTM_SHADOW'
            }
        except Exception as e:
            logger.debug(f"LSTM prediction failed for {symbol}: {e}")
            return {'symbol': symbol, 'confidence': 0.0, 'action': 'WAIT'}

    def _prepare_seq(self, df: pd.DataFrame) -> Optional[np.ndarray]:
        cols = ['close', 'high', 'low', 'open', 'volume']
        subset = df[cols].iloc[-30:].copy()
        
        # Min-Max normalization within the window
        subset = (subset - subset.min()) / (subset.max() - subset.min() + 1e-9)
        return subset.values

    def _load_model(self):
        try:
            self.model.load_state_dict(torch.load(self.model_path, map_location=self.device))
            logger.info("SHADOW_LSTM: Model weights loaded.")
        except Exception as e:
            logger.error(f"SHADOW_LSTM: Load failure: {e}")
