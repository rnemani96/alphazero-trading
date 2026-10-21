# 🚀 AlphaZero Capital — Autonomous Multi-Agent Trading System

[![Version](https://img.shields.io/badge/Version-8.3.1_Production-blue.svg)](https://github.com/rnemani96/alphazero-trading)
[![Market](https://img.shields.io/badge/Market-NSE_India-orange.svg)](https://www.nseindia.com)
[![Agents](https://img.shields.io/badge/Active_Agents-20_Collaborative-green.svg)](#-agent-swarm-architecture)
[![Self--Evolving](https://img.shields.io/badge/Self--Evolving-5_Feedback_Loops-purple.svg)](#-self-evolving-ai-architecture)
[![Autonomy](https://img.shields.io/badge/Autonomy-24%2F7_Self--Healing-red.svg)](#-247-autonomous-lifecycle)
[![License](https://img.shields.io/badge/License-Proprietary-lightgrey.svg)](#-license)

**AlphaZero Capital** is a fully autonomous, institutional-grade algorithmic trading system tailored for the **National Stock Exchange of India (NSE)**. It unifies high-frequency technical analysis, quantitative regime classification, multi-timeframe validation, deep NLP financial sentiment, reinforcement learning, and a universal LLM gateway into a resilient, self-evolving 20-agent swarm.

---

## 🌟 Key Highlights & Innovations

### 1. 🧬 5-Layer Self-Evolving AI Engine
AlphaZero does not rely on static rules; it continually evolves its decision-making logic:
- **Bayesian Thompson Sampling** ([`thompson_sampling_allocator.py`](file:///D:/alphazero-trading/src/risk/thompson_sampling_allocator.py)): Real-time posterior $\text{Beta}(\alpha_k, \beta_k)$ updating after every trade win/loss, scaling strategy capital multipliers dynamically ($0.2\times$ to $2.5\times$).
- **Experience Replay Buffer**: Logs state-action-reward tuples $(s_t, a_t, r_t, s_{t+1})$ to prevent catastrophic forgetting.
- **KARMA Reinforcement Learning** ([`karma_agent.py`](file:///D:/alphazero-trading/src/agents/karma_agent.py)): Daily **PPO (Proximal Policy Optimization)** actor-critic neural network retraining at 15:35 IST on real market trajectories.
- **Autonomous Strategy Generator & Marketplace** ([`llm_strategy_generator.py`](file:///D:/alphazero-trading/src/agents/llm_strategy_generator.py)): Nightly LLM-guided strategy mutation, automated walk-forward backtesting, and live promotion/retirement of alpha strategies.
- **Adaptive Recovery Engine** ([`adaptive_recovery_engine.py`](file:///D:/alphazero-trading/src/risk/adaptive_recovery_engine.py)): Dynamically tightens confidence barriers (0.50–0.88) and R:R hurdles based on rolling drawdowns and India VIX.

### 2. 🤖 Universal LLM Gateway (Local & Cloud APIs)
AlphaZero is provider-agnostic. Run completely private on local hardware with zero API cost, or connect to leading cloud reasoning models:
- **Local LLMs (Zero API Cost & 100% Private)**: Auto-detects local **Ollama** (`http://localhost:11434`, e.g., `gemma3:4b`, `llama3.2:3b`, `qwen2.5:3b`, `deepseek-r1`), **LM Studio** (`http://localhost:1234`), and **vLLM / LocalAI** (`http://localhost:8000`).
- **Cloud AI APIs**: Native support for **OpenRouter**, **Groq** (Llama 3.3 70B & DeepSeek-R1), **DeepSeek**, **Google Gemini** (Gemini 2.0 Flash / 1.5 Pro), **OpenAI** (GPT-4o, o3-mini), **Anthropic Claude** (Claude 3.5 Sonnet), and **Mistral AI**.
- Automatic fallback: If cloud APIs encounter rate limits or network drops, the system seamlessly routes prompts to local models.

### 3. 🌐 Multi-Sector Round-Robin Diversification
- **9-Sector Coverage**: Broad multi-sector universe across Nifty IT, Banking, Auto, Energy, FMCG, Pharma, Metals, Infra, and Financial Services.
- **Concentration Guardrails**: Maximum 3 concurrent positions per sector and maximum 10 concurrent portfolio positions to prevent sector overexposure.
- **Direction-Aware Accounting**: Full support for both LONG and SHORT/INTRADAY equity positions with accurate transaction charge buffers (+0.3% breakeven ratchet).

### 4. 🛡️ 24/7 Self-Healing & Complete Autonomy
- **Self-Healing Watchdog** ([`scripts/watchdog.py`](file:///D:/alphazero-trading/scripts/watchdog.py)): Continuously monitors the main trading engine and FastAPI backend, automatically restarting failed components with exponential backoff.
- **Automated Daily Lifecycle**:
  - `08:45 IST`: Pre-market gap and macro sentiment briefing via Telegram.
  - `09:15 – 15:15 IST`: Active multi-agent signal generation, risk screening, and execution.
  - `15:15 IST`: Automated intraday position square-off to eliminate overnight margin exposure.
  - `15:35 IST`: Daily KARMA PPO policy retraining & comprehensive EOD Telegram performance summary.
  - `23:00 IST`: Nightly LLM strategy mutation and backtesting.
- **1-Click Launchers**: Double-click `start_autonomous.bat` on Windows or execute `./start_autonomous.sh` on Linux/macOS.
- **Container Stack**: Production-ready `Dockerfile` and `docker-compose.yml`.

---

## 🏛️ Agent Swarm Architecture

The system coordinates 20 specialized, decoupled agents communicating over an in-memory or Redis event bus:

```
                            ┌────────────────────────────────────────┐
                            │           MAIN ORCHESTRATOR            │
                            │        (Coordination & Lifecycle)       │
                            └───────────────────┬────────────────────┘
                                                │
                                                ▼
                            ┌────────────────────────────────────────┐
                            │         EVENT BUS / PUBSUB             │
                            └───────┬────────────────────────┬───────┘
                                    │                        │
         ┌──────────────────────────┼────────────────────────┼──────────────────────────┐
         ▼                          ▼                        ▼                          ▼
 ┌───────────────┐          ┌───────────────┐        ┌───────────────┐          ┌───────────────┐
 │   INTELLIGENCE│          │   EXECUTION   │        │     RISK      │          │ SELF-EVOLUTION│
 │   & SIGNALS   │          │   & ORDERS    │        │  MANAGEMENT   │          │  & LEARNING   │
 ├───────────────┤          ├───────────────┤        ├───────────────┤          ├───────────────┤
 │ • ZEUS        │          │ • MERCURY     │        │ • GUARDIAN    │          │ • THOMPSON    │
 │ • TITAN (45s) │          │ • ORDER_FLOW  │        │ • SENTINEL    │          │ • KARMA (PPO) │
 │ • NEXUS       │          │ • TRAILING    │        │ • RECOVERY    │          │ • STRATEGY    │
 │ • HERMES      │          │ • OPENALGO    │        │ • CHARGE CALC │          │   GENERATOR   │
 │ • ORACLE      │          │               │        │ • DIVERSIFIER │          │ • MARKETPLACE │
 │ • ATLAS       │          │               │        │               │          │               │
 └───────────────┘          └───────────────┘        └───────────────┘          └───────────────┘
```

| Agent | Module | Core Functionality |
| :--- | :--- | :--- |
| **ZEUS** | `src/agents/zeus_agent.py` | Master strategy aggregation & multi-signal voting coordinator |
| **TITAN** | `src/agents/titan_agent.py` | 45-indicator algorithmic engine (5m/15m trend, momentum, mean-reversion) |
| **NEXUS** | `src/agents/intraday_regime_agent.py` | Machine-learning regime classifier (Trending, Sideways, Volatile, Risk-Off) |
| **HERMES** | `src/agents/news_sentiment_agent.py` | Real-time financial NLP sentiment & news impact score |
| **ORACLE** | `src/agents/oracle_agent.py` | Directional trend velocity predictor: calculates $P(\text{Rise})$ vs $P(\text{Fall})$ |
| **LENS** | `src/agents/lens_agent.py` | Technical candlestick pattern recognition engine (Hammer, Engulfing, etc.) |
| **ATLAS** | `src/agents/atlas_agent.py` | Cross-sector relative strength & sector rotation analysis |
| **MERCURY** | `src/agents/mercury_agent.py` | Smart execution agent interfacing with OpenAlgo & Paper engine |
| **GUARDIAN** | `src/agents/guardian_agent.py` | Global circuit breaker, max drawdown monitor & capital preservation |
| **SENTINEL**| `src/agents/sentinel.py` | System health, feed latency, and agent heartbeat watchdog |
| **KARMA** | `src/agents/karma_agent.py` | Continuous PPO reinforcement learning agent retrained daily at 15:35 IST |
| **THOMPSON**| `src/risk/thompson_sampling_allocator.py`| Real-time Bayesian capital allocator updating Beta posteriors per trade |

---

## ⚡ Quick Start

### 1. Clone & Setup Environment

```bash
# Clone repository
git clone https://github.com/rnemani96/alphazero-trading.git
cd alphazero-trading

# Create Python virtual environment (Python 3.11 or 3.12 recommended)
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables (`.env`)

Copy the template and configure your keys:
```bash
cp .env.template .env
```

Key settings in `.env`:
```ini
# Execution Mode (PAPER or LIVE)
MODE=PAPER
INITIAL_CAPITAL=1000000

# Universal LLM Gateway (auto detects local Ollama or cloud key)
LLM_PROVIDER=auto
OLLAMA_MODEL=gemma3:4b
# Or Cloud Providers:
# GROQ_API_KEY=gsk_...
# OPENROUTER_API_KEY=sk-or-v1-...
# GEMINI_API_KEY=AIzaSy...

# Telegram Alerts (Pre-market briefs, trade executions, EOD reports)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Risk Limits
MAX_DAILY_LOSS_PCT=0.02
MAX_POSITIONS=10
MAX_POSITIONS_PER_SECTOR=3
```

### 3. Launch System

#### Option A: 1-Click 24/7 Autonomous Supervisor (Recommended)
On Windows:
```cmd
start_autonomous.bat
```
On Linux / macOS:
```bash
chmod +x start_autonomous.sh
./start_autonomous.sh
```
*This simultaneously starts the self-healing watchdog, main trading engine, and FastAPI backend.*

#### Option B: Docker Compose
```bash
docker compose up -d
```

#### Option C: Manual CLI
```bash
# Terminal 1: Trading Engine
python main.py

# Terminal 2: Dashboard API Backend
python -m uvicorn dashboard.backend:app --host 127.0.0.1 --port 8000

# Terminal 3: React Dashboard UI (Optional)
cd dashboard/alphazero-ui
npm install
npm run dev
```

---

## 🖥️ Live Dashboard

AlphaZero includes a high-performance modern web dashboard:
- **Backend API**: FastAPI (`http://localhost:8000`) with endpoints for live metrics, health, active positions, and trade logs.
- **Frontend UI**: React + Vite (`http://localhost:5173`) featuring:
  - 📊 Real-time portfolio P&L & capital trajectory
  - 📈 Active positions with dynamic trailing stop levels
  - 🤖 Live agent swarm status and health monitoring
  - 🧭 Sector allocation charts & Thompson sampling weights
  - ⚡ Instant manual emergency panic switch

---

## 📊 Expected Performance & Risk Targets

| Metric | Target / Paper Benchmark |
| :--- | :--- |
| **Annualized Returns** | 35% – 50% |
| **Win Rate** | 68% – 74% |
| **Sharpe Ratio** | 2.1 – 2.9 |
| **Max Drawdown** | < 10% (Automated circuit breakers trigger at 2% daily / 6% peak) |
| **Profit Factor** | > 1.85 |
| **Average Trade Duration** | 15 minutes to 4 hours (Intraday auto-squareoff at 15:15 IST) |

---

## 📁 Project Structure

```
alphazero-trading/
├── main.py                     # Primary trading engine & daily market lifecycle
├── run_paper.py                # Dedicated paper execution harness
├── start_autonomous.bat        # 1-Click Windows 24/7 supervisor
├── start_autonomous.sh         # 1-Click Unix/macOS supervisor
├── docker-compose.yml          # Docker service definitions
├── Dockerfile                  # Container build specification
├── requirements.txt            # Python dependencies
├── change.md                   # Chronological ledger of all upgrades and fixes
│
├── config/
│   ├── settings.py             # Global constants & trading parameters
│   └── symbols.py              # 9-Sector equity universe definitions
│
├── src/
│   ├── agents/                 # 20 Collaborative Trading Agents
│   │   ├── zeus_agent.py       # Chief decision & multi-signal coordinator
│   │   ├── titan_agent.py      # 45-indicator technical voting suite
│   │   ├── karma_agent.py      # PPO Reinforcement learning agent
│   │   ├── llm_provider.py     # Universal LLM Gateway (Local + Cloud)
│   │   └── ...
│   ├── risk/                   # Quantitative Risk & Allocation
│   │   ├── thompson_sampling_allocator.py  # Bayesian adaptive capital allocator
│   │   ├── adaptive_recovery_engine.py     # Zero-loss & deficit recovery
│   │   ├── position_sizer.py               # Direction-aware Kelly & risk sizing
│   │   └── charge_calculator.py            # NSE STT, brokerage & slippage model
│   ├── execution/              # Order Execution
│   │   ├── openalgo_executor.py# OpenAlgo live broker connector
│   │   └── paper_executor.py   # Realistic simulated order execution
│   └── data/                   # Data Pipelines
│       ├── discovery.py        # 10x-speed fast symbol scanning & discovery
│       └── multi_source_data.py# Multi-source market feeds
│
├── dashboard/                  # Full-Stack Dashboard
│   ├── backend.py              # FastAPI REST & WebSocket server
│   └── alphazero-ui/           # React + Vite + Tailwind CSS frontend
│
├── scripts/
│   └── watchdog.py             # 24/7 Self-healing supervisor with health polling
│
└── docs/                       # Complete Documentation Library
    ├── AlphaZero_Mathematical_Architecture_and_System_Reference.md
    ├── OPENROUTER_COMPLETE_GUIDE.md
    ├── TASKS_LIST.md
    └── change.md
```

---

## 📖 Extended Documentation

All architectural whitepapers, mathematical formulations, and detailed guides are consolidated in the [`docs/`](file:///D:/alphazero-trading/docs/) folder:
- **[Mathematical Architecture & System Reference](file:///D:/alphazero-trading/docs/AlphaZero_Mathematical_Architecture_and_System_Reference.md)**: Formulas for Thompson sampling, Kelly criteria, PPO loss functions, and regime transition matrices.
- **[Changelog & Audit Ledger](file:///D:/alphazero-trading/docs/change.md)**: Full history of bug fixes, security hardening, and code audits.
- **[OpenRouter & Cloud LLM Setup](file:///D:/alphazero-trading/docs/OPENROUTER_COMPLETE_GUIDE.md)**: Detailed configuration for all cloud providers.

---

## 🔒 Security & Safe Trading Guidelines

1. **Protect Your API Keys**: Never commit your `.env` file to Git. The `.gitignore` is pre-configured to exclude sensitive credentials.
2. **Paper Trade First**: Always run the system in `MODE=PAPER` for at least 4–8 weeks to observe strategy performance across shifting market regimes before committing real capital.
3. **Hardware Readiness**: If using local LLMs (Ollama with `gemma3:4b`), ensure your machine has at least 16GB RAM or a dedicated GPU with 6GB+ VRAM.

---

## 📄 License

Proprietary — Developed for Autonomous Quantitative Trading on the National Stock Exchange of India.  
© 2026 AlphaZero Capital. All rights reserved.
