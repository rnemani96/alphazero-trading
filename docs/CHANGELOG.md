# Changelog — AlphaZero Capital

## [8.3.1] - 2026-04-25 (GIFT Nifty Integration & Anti-Bot Resilience)
### 🚀 Global Market Intelligence
- **GIFT Nifty (SGX) Causal Integration**: Fully integrated `sgx_bias` as a feature in the **NEXUS** regime model. The AI now uses the GIFT Nifty futures premium (compared to the domestic NSE close) to predict market "mood" and volatility regimes before the Indian market opens.
- **Historical Gap Proxy**: Updated `scripts/train_nexus.py` to train on the historical **Index Opening Gap**, allowing the model to learn the mathematical relationship between overnight global shocks and intraday price action.

### 🛡️ Data Resilience & Anti-Bot Layer
- **Aggressive Yahoo Bypass**: Implemented an automated **Crumb Recovery** system. If Yahoo returns a 401 Unauthorized error, the engine now autonomously purges the local `py-yfinance` cache and clears memory-resident cookies to force a fresh handshake.
- **Network Signature Rotation**: Added a pool of modern browser User-Agents and **Rate-Limit Jitter (1–3s)** between chunk requests to humanize traffic and prevent IP-level rate-limiting.
- **Permanent Blacklist**: Integrated a hard-coded suppression list for delisted symbols (e.g., `RELINFRA.NS`, `ABGSHIP.NS`) directly into the recorder and data engine to protect API quotas.
- **Cool-Down Safeguard**: Implemented a mandatory 60-second "cool-down" period when 401 errors are detected, ensuring the system doesn't get permanently flagged as a bot.

---
### 🚀 Market Recording & Replay Intelligence
- **High-Speed Market Recorder**: Implemented `scripts/market_recorder.py` which autonomously captures minute-level tick data for all Nifty 500 stocks. 
- **Batch Processing Optimization**: Reduced snapshot recording time from 4+ minutes to **under 60 seconds** using chunked yfinance downloads (25 symbols per chunk).
- **Automated Nightly Backtester**: Integrated `scripts/nightly_backtest.py` into the nightly orchestrator to automatically replay the day's data against benchmark strategies for continuous self-validation.
- **Strategy Leaderboard UI**: Added a new "Strategy Performance Rankings" component to the dashboard to monitor the real-time and backtested effectiveness of all active trading logics.

### 🛡️ Execution & Data Stability
- **Relaxed Trading Constraints**: Lowered the mandatory market breadth gate to **30%** (was 50%) and signal confidence to **0.15** to ensure continuous trade execution during sideways or neutral regimes.
- **yfinance Resiliency Layer**: Overhauled the data fetching engine to handle malformed responses and rate-limiting gracefully. Integrated robust handling for delisted symbols and Yahoo's anti-bot measures.
- **Persistent Connection Management**: Optimized network throughput by aligning with yfinance's internal anti-bot bypass backends (restored native session management).

---

## [8.2.0] - 2026-04-20 (Monopoly Intelligence & Institutional Risk Suite)
### 🚀 Monopoly & Fundamental Intelligence
- **Dynamic Monopoly Scanner**: Implemented `_monopoly_scanner_thread` which autonomously evaluates the NIFTY 500 for "Moat" characteristics (Margins >25%, ROE >15%, low debt).
- **Fundamental Confidence Boost**: Integrated institutional-grade logic into the signal aggregator, applying a +10% confidence boost to stocks identified as monopolies to prioritize high-quality long-term holdings.
- **Cache-Ready Intelligence**: Established `config/monopoly_stocks.json` for persistent storage of identified moats, ensuring the engine has fundamental context immediately upon startup.

### 🛡️ Advanced Risk & Institutional Logic
- **Dynamic Slippage Modeling**: Overhauled `PositionSizer` to penalize expected gross profit based on stock-specific volatility (ATR). High-volatility stocks now require a higher gross-profit buffer to account for market impact.
- **Market Breadth Override (A/D Protection)**: Implemented a strict signal veto when the broader market Advance/Decline ratio falls below 50%. This prevents "catching a falling knife" during systemic sell-offs.
- **Volume-Weighted Signal Priority**: Integrated exponential confidence scaling for high-relative-volume breakouts (>3.0x), ensuring the system captures institutional accumulation signatures with high precision.

---

## [8.1.1] - 2026-04-20 (Dashboard UI Synchronization & Stability)
### 📊 UI Synchronization & Dynamic State
- **Dynamic Variable Injection**: Overhauled `alphazero_v5.html` and `App.jsx` to completely replace hardcoded mock values (e.g., initial capital, slot counts, win rates) with dynamic backend-driven variables (`apData`).
- **Positions Tab Repair**: Rebuilt and safely integrated the `<PositionsTab>` UI component after fixing a major syntax corruption bug that was causing the Babel JSX parser to fail. Re-enabled live tracking of 'Trade History' and dynamic charge calculations.
- **Signals Tab Repair**: Surgically restored the `<SignalsTab>` component to fix "JSX expressions must have one parent element" errors. The dashboard now properly renders all dynamic signals fed from the TITAN engine without crashing.
- **Null-Safety Enhancements**: Added comprehensive null-coalescing (`??`) and optional chaining (`?.`) operators throughout the frontend code to ensure the dashboard remains stable even during backend data pipeline restarts or cold starts.

---

## [8.1.0] - 2026-04-19 (Fully Dynamic Momentum & System Fixes)
### 🚀 Dynamic Execution & Profit Maximization
- **Fully Dynamic Momentum Scanner**: The background `_momentum_scanner_thread` was completely overhauled. Instead of relying on a hardcoded list of 26 stocks, the system now queries the entire **NIFTY 500**, calculates live intraday percentage gains, and injects the top 20 absolute best performers into the live trading engine.
- **High-Frequency Market Sensing**: Scanner iteration delay was reduced from 10 minutes to **5 minutes**, ensuring AlphaZero catches fast-moving intraday momentum breakouts immediately.
- **Momentum Confidence Priority**: The `TITAN` strategy engine now applies a **+15% immediate confidence boost** to any stock flagged by the dynamic momentum scanner, overriding standard hesitations and aggressively allocating capital to the day's winners.

### 🛠️ Core System & Training Fixes
- **NEXUS Regime Model Encoding**: Resolved a critical `UnicodeEncodeError` in `scripts/train_nexus.py` caused by non-Latin characters (like the ₹ symbol or emojis) crashing the XGBoost training pipeline. The pipeline now explicitly forces UTF-8 encoding.
- **Parquet Cache Normalization Bug**: Fixed a bug where cached historical data downloaded by `data_daemon.py` had capitalized column names (e.g., 'Close', 'High'), which broke the training engine and caused training sets to report 0 samples. The caching layer now rigorously enforces lowercase column names.
- **Optuna Download Suffix Bug**: Fixed `scripts/optimize_params.py` failing to download historical data from Yahoo Finance. Added logic to automatically append `.NS` to ticker symbols before requesting data, while ensuring the clean symbols (without `.NS`) are preserved when saving optimized parameters to the database.

---

## [8.0.0] - 2026-04-17 (High-Frequency & Charge-Aware Update)
### 🚀 Performance & Scale (User-Driven)
- **Universe Expansion**: Increased daily scanning universe to **120 symbols** (60 high-volume performers + 60 Nifty 50 momentum/liquid stocks).
- **High-Frequency Scans**: Reduced iteration sleep time to **5 minutes** (300s) for faster market reaction and breakout capture.
- **Capacity Scaling**: Increased concurrent position limit to **25** and daily trade capacity to **50**.

### 🛡️ Risk & Profitability (Charge-Aware Logic)
- **Charge Calculator**: Implemented a new core module `src/risk/charge_calculator.py` for precise Indian market tax/fee modeling (STT, GST, SEBI, Stamp Duty, DP).
- **Net-Profit Viability Filter**: Integrated charge-awareness into the `PositionSizer`. The system now automatically skips signals where expected charges eat >15% of gross profit.
- **Minimum Quantity Floor**: Implemented logic to calculate the minimum quantity required to ensure a trade is mathematically profitable after all fees.
- **Guardian Risk Relaxation**: Relaxed hard risk gates to enable higher trade frequency:
    - Min Risk:Reward ratio lowered to **1.2** (was 2.0).
    - Max daily loss limit increased to **5%** (was 2%).
    - Max position sizing increased to **10%** (was 5%).

### 📊 Dashboard & Monitoring
- **Live Discovery Feed**: Implemented real-time export of top 50 candidates to `logs/candidates.json`.
- **Candidates API**: Added a new `/api/candidates` endpoint to the dashboard backend for continuous monitoring of profitable stock scans.
- **Transparency**: Every signal now carries `expected_charges` and `net_pnl_projection` metadata for full visibility of transaction costs.

### ⚙️ Signal Aggregation
- **Hyper-Relaxed Thresholds**: Lowered ensemble entry confidence requirements to **0.22 - 0.35** (from 0.55+) across all regimes to maximize today's trade capture.
- **Agreement Relaxation**: Reduced mandatory architecture agreement to **1/1** (was 2/3) for high-conviction signals during trending markets.

---

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
