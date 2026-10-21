# AlphaZero Trading System - Development Roadmap

## Phase 1: Dashboard Data Refresh [100%] ✅
- [x] **KPI Integration**: Add Real-time P&L, Win Rate, and Agent Scores to `status.json`.
- [x] **Backend API expansion**:
    - [x] `/api/sources`: Data source health status.
    - [x] `/evaluation/stats`: Real-time signal accuracy tracking.
    - [x] `/candles/{symbol}`: Serve data for dashboard charts.
    - [x] `/fundamentals/{symbol}`: Company profile and ratios.
- [x] **Normalized State**: Convert snake_case to camelCase for React compatibility. ✅

## Phase 2: KARMA RL Intelligence [100%] ✅
- [x] **Dynamic Training Universe**: Refresh training symbols daily (Top Gainers/Losers + Random). ✅
- [x] **Parallel Nightly Stress Test**: Run `BacktestEngine` at 6 PM IST on training data. ✅
- [x] **Global US Market Sync**: S&P 500 / NASDAQ performance bias injection. ✅

## Phase 3: Strategic Upgrades (AlphaZero v5.0 Core) [100%] ✅
- [x] **Multi-Timeframe Confirmation**: 15m, 1h, and Daily alignment requirement for entries. ✅
- [x] **Tiered Profit Taking**: Scale-out 50% at +4% profit. ✅
- [x] **Zero-Risk Transition**: Move SL to Breakeven (+1%) at +2.5% profit. ✅
- [x] **Limit-Wait Execution**: Patient 30s limit wait before market fallback (Live mode). ✅
- [x] **Sector Hard-Caps**: Block more than 3 positions in the same sector. ✅
- [x] **Weekly Watchlist Tuning**: Monday evening sector-based re-balancing. ✅

## Phase 5: Dashboard V5 Upgrade [100%] ✅
- [x] **New Visual Engine**: Upgraded to React/JSX with GH-style aesthetics.
- [x] **Multi-Tab Architecture**: Overview, Positions, Signals, News, Performance, Evaluation, Agents.
- [x] **External Factors Tab**: Displays US Fed Rates, Brent Crude, USD-INR, and NSE VIX bias. (Req #3)
- [x] **Technical Indicator Tooltips**: Interactive definitions and market impact for 15+ indicators. (Req #1)
- [x] **Fundamental Data**: Integrated yfinance/MSD and Screener.in data into Stock Modal. (Req #2.2)
- [x] **Volume & Candle Analysis**: Automated detection of patterns and volume profiles. (Req #4)

## Phase 6: Auto-Evolving Architecture (Evolution 2.0) [100%] ✅
- [x] **Ensemble + Thompson Sampling**: Orchestrate capital allocation across multiple sub-agents (Mean Reversion, Trend Following) using Bayesian Thompson Sampling for optimal exploration/exploitation. ✅
- [x] **Online Fine-Tuning with Experience Replay**: Immediate model weight updates on live data, incorporating Experience Replay buffering to prevent catastrophic forgetting. ✅
- [ ] **Genetic Algorithm (GA)**: Macro-level evolution loop to mutate hyperparameters and model architectures, run every 100 epochs.

## Phase 7: Interactive Chatbot Integration & Manual Override [100%] ✅ 🤖
- [x] **Chatbot Backend**: Implement LLM Agent (Local Ollama, LM Studio, or Cloud APIs) with tool-calling capabilities (`portfolio_status`, `analyze_symbol`, `market_regime`, `execute_trade`, `get_signals`). ✅
- [x] **Dashboard Chat API**: Added POST `/api/chat` endpoint to `dashboard/backend.py` for real-time portfolio management and conversational quantitative analysis. ✅
- [x] **Manual Trade Execution**: EventBus manual trade override allowing the chatbot or user to bypass automated scheduling to inject trades on-demand. ✅

## Phase 8: Zero-Loss Engine, Trend Forecasting & Universal LLM [100%] ✅
- [x] **Universal LLM Gateway**: Support ANY local LLM (Ollama, LM Studio, vLLM) or ANY cloud API (OpenRouter, Groq, DeepSeek, OpenAI, Gemini, Claude). ✅
- [x] **Zero-Loss Breakeven Ratchet**: Charge-aware break-even ratchet (+0.3% buffer) executed at +0.5R profit distance. ✅
- [x] **Loss Recovery Deficit Ledger**: Automated mathematical deficit recovery target planning after any loss. ✅
- [x] **Dynamic Contextual Risk Thresholds**: Self-adjusting confidence barriers and risk-reward ratios based on India VIX and regime. ✅
- [x] **Directional Trend Velocity Predictor**: Multi-factor logistic sigmoid forecasting ($P(\text{Rise})$ vs $P(\text{Fall})$) with directional veto and open position threat monitoring. ✅
- [x] **Multi-Timeframe Dynamic Scoring**: Active 15m, 1h, Daily candle confirmation integrated with confidence modifiers. ✅

---
*Status Update: System is running AlphaZero v5.2 with active Thompson Sampling allocation, Interactive Chatbot API, Zero-Loss protection, and Universal Local/Cloud LLM Gateway.*
