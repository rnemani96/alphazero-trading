# Changelog — AlphaZero Capital

## [4.2.0] - 2026-04-08 (Self-Healing Update)
### Added
- **Ensemble Consensus Gate v2.0**: TITAN + ORACLE + SHADOW multi-architecture voting.
- **Dynamic Majority Voting**: Automated agent-count adjustment for signal gating.
- **Market Breadth-Boost**: Automated threshold relaxation (0.05) during market rallies.
- **Symbol Sanitizer**: Prevents `UNDEFINED` ticker injection into data fetching.

### Fixed
- **yfinance 401Crumb Recovery**: Browser-emulation sessions and native curl_cffi fallback.
- **Portfolio Guard Stability**: Fixed `UnboundLocalError` in price-update loop.
- **Shadow LSTM Import Path**: Resolved ModuleNotFoundError for EventBus.

### Changed
- **Relaxed Boundaries**: Sideways threshold lowered to 0.52 (Ensemble) and 0.35 (TITAN).
- **Context Score Relaxation**: Required score lowered to 2/5 for increased strike frequency.

---


All notable changes to the AlphaZero Capital project will be documented in this file.
**Rule:** Every new feature or fix MUST be accompanied by the date of implementation.

## [7.7.0] - 2026-04-08
### 🔬 Ensemble Intelligence (SOTA 2026 Alignment)
- **Ensemble Consensus Gate**: 
  - Upgraded the signal orchestrator to a **Majority-Vote Committee**. 
  - New logic requires at least 2/3 agreement between **Neural (LSTM)**, **Boosting (LGBM)**, and **Rule-based (TITAN)** architectures before a high-conviction signal is approved.
- **Bayesian Hyperparameter Tuner**: 
  - Implemented `scripts/tune_hyperparams.py` using **Optuna**.
  - Enables per-symbol optimization, allowing the system to find the unique mathematical "sweet spot" (RSI/EMA/Thresholds) for every stock in the Nifty 500.
- **Performance Benchmarking**: Integrated automated logic to penalize signals when architectures are in "Discord" (low agreement), drastically reducing false-positive breakouts.

---

### 🧠 Autonomous Intelligence (The Final Forge)
- **Committee Model Forge**: 
  - Implemented `scripts/train_committee.py` to handle production-ready training of **LightGBM** and **PyTorch LSTM** models.
  - Features AUC-based early stopping and multi-symbol sequence validation.
- **Nightly Self-Improvement Loop**: 
  - Fully automated the AI retraining process inside `main.py`.
  - The system now performs a daily "Deep Learn" at 18:00 IST, calibrating its neural weights to the latest market trends automatically.
- **Integrated Showdown**: 
  - Verification stage added after nightly training to ensure new models outperform old benchmarks before being promoted to live trading.

---

### 🚀 Total Autonomy (The Ultimate Integration)
- **Unified Command Center**: Refactored `main.py` to be the single entry point for all system operations. No external scripts required.
- **Background AlphaHarvester**:
  - Implemented a multi-threaded background daemon inside `main.py` that continuously harvests historical data for the entire Nifty 500.
  - Maximized data lookback: 10 years (1d), 720 days (1h), and 60 days (intraday).
- **Candlestick Pattern Engine**: 
  - Integrated explicit pattern detection (Doji, Hammer, Shooting Star, Bull/Bear Engulfing, Morning/Evening Star) into the automated feature store.
  - Models now train on geometric price action features alongside technical indicators.
- **Automated Nightly Competition**: 
  - The system now automatically executes the "AI Model Showdown" every night at 18:00 IST.
  - Compares XGBoost, LightGBM, and LSTM architectures and auto-selects the winner for the next session's signal generation.

---

### 🧠 Neural & Fundamental Convergence (The Upgrade)
- **Multi-Model Committee**: 
  - **ORACLE_V2 (LightGBM)**: Implemented a LightGBM-GOSS model for high-precision breakout detection, outperforming standard XGBoost for tabular market data.
  - **SHADOW_LSTM (PyTorch)**: Added a sequential Deep Learning model that analyzes the last 30 bars of price action to validate geometric chart patterns.
- **News-Catalyst Matcher**: Integrated **HERMES news extraction** directly into the TITAN signal loop. Signals now receive a **+10% confidence boost** if major keywords like "Order," "Contract," or "Dividend" are detected for the stock.
- **Automated Feature Store**:
  - Modified `download_data_v4.py` to automatically calculate **45+ technical indicators** for every download.
  - Data is now kept "ready for training" in `data/training_ready/`. 
  - Created `scripts/bulk_featurize.py` for legacy database conversion.
- **Adaptive Profit Preservation**:
  - Tightened trailing stops dynamically (2.5x → 1.0x ATR) as profit tiers are reached.
  - Implemented **Greed Close**: Guaranteed protection of "In-Hand" profits. >1.25% winners are automatically closed if they drop below entry+0.5%.

---

### 🛡️ Stabilization & High-Precision Selection Suite
- **Strict Risk Adherence**: Removed the dangerous ₹15,000 position minimum. Enforced a hard **1% capital risk budget** per trade via ATR-sizing. Positions are now skipped if the risk-per-share is too high relative to the stock price.
- **Sideways Market Protection**: 
  - Tightened Stop-Losses to **2.0x ATR** (was 3.0x) to cut losses 33% faster in choppy regimes.
  - Raised entry confidence threshold to **40%** (was 25%) and now require agreement from at least **2 parallel strategies**.
- **Earnings Risk Blocker**: Integrated **EarningsCalendarAgent** into the TITAN signal loop. The system now automatically skips signals for stocks with earnings announcements in the next **2 days** to avoid binary event risk.
- **Quality Over Quantity Gate**: Implemented a **Multi-Agent Consensus** gate for Sideways/Volatile markets. Trades now require a positive **Sentiment score (HERMES)** and **Sector Alpha (ATLAS)** to emit.
- **Aggressive Profit Harvesting**:
  - **Early Break-even**: Stops now automatically move to **Entry + 0.1%** as soon as a trade hits **0.8% profit**.
  - **Confidence-Based Sizing**: High-conviction setups (>90% confidence) now automatically **double the risk budget to 2%** to maximize capital on the best ideas.

### ⚙️ Pipeline & Data Integrity Fixes
- **NSE Multi-Source Fix**: Implemented mandatory **.NS suffixing** for all NSE tickers in `train_model.py` and `download_data_v4.py`, resolving a 95% data ingestion failure rate in `yfinance`.
- **Look-ahead Bias Resolution**: Switched Random Forest training to **Chronological Splitting** (`iloc[:split]`). Fixed the "cheating" model that was training on future data.
- **NEXUS Adaptive Threshold**: Replaced the hard-coded 50-stock requirement in NEXUS training with an **Adaptive Pool** (`max(20, 10% of universe)`), ensuring incremental updates succeed even with sparse data.
- **FinBERT Stability**: Expanded the labeled sentiment corpus from 55 to **165 examples**, incorporating specific Indian market lexicon (RBI/SEBI/FII flows) to stabilize `eval_loss`.
- **Historical Technical Logic**: Standardized `add_all_indicators` across all historical training pipelines (`train_full_history_v4.py`) to ensure PPO agents no longer train on placeholder zeros.

---


### 📊 Dashboard & UI Wiring (Full Dynamic Update)
- **TopNav Indices**: Fully wired NIFTY 50, NIFTY BANK, INDIA VIX, and Today's P&L to real-time data. No longer static.
- **Real-Time News Stream**: Wired HERMES agent news headlines to the dashboard's Intelligence tab via WebSockets.
- **Dynamic Portfolio Quotes**: Enabled live price updates for all watchlist and portfolio symbols on every system iteration.
- **Agent KPI & Knowledge Integration**: Wired KARMA learning patterns and LENS agent efficiency scores to the UI for total system transparency.
- **Candidates Feed**: Scored stocks from SIGMA and ATLAS now appear in the "Active Scans" section in real-time.

### 🛡️ Risk & Execution Logic
- **Ghost Trade Fix**: Resolved the "trades_today" increment bug that was causing premature daily trade exhaustion by only counting successful executions.
- **Multi-Upgrade Priority Logic**: Reverted `MAX_TRADES_PER_DAY` to **20** but heavily modified `APEX`/`main.py`. The system now dynamically replaces the lowest confidence/underperforming open positions if new exceptionally strong signals emerge, acting as a competitive 'survival of the fittest' rather than blindly consuming daily limits.
- **Volume Sensitivity Tweak**: Relaxed `_check_volume_confirmation` threshold from **1.5 to 1.2** to improve signal throughput in low-volatility/sideways markets.
- **Post-Market Audit (Mar 23rd)**: Identified and documented a cluster of T10/T2 breakout failures during a SIDEWAYS regime; recommended regime-based strategy filtering.

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
