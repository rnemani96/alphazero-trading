# Pending & Recently Applied Changes — AlphaZero Trading System

## Applied: AlphaZero v5.0 Strategic Upgrades (March 23, 2026) ✅

### 1. Dashboard & API Expansion (Phase 1)
- **Status Normalization**: `status.json` now provides camelCase keys for React frontend compatibility.
- **KPI Enrichment**: Added real-time P&L, cumulative win rate, and agent-specific Sharpe ratios.
- **New Endpoints**: 
    - `/api/sources`: Real-time health check of data providers (Yahoo, NSE, Google).
    - `/candles/{symbol}`: High-performance data serving for dashboard charts.
    - `/fundamentals/{symbol}`: Integrated fundamental ratios (PE, ROE, Debt/Equity).

### 2. Nightly Intelligence Refresh (Phase 2)
- **Dynamic Training Universe**: Automated daily refresh based on Top 5 Gainers/Losers + Random Nifty 500 selection.
- **Parallel Stress Test**: Added capability to run 60-day parallel backtests at 6 PM IST to re-rank strategy weights.
- **Global US Market Sync**: S&P 500 and NASDAQ 100 performance now injects a ±5% bias into sentiment confidence scores.

### 3. AlphaZero v5.0 Core Strategic Enhancements (Phase 3)
- **Multi-Timeframe (MTF) Entry Filter**: Requires bullish alignment across 15m, 1h, and Daily timeframes for all new long entries.
- **Adaptive Execution (Patient Limit Wait)**:
    - High-conviction trades (`confidence > 0.7`) now wait 30 seconds for a limit fill before falling back to a market order.
- **Tiered Profit Management**:
    - **Scale-Out**: Automated 50% sell at **+4.0%** profit.
    - **Zero-Risk Transition**: Moving stop-loss to **Breakeven (+1%)** once profit hits **+2.5%**.
- **Sector Hard-Caps**: Enforced a risk-limit of **maximum 3 positions per sector** (reduced from 4) to ensure high diversification.
- **Weekly Watchlist Tuning**: Scheduled for Monday evenings to re-align focus based on sectoral momentum shifts.

## Applied: Dashboard V5 — Advanced UI Console (Phase 5) ✅
- **New Visual Engine**: Upgraded to **React/JSX** with advanced dark-mode aesthetics.
- **Multi-Tab Architecture**: Overview, Positions, Signals, News, Performance, Evaluation, Agents.
- **External Factors Tab**: Displays US Fed Rates, Brent Crude, USD-INR, and NSE VIX bias. ✅
- **Technical Indicator Tooltips**: Interactive definitions and market impact for 15+ indicators. ✅
- **Fundamental Data**: Integrated yfinance and Screener.in data into Stock Modal. ✅
- **Volume Profile**: Detailed price-volume distribution (Volume at Price). ✅
- **Candle Pattern Detection**: Automated detection of Doji, Marubozu, Hammer, etc. ✅

---
## Pending: Phase 4 — Institutional Broker Integration ⏳
- **Upstox API v2**: Implement dedicated executor class with multi-instrument support.
- **Zerodha KiteConnect**: Integrate order management and live margin checking.
- **Unified Order Book**: Aggregated view across all connected brokers (Paper + Live).
- **Execution Analytics**: Automated post-trade slippage analysis vs. VWAP.

## Pending: Phase 6 — Auto-Evolving Architecture (Evolution 2.0) [HIGH PRIORITY] 🚀
- **Ensemble + Thompson Sampling**: Orchestrate capital allocation across multiple sub-agents (Mean Reversion, Trend Following) using Thompson Sampling for optimal exploration/exploitation. (Target: +20-30% Sharpe)
- **Online Fine-Tuning**: Implement immediate model weight updates on live data, incorporating Experience Replay buffering to prevent catastrophic forgetting.
- **Genetic Algorithm (GA)**: Macro-level evolution loop to mutate hyperparameters and model architectures, run every 100 epochs.

*Current build: AlphaZero v5.0.1 (Stable)*
