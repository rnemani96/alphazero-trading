# Changelog — AlphaZero Capital

All notable changes to the AlphaZero Capital project will be documented in this file.
**Rule:** Every new feature or fix MUST be accompanied by the date of implementation.

## [5.0.0] - 2026-03-24

### 🛡️ Risk Management & Capital Safeguards
- **Strategy Correlation Guard**: Implemented a strict limit of **3 open positions per strategy** (e.g., T10) to prevent over-exposure and "herd behavior" during mass signal generation.
- **Short Sale P&L Fix**: Resolved a critical money leak where short positions (SELL signals) were having their P&L incorrectly calculated as BUYS. Logic is now fully direction-aware.
- **Volatility Filter**: Added a mandatory **9:15 AM - 9:45 AM IST entry lock** to avoid getting stopped out by initial market-open noise.

### 🚀 Execution & Signal Improvements
- **Execution Gap Fix**: Replaced the hardcoded 0.65 entry confidence threshold with **Regime-Adaptive Confidence**:
  - Trending: 0.55
  - Sideways: 0.60
  - Volatile: 0.70
- **Daily P&L Dash**: Rewired dashboard to display real-time "Today's P&L" based on trades closed in the current session.
- **History Expansion**: Increased history rendering limit from 100 to 500 trades for better audit trails.

### 🕯️ Candlestick Price Action
- **Pattern Detection Engine**: Added native support for **Hammer**, **Doji**, **Engulfing**, and **Morning/Evening Star** patterns in the indicator layer.
- **TITAN Integration**: New "Price Action" strategy category added to TITAN, contributing 10% to overall signal confidence across all regimes.

## [4.0.0] - 2026-03-21

### 🚀 Major Features & AI Integration
- **17 specialized agents** collaborating via a secure internal Event Bus.
- **NEXUS Regime Classification**: Integrated XGBoost model for automatic market regime detection (Trending, Sideways, Volatile, Risk-Off).
- **TITAN Strategy Engine**: 45 parallelized technical strategies with regime-weighted consensus voting.
- **KARMA RL Actor-Critic**: Reinforcement learning fine-tuned via weekend PPO retraining.
- **ATLAS Sector Rotation**: Dynamic 90-day relative strength tracking for optimal sector allocation.
- **HERMES News & Sentiment**: 4-layer hybrid sentiment pipeline featuring FinBERT and custom keyword lexicons.
- **Natural Language Interface**: Telegram bot integrated with LLMs (Claude/GPT-4) for direct system status queries.

### 🛡️ Security & Risk Management
- **Security Audit & Hardening**: Restricted CORS to localhost, added `DASHBOARD_SECRET` command authentication, and bound backend to 127.0.0.1.
- **GUARDIAN Agent**: Hardcoded safety rules including daily loss halts, position sizing (Kelly + ATR), and sector exposure limits.
- **Dynamic Hedging**: Automated `NIFTY_HEDGE_PE` signal injection during `RISK_OFF` regimes.
- **Shadow Model Support**: A/B testing framework allowing pre-promotion evaluation of newly trained models.

### ⚙️ Automation & Infrastructure
- **Weekend Cron Ecosystem**: Windows Task Scheduler registration for automated Bayesian optimization, regime training, and RL updates.
- **High-Frequency Data Pipe**: Parallelized multi-source market data engine with 50-worker ThreadPoolExecutor.
- **Bayesian Optimization**: Optuna integration for per-symbol hyperparameter tuning of strategy indicators.
- **Pre-Monday Readiness**: Automated Sunday 8 PM verification scripts with Telegram status reports.

### 📊 Dashboard & UI
- **Real-Time Visualization**: React-based dashboard with WebSocket push updates for zero-latency monitoring.
- **Agent Health Monitoring**: Live status and KPI tracking for all 17 system components.
- **Signal Feed & Portfolio**: Centralized view of all generated signals and unrealized/realized PnL.

### 🔧 Fixes & Optimizations
- **Vectorized Indicators**: Rewrote all technical indicators using raw NumPy for a 20x performance boost over standard Pandas loops.
- **Atomic State Persistence**: Safe JSON writing via temporary file swapping to prevent dashboard corruption.
- **Broker Abstraction**: Unified `Mercury` execution layer supporting both simulated Paper trading and OpenAlgo live routing.

---
*AlphaZero Capital — Version 4.0: The Proprietary Equities Hedge Fund.*
