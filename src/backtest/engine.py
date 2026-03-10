"""
AlphaZero Backtest Engine
src/backtest/engine.py

Vectorized and event-simulating backtest engine for AlphaZero Capital.
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import os

from src.data.fetch import DataFetcher
from src.agents.oracle_agent import OracleAgent
from src.agents.titan_agent import TitanAgent
from src.agents.sigma_agent import SigmaAgent
from src.agents.atlas_agent import AtlasAgent
from src.agents.chief_agent import ChiefAgent
from src.backtest.metrics import calculate_metrics, calculate_trade_metrics

logger = logging.getLogger("BACKTEST")

class BacktestEngine:
    def __init__(self, initial_capital: float = 1_000_000.0, config: Dict = None):
        self.initial_capital = initial_capital
        self.config = config or {}
        self.fetcher = DataFetcher(mode='PAPER')
        
        # Portfolio State
        self.cash = initial_capital
        self.holdings = {} # symbol -> {quantity, entry_price, entry_time}
        self.equity_curve = [] # list of {timestamp, equity, cash}
        self.trades = [] # list of closed trades
        
        # Agents (mocked or initialized for backtest)
        self.oracle = OracleAgent(None, self.config)
        self.titan = TitanAgent(None, self.config)
        self.sigma = SigmaAgent(None, self.config)
        self.atlas = AtlasAgent(None, self.config)
        self.chief = ChiefAgent(None, self.config)
        
        self.slippage = self.config.get('BACKTEST_SLIPPAGE', 0.001) # 0.1%
        self.commission = self.config.get('BACKTEST_COMMISSION', 0.0005) # 0.05%

    def run(self, start_date: str, end_date: str, symbols: List[str]):
        """
        Run the backtest loop.
        """
        logger.info(f"Starting backtest from {start_date} to {end_date} for {len(symbols)} symbols")
        
        # 1. Load Data
        data_map = self._load_historical_data(start_date, end_date, symbols)
        if not data_map:
            logger.error("No data loaded. Backtest aborted.")
            return {}

        # 2. Align Timestamps (find all unique timestamps)
        all_ts = sorted(list(set().union(*(df.index for df in data_map.values()))))
        
        # 3. Simulation Loop
        for ts in all_ts:
            self._step(ts, data_map)
            
        # 4. Finalize
        return self._summarize()

    def _load_historical_data(self, start: str, end: str, symbols: List[str]) -> Dict[str, pd.DataFrame]:
        """
        Loads OHLCV data for all symbols.
        """
        data_map = {}
        for sym in symbols:
            try:
                # Using DataFetcher which fallbacks from nsepython to yfinance
                df = self.fetcher.get_ohlcv(sym, interval='1d', start=start, end=end)
                if not df.empty:
                    data_map[sym] = df
            except Exception as e:
                logger.warning(f"Failed to load data for {sym}: {e}")
        return data_map

    def _step(self, ts, data_map):
        """
        Execute one bar step.
        """
        current_data = {}
        for sym, df in data_map.items():
            if ts in df.index:
                row = df.loc[ts]
                current_data[sym] = {
                    'symbol': sym,
                    'open': row['Open'],
                    'high': row['High'],
                    'low': row['Low'],
                    'close': row['Close'],
                    'volume': row['Volume'],
                    'timestamp': ts.isoformat()
                }

        if not current_data:
            return

        # --- AGENT LAYER ---
        # 1. Oracle - Regime Detection
        # Mocking market_data for oracle
        regime_data = {'vix': 15.0} # Placeholder
        macro = self.oracle.analyze(regime_data)
        regime = macro.get('macro_bias', 'NEUTRAL')
        
        # 2. Titan - Signals
        signals = self.titan.generate_signals(current_data, regime)
        
        # 3. Sigma - Scoring
        # Sigma expects a list of candidates
        candidates = []
        for sym, d in current_data.items():
            # Add some dummy factors for sigma to work
            d['momentum'] = 0.5 # Placeholder
            d['trend_strength'] = 0.5
            candidates.append(d)
        
        scored = self.sigma.score_stocks(candidates, regime)
        
        # 4. Atlas - Sector Allocation
        atlas_sectors = self.atlas.get_sector_allocation(regime)
        
        # 5. Chief - Selection
        selections = self.chief.select_portfolio(scored, atlas_sectors, regime)
        
        # --- EXECUTION LAYER (Simulated) ---
        self._sync_portfolio(ts, selections, current_data)
        
        # --- ACCOUNTING ---
        current_equity = self.cash
        for sym, pos in self.holdings.items():
            if sym in current_data:
                current_equity += pos['quantity'] * current_data[sym]['close']
        
        self.equity_curve.append({
            'timestamp': ts.isoformat(),
            'equity': round(current_equity, 2),
            'cash': round(self.cash, 2)
        })

    def _sync_portfolio(self, ts, selections, current_data):
        """
        Rebalance portfolio to match Chief's selections.
        This is a simplified rebalancer.
        """
        target_symbols = {s['symbol'] for s in selections}
        current_symbols = set(self.holdings.keys())
        
        # 1. Sell symbols not in selections
        to_sell = current_symbols - target_symbols
        for sym in to_sell:
            self._close_position(sym, current_data[sym]['close'], ts)
            
        # 2. Open / Adjust symbols in selections
        # For simplicity, we just enter new ones if not already held
        # and ignore size adjustments of existing ones for this version.
        for sel in selections:
            sym = sel['symbol']
            if sym not in self.holdings and sym in current_data:
                target_amount = sel['capital_amount']
                price = current_data[sym]['close']
                # Apply slippage
                adj_price = price * (1 + self.slippage)
                quantity = int(target_amount / adj_price)
                if quantity > 0:
                    cost = quantity * adj_price
                    comm = cost * self.commission
                    if self.cash >= (cost + comm):
                        self.cash -= (cost + comm)
                        self.holdings[sym] = {
                            'quantity': quantity,
                            'entry_price': adj_price,
                            'entry_time': ts
                        }

    def _close_position(self, sym, price, ts):
        pos = self.holdings.pop(sym)
        # Apply slippage
        adj_price = price * (1 - self.slippage)
        proceeds = pos['quantity'] * adj_price
        comm = proceeds * self.commission
        self.cash += (proceeds - comm)
        
        # Record trade
        pnl_val = proceeds - (pos['quantity'] * pos['entry_price'])
        pnl_pct = pnl_val / (pos['quantity'] * pos['entry_price'])
        duration = (ts - pos['entry_time']).days
        
        self.trades.append({
            'symbol': sym,
            'entry_time': pos['entry_time'].isoformat(),
            'exit_time': ts.isoformat(),
            'entry_price': pos['entry_price'],
            'exit_price': adj_price,
            'pnl_val': pnl_val,
            'pnl_pct': pnl_pct,
            'duration': duration
        })

    def _summarize(self) -> Dict:
        equity_df = pd.DataFrame(self.equity_curve)
        if equity_df.empty: return {}
        
        equity_df.set_index('timestamp', inplace=True)
        returns = equity_df['equity'].pct_change().dropna()
        
        metrics = calculate_metrics(returns)
        trade_metrics = calculate_trade_metrics(self.trades)
        
        return {
            'metrics': metrics,
            'trade_stats': trade_metrics,
            'equity_curve': self.equity_curve,
            'trades': self.trades
        }
