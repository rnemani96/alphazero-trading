# AlphaZero Capital — Authoritative Project Structure
# Version 2.0 | Paper-first, Live-ready

## ═══════════════════════════════════════════════
## THE CORE PROBLEM — WHY IT'S BROKEN
## ═══════════════════════════════════════════════

Someone ran `create_remaining_files.py` which stamped STUB versions of
critical agent files on top of the real ones. The stubs have DIFFERENT
class signatures — no BaseAgent inheritance, no event bus.

### Shadow File Conflicts (DELETE THESE FROM YOUR REPO)

| Stub file created               | Real file it shadows         | Why it breaks                          |
|----------------------------------|------------------------------|----------------------------------------|
| `src/agents/chief_agent.py`      | knowledge base version       | Stub ignores SIGMA/ATLAS entirely      |
| `src/agents/sector_agent.py`     | knowledge base version       | Stub has wrong `__init__` signature    |
| `src/agents/intraday_regime_agent.py` | knowledge base version  | 4-line stub, always returns TRENDING   |
| `src/agents/news_sentiment_agent.py`  | knowledge base version  | Always returns NEUTRAL                 |
| `src/event_bus/event_bus.py`     | knowledge base version       | Stub EventBus missing priority queue   |

### Dual-file Naming Conflict

| Old flat file       | Correct agent wrapper     | Who calls what                 |
|---------------------|---------------------------|--------------------------------|
| `titan.py`          | `titan_agent.py`          | main.py imports titan_agent    |
| `mercury.py`        | `mercury_agent.py`        | main.py imports mercury_agent  |
| `guardian.py`       | `guardian_agent.py`       | main.py imports guardian_agent |

The `titan.py` / `mercury.py` / `guardian.py` flat files are the REAL 
strategy/execution engines. The `*_agent.py` files wrap them with BaseAgent.
BOTH must exist. Do NOT delete the flat files.


## ═══════════════════════════════════════════════
## CORRECT FOLDER STRUCTURE
## ═══════════════════════════════════════════════

```
alphazero-trading/                    ← repo root
│
├── main.py                           ← ENTRY POINT: python main.py
├── run_paper.py                      ← NEW: standalone paper engine (no broken imports)
├── .env                              ← secrets (never commit)
├── .env.example                      ← template
├── requirements.txt
│
├── config/
│   ├── settings.py                   ← all config, reads from .env
│   └── sectors.py                    ← SECTORS dict + SYMBOL_TO_SECTOR map
│
├── src/
│   │
│   ├── event_bus/
│   │   └── event_bus.py              ← EventBus, BaseAgent, EventType, Event
│   │                                    (priority queue, thread-safe, start/stop)
│   │
│   ├── agents/
│   │   ├── oracle_agent.py           ← ORACLE: macro (VIX, FII, USD/INR, SPX)
│   │   ├── sigma_agent.py            ← SIGMA: 8-factor stock scorer
│   │   ├── chief_agent.py            ← CHIEF: portfolio selector from SIGMA
│   │   ├── sector_agent.py           ← ATLAS: sector allocation weights
│   │   ├── intraday_regime_agent.py  ← NEXUS: TRENDING/SIDEWAYS/VOLATILE/RISK_OFF
│   │   ├── news_sentiment_agent.py   ← HERMES: FinBERT + keyword RSS scraper
│   │   ├── titan_agent.py            ← TITAN: wraps titan.py engine
│   │   ├── guardian_agent.py         ← GUARDIAN: wraps guardian.py risk rules
│   │   ├── mercury_agent.py          ← MERCURY: wraps mercury.py executor
│   │   ├── lens_agent.py             ← LENS: P&L attribution + reports
│   │   ├── karma_agent.py            ← KARMA: RL learning, weight updates
│   │   ├── options_flow_agent.py     ← OPTIONS_FLOW: unusual activity scanner
│   │   ├── multi_timeframe_agent.py  ← MTF: 5-timeframe confirmation
│   │   ├── llm_earnings_analyzer.py  ← EARNINGS_ANALYZER: LLM on earnings calls
│   │   └── llm_strategy_generator.py ← STRATEGY_GENERATOR: LLM discovers patterns
│   │
│   ├── (flat engine files — NOT agents, called BY agents)
│   │   ├── titan.py                  ← 45 strategy implementations (TitanStrategyEngine)
│   │   ├── mercury.py                ← PaperExecutor + OpenAlgoExecutor classes
│   │   └── guardian.py               ← GuardianRules class (hard risk limits)
│   │
│   ├── data/
│   │   ├── fetch.py                  ← DataFetcher: yfinance NSE data
│   │   └── indicators.py             ← add_all_indicators(df) — single source of truth
│   │
│   ├── risk/
│   │   ├── risk_manager.py           ← RiskManager: daily loss check, position size
│   │   ├── capital_allocator.py      ← CapitalAllocator: splits capital
│   │   └── trailing_stop_manager.py  ← TrailingStopManager: ATR-based trailing stops
│   │
│   ├── execution/
│   │   ├── paper_executor.py         ← PaperExecutor (full, with position tracking)
│   │   └── openalgo_executor.py      ← OpenAlgoExecutor (live)
│   │
│   ├── reporting/
│   │   ├── agent_performance.py      ← AgentPerformanceTracker (JSON-backed leaderboard)
│   │   ├── telegram_reporter.py      ← TelegramReporter + TelegramCommandHandler
│   │   ├── email_reporter.py         ← EmailReporter
│   │   ├── pdf_generator.py          ← PDFReportGenerator
│   │   └── scheduler.py              ← ReportScheduler (daily 8PM, weekly)
│   │
│   └── monitoring/
│       ├── __init__.py               ← live_state dict + update()/read() helpers
│       └── state.py                  ← in-memory status.json writer
│
├── dashboard/
│   ├── server.py                     ← Flask: serves /api/status, /api/stock/<sym>
│   ├── dashboard.html                ← main dashboard UI
│   └── index.html                    ← NEW: clean dashboard with TA/FA tabs
│
├── logs/
│   ├── alphazero.log                 ← rolling log
│   ├── status.json                   ← live state (polled by dashboard)
│   └── reports/                      ← PDF + CSV reports
│
└── models/
    └── nexus_regime.json             ← XGBoost model (optional, auto-trains)
```


## ═══════════════════════════════════════════════
## HOW AUTONOMOUS STOCK SELECTION WORKS
## ═══════════════════════════════════════════════

The system scans ALL 50 NIFTY stocks every iteration.
SYMBOLS in settings.py is just the initial universe — it is NOT the 
portfolio. The pipeline works like this:

```
ORACLE.analyze()          → macro_context {vix, bias, size_mult}
         ↓
NEXUS.detect_regime()     → "TRENDING" | "SIDEWAYS" | "VOLATILE" | "RISK_OFF"
         ↓
HERMES.get_sentiment()    → per-symbol sentiment scores
         ↓
DataFetcher.get_ohlcv()   → real-time prices + indicators for all 50 stocks
         ↓
SIGMA.score_stocks()      → 8-factor score for EACH of 50 stocks
   Factors: momentum, trend_strength, earnings_quality, relative_strength,
            news_sentiment, volume_confirm, low_volatility, fii_interest
   Weights: shift by regime (TRENDING → momentum + trend weighted up)
         ↓
CHIEF.select_portfolio()  → top 5 stocks, max 2 per sector, capital-weighted
         ↓
TITAN.generate_signals()  → runs 45 strategies on selected stocks
         ↓
MTF filter                → 4/5 timeframes must agree
         ↓
GUARDIAN.check_trade()    → risk limits (daily loss, position size, sector)
         ↓
MERCURY.execute_trade()   → paper fill with slippage model
         ↓
KARMA.learn_from_outcome() → adjusts weights on stop/target
```

Paper mode vs Live mode:
- EVERYTHING above runs identically
- Only difference: MERCURY routes to PaperExecutor vs OpenAlgoExecutor
- PaperExecutor tracks real P&L, real slippage, real positions


## ═══════════════════════════════════════════════
## AGENT REFERENCE TABLE
## ═══════════════════════════════════════════════

| Key in agents{} | Class            | File                        | KPI                      |
|-----------------|------------------|-----------------------------|--------------------------|
| CHIEF           | ChiefAgent       | chief_agent.py              | Sharpe > 1.5 quarterly   |
| SIGMA           | SigmaAgent       | sigma_agent.py              | Beats NIFTY50 by 5%      |
| ATLAS           | SectorAgent      | sector_agent.py             | Sector outperforms       |
| ORACLE          | OracleAgent      | oracle_agent.py             | Macro accuracy > 65%     |
| NEXUS           | IntradayRegime.. | intraday_regime_agent.py    | Regime accuracy > 75%    |
| HERMES          | NewsSentiment..  | news_sentiment_agent.py     | F1 > 0.70                |
| TITAN           | TitanAgent       | titan_agent.py              | Precision > 58%          |
| GUARDIAN        | GuardianAgent    | guardian_agent.py           | Drawdown never > 8%      |
| MERCURY         | MercuryAgent     | mercury_agent.py            | Slippage < 0.15%         |
| LENS            | LensAgent        | lens_agent.py               | Daily report by 8PM IST  |
| KARMA           | KarmaAgent       | karma_agent.py              | Sharpe +2% monthly       |
| OPTIONS_FLOW    | OptionsFlowAgent | options_flow_agent.py       | Smart-money detection    |
| MULTI_TIMEFRAME | MultiTimeframe.. | multi_timeframe_agent.py    | 4/5 TF agreement         |
| EARNINGS_ANLZR  | EarningsAnalyzer | llm_earnings_analyzer.py    | Earnings alpha           |
| STRATEGY_GEN    | StrategyGenerator| llm_strategy_generator.py   | Pattern discovery        |
| TRAILING_STOP   | TrailingStopMgr  | trailing_stop_manager.py    | Locks profits            |


## ═══════════════════════════════════════════════
## QUICK FIX CHECKLIST
## ═══════════════════════════════════════════════

Run this in your repo root to remove all shadow stubs:

```bash
# Step 1: Delete shadow stubs (replace with correct files from patches/)
git rm src/agents/chief_agent.py         # will be replaced
git rm src/agents/sector_agent.py        # will be replaced  
git rm src/agents/intraday_regime_agent.py
git rm src/agents/news_sentiment_agent.py

# Step 2: Copy correct files from the patches folder
cp patches/chief_agent.py          src/agents/chief_agent.py
cp patches/intraday_regime_agent.py src/agents/intraday_regime_agent.py
cp patches/news_sentiment_agent.py  src/agents/news_sentiment_agent.py
cp patches/main.py                  main.py

# Step 3: Verify no stray event_bus stub
# The real event_bus.py has: class BaseAgent, heapq priority queue, start/stop
grep "class BaseAgent" src/event_bus/event_bus.py  # must print a match

# Step 4: Check requirements
pip install yfinance pandas numpy requests flask

# Step 5: Run paper engine
python run_paper.py
# or the full system:
python main.py
```


## ═══════════════════════════════════════════════
## .ENV TEMPLATE
## ═══════════════════════════════════════════════

```bash
# Mode
MODE=PAPER                       # PAPER or LIVE

# Capital
INITIAL_CAPITAL=1000000          # ₹10 lakh

# Risk
MAX_DAILY_LOSS_PCT=0.02          # Stop at -2% daily
MAX_POSITION_SIZE_PCT=0.05       # Max 5% per position
MAX_POSITIONS=5                  # Max 5 open positions
MAX_TRADES_PER_DAY=20

# Execution (LIVE only)
OPENALGO_HOST=http://localhost:5000
OPENALGO_API_KEY=your_key_here

# Telegram alerts (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# LLM (optional, for earnings analyzer)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# Dashboard
DASHBOARD_PORT=8080
DASHBOARD_HOST=localhost
```
