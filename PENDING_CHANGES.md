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
## Applied: AlphaZero v5.1 Intelligence & Zero-Loss Upgrades (October 2026) ✅

### 1. Universal LLM Gateway (Local & Cloud APIs)
- **Zero-Dependency Universal Client**: `src/agents/llm_provider.py` connects to ANY local LLM or cloud API.
- **Local LLMs Supported**: Auto-detects local Ollama (`localhost:11434`, e.g. Gemma 3, Llama 3.2, Qwen 2.5, Phi 4), LM Studio (`localhost:1234`), vLLM, and llama.cpp with zero configuration.
- **Cloud APIs Supported**: OpenRouter (100+ models), Groq, DeepSeek-V3/R1, OpenAI (GPT-4o), Google Gemini (2.0 Flash), Anthropic Claude, Mistral, Together AI, and custom endpoints.
- **Agent Interoperability**: `EarningsCallAnalyzer`, `StrategyGenerator`, and `LLMPostMortem` now run seamlessly on any local or cloud provider without crashes.

### 2. Adaptive Profit & Loss Recovery Engine (`src/risk/adaptive_recovery_engine.py`)
- **Zero-Loss Breakeven Ratchet**: Automatically locks entry price + Indian market charges (+0.3%) once position moves +0.5R into profit.
- **Mathematical Recovery Deficit Ledger**: On any adverse loss, immediately computes an exact mathematical recovery plan (`Target = Deficit * 1.05 / Target_RR`) to recoup capital within subsequent high-conviction trades.
- **Self-Adjusting Thresholds**: Dynamically scales minimum confidence (0.50–0.88), minimum risk-reward (1.4–4.5), and required consensus based on regime, India VIX, and rolling win rate.

### 3. Directional Trend Velocity Predictor (`src/data/trend_velocity_predictor.py`)
- **Rise/Fall Probability Engine**: Multi-factor logistic sigmoid forecasting ($P(\text{Rise})$ vs $P(\text{Fall})$) combining EMA alignment velocity, momentum acceleration, and VWAP volume pressure.
- **Directional Veto**: Automatically vetoes BUY signals if $P(\text{Fall}) \ge 65\%$ and vice-versa.
- **Preemptive Position Threat Shield**: Evaluates open positions every tick; ratchets stop-loss to breakeven before trailing stops react if an adverse reversal is detected.

### 4. Strategic Pipeline Completion & Multi-Timeframe Alignment
- **MTF Entry Alignment**: Wired active 15m, 1h, and Daily alignment check (+8% confidence boost on confirmation; gentle penalty on divergence).
- **Nightly Autonomous Strategy Discovery**: Wired `StrategyGenerator.discover_strategy()` into nightly pipeline at 15:35 IST.
- **Dashboard & API Routing**: Aligned FastAPI backend (port 8001) and Vite React frontend (port 3000) with CORS and `/api/portfolio` routes.

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

## Pending: Phase 7 — Interactive Chatbot Integration & Manual Override (Future) 🤖
- **Chatbot Backend**: Implement LLM Agent (OpenAI/Gemini/Ollama) with tool-calling capabilities to perform deep-dive analysis on user-requested tickers.
- **Dashboard Chat UI**: Integrate conversational AI interface on the frontend for real-time portfolio management and queries.
- **Manual Trade Execution**: Connect chatbot commands directly to the `execution` pipeline (paper/live) bypassing normal agent scheduling for immediate action.

*Current build: AlphaZero v5.1.0 (Autonomous Production)*
