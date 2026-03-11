"""
NEXUS Model Training Script
scripts/train_nexus.py

Generates synthetic but rule-consistent training data to create the initial
XGBoost model for regime detection.
"""

import os
import sys
import numpy as np
import xgboost as xgb
import json

# Add root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def generate_training_data(n_samples=5000):
    """
    Generate synthetic features based on the rules in intraday_regime_agent.py
    REGIMES: 0=TRENDING, 1=SIDEWAYS, 2=VOLATILE, 3=RISK_OFF
    """
    X = []
    y = []

    for _ in range(n_samples):
        # Features: [adx, rsi, vix, breadth, cev, atr]
        # These should roughly match the bounds in NEXUS agent
        
        # 1. TRENDING (High ADX, Good Breadth, Far from EMA)
        if np.random.random() < 0.25:
            adx = np.random.uniform(25, 50)
            rsi = np.random.uniform(40, 70)
            vix = np.random.uniform(10, 18)
            breadth = np.random.uniform(0.7, 1.0)
            cev = np.random.choice([np.random.uniform(1.5, 4.0), np.random.uniform(-4.0, -1.5)])
            atr = np.random.uniform(1.0, 2.0)
            X.append([adx, rsi, vix, breadth, cev, atr])
            y.append(0)

        # 2. SIDEWAYS (Low ADX, Neutral RSI, Low VIX, Close to EMA)
        elif np.random.random() < 0.5:
            adx = np.random.uniform(5, 18)
            rsi = np.random.uniform(45, 55)
            vix = np.random.uniform(10, 15)
            breadth = np.random.uniform(0.4, 0.6)
            cev = np.random.uniform(-0.5, 0.5)
            atr = np.random.uniform(0.5, 1.2)
            X.append([adx, rsi, vix, breadth, cev, atr])
            y.append(1)

        # 3. VOLATILE (High VIX, High ATR, Choppy RSI)
        elif np.random.random() < 0.75:
            adx = np.random.uniform(15, 30)
            rsi = np.random.choice([np.random.uniform(20, 35), np.random.uniform(65, 80)])
            vix = np.random.uniform(20, 25)
            breadth = np.random.uniform(0.3, 0.7)
            cev = np.random.uniform(-2.0, 2.0)
            atr = np.random.uniform(2.5, 5.0)
            X.append([adx, rsi, vix, breadth, cev, atr])
            y.append(2)

        # 4. RISK_OFF (Extreme VIX, Poor Breadth, Extreme RSI)
        else:
            adx = np.random.uniform(20, 40)
            rsi = np.random.uniform(15, 30)
            vix = np.random.uniform(26, 40)
            breadth = np.random.uniform(0.0, 0.3)
            cev = np.random.uniform(-5.0, -2.0)
            atr = np.random.uniform(3.0, 6.0)
            X.append([adx, rsi, vix, breadth, cev, atr])
            y.append(3)

    return np.array(X), np.array(y)

def train_and_save():
    print("Generating synthetic training data...")
    X, y = generate_training_data()
    
    print("Training XGBoost Regressor...")
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.1,
        objective='multi:softmax',
        num_class=4,
        eval_metric='mlogloss'
    )
    
    model.fit(X, y)
    
    models_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'models')
    os.makedirs(models_dir, exist_ok=True)
    
    model_path = os.path.join(models_dir, 'nexus_regime.json')
    model.save_model(model_path)
    
    print(f"✅ NEXUS model trained and saved to {model_path}")

if __name__ == "__main__":
    train_and_save()
