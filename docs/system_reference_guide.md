# AlphaZero Capital — System Reference Guide

> This guide is based on the **Version 4.0 (2026-03-21)** release.

## 1. Core Orchestration
| File | Role | Key Methods / Functions |
| :--- | :--- | :--- |
| `main.py` | **Master Orchestrator** | `_aggregate_signals()`: Merges TITAN+NEXUS+HERMES scores.<br>`_update_positions()`: Manages TSL and closes trades.<br>`_fetch_market_data()`: Orchestrates bulk downloads.<br>`_write_state()`: Performs **Atomic Safe-Writes** to JSON. |
| `src/event_bus/event_bus.py` | **Nervous System** | `EventBus.publish()`: Dispatches prioritized events.<br>`EventBus.subscribe()`: Registers agent listeners.<br>`BaseAgent.publish_event()`: Standardized agent emitter. |
| `src/infra/sanity_check.py` | **Startup Safety** | `StartupSanityCheck.run()`: Verifies API keys, Redis, and data paths. |

## 2. Market Intelligence (Agents)
| File | Agent | Key Methods |
| :--- | :--- | :--- |
| `src/agents/titan_agent.py` | **TITAN** | `generate_signals()`: Runs 45 strategies in parallel.<br>`_get_dynamic_thresholds()`: Adjusts confidence by regime.<br>`_process_symbol()`: Aggregates technical indicators. |
| `src/titan.py` | **Strategy Engine** | `compute_all()`: The math behind all 45 strategies.<br>`_compute_base()`: Calculates EMAs, RSI, MACD, VWAP via NumPy. |
| `src/agents/chief_agent.py` | **CHIEF** | `select_portfolio()`: Builds final portfolio from candidates.<br>`_sector_diversify()`: Ensures max 30% exposure per sector. |
| `src/agents/sigma_agent.py` | **SIGMA** | `score_stocks()`: 8-factor scoring (Momentum, Vol, etc.).<br>`_calculate_score()`: Regime-weighted composite index. |
| `src/agents/intraday_regime_agent.py` | **NEXUS** | `detect_regime()`: Classifies TRENDING / SIDEWAYS / VOLATILE.<br>`load_xgb_model()`: Loads XGBoost model for 75%+ accuracy. |
| `src/agents/news_sentiment_agent.py` | **HERMES** | `analyze_sentiment()`: Scores news via FinBERT/Lexicons. |
| `src/agents/earnings_calendar_agent.py` | **EARNINGS** | `check_pre_earnings_momentum()`: (S44) Pre-results runup.<br>`check_post_earnings_gap()`: (S45) Post-results breakout. |

## 3. Risk & Execution
| File | Role | Key Methods |
| :--- | :--- | :--- |
| `src/agents/guardian_agent.py` | **The Sentry** | `check_trade()`: Final gatekeeper for ALL trades.<br>`_compute_sl_target()`: ATR-based stop-loss and 3:1 R:R.<br>`_compute_position_size()`: **Kelly + ATR** conservative sizing. |
| `src/agents/mercury_agent.py` | **Trade Link** | `execute_signals()`: Relays approved signals to executors.<br>`modify_order()`: Updates trailing stops on the broker. |
| `src/execution/paper_executor.py` | **SIM Engine** | `execute_trade()`: Virtual fills with slippage simulation. |
| `src/execution/order_manager.py` | **Order State** | `track_order()`: Syncs local state with broker responses. |

## 4. Data Acquisition
| File | Role | Key Methods |
| :--- | :--- | :--- |
| `src/data/discovery.py` | **Scanner** | `get_best_performing_stocks()`: Scans Nifty 500 for momentum. |
| `src/data/multi_source_data.py` | **Data Pipe** | `get_bulk_quotes()`: High-speed parallel yfinance downloader. |
| `src/data/indicators.py` | **Calculations** | `add_all_indicators()`: Vectorized TA calculations for pandas. |

## 5. Monitoring & Dashboard
| File | Role | Key Methods |
| :--- | :--- | :--- |
| `dashboard/backend.py` | **Web Server** | `create_app()`: FastAPI server for the UI.<br>`websocket_endpoint()`: Real-time status push to dashboard. |
| `src/monitoring/state.py` | **In-Memory Store** | `update()` / `read()`: Thread-safe state sharing between agents. |
| `src/monitoring/audit_log.py` | **Compliance** | `log_trade()`: SEBI-compliant SQLite audit trail. |

---

### Critical Logic Flows

1. **Signal Generation**: `DISCOVERY` (Scanning) → `TITAN` (45 Technicals) + `SIGMA` (Ranking) + `HERMES` (Sentiment) → `main.py` (`_aggregate_signals`).
2. **Safety Gate**: `AGGREGATE` → `GUARDIAN` (`check_trade`) → `MERCURY` (Execution).
3. **Live Monitoring**: `MERCURY` → `EXECUTION` → `main.py` (`_update_positions`) → `STATE` → **Dashboard WebSockets**.
4. **Error Handling**: `ZEUS` (Health Cycle) detects agent hangs and attempts restart via `SENTINEL`.

---

> **Tip:** Keep this document handy during trading hours. If the system stops generating signals, check `main.py` line 451 (`_aggregate_signals`) and `GuardianAgent` line 112 (`check_trade`) first, as these are the most common "hard gates."
