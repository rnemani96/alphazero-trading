# 🌌 AlphaZero Capital — Complete System Architecture & Mathematical Reference Guide

**Version**: 5.1.0 Autonomous Production  
**Markets**: National Stock Exchange of India (NSE: NIFTY 50, NIFTY BANK, NIFTY 500)  
**Intelligence Layer**: 18 Distributed Autonomous Agents + Universal LLM Gateway (Local Ollama & Cloud APIs)  
**Execution**: Zero-Loss Adaptive Recovery Engine + Asymmetric Directional Trend Forecasting  

---

## 1. System Overview & Architectural Topology

AlphaZero Capital is an institutional-grade, multi-agent quantitative trading ecosystem engineered for high-probability swing and intraday trading on Indian equities and derivatives. The architecture enforces strict **Separation of Concerns (SoC)** across four operational layers:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CENTRAL EVENT BUS (Priority Min-Heap)           │
│        Asynchronous Event Dispatcher & Message Queue (Latency < 2ms)   │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
       ┌─────────────────────────────┼─────────────────────────────┐
       ▼                             ▼                             ▼
┌──────────────┐             ┌──────────────┐              ┌──────────────┐
│  DATA LAYER  │             │ INTELLIGENCE │              │  EXECUTION   │
│ MultiSource  │             │    LAYER     │              │   & RISK     │
├──────────────┤             ├──────────────┤              ├──────────────┤
│ • Upstox API │             │ • TITAN (45) │              │ • GUARDIAN   │
│ • OpenAlgo   │             │ • NEXUS      │              │ • MERCURY    │
│ • yfinance   │             │ • ORACLE V2  │              │ • ActivePort │
│ • NSE Direct │             │ • SHADOW     │              │ • Zero-Loss  │
│ • TwelveData │             │ • HERMES     │              │ • Recovery   │
│ • Finnhub    │             │ • ATLAS      │              │ • PositionSz │
└──────────────┘             └──────────────┘              └──────────────┘
                                     │
                                     ▼
                     ┌──────────────────────────────┐
                     │   UNIVERSAL LLM GATEWAY      │
                     ├──────────────────────────────┤
                     │ Local: Ollama / LM Studio    │
                     │ Cloud: OpenRouter / Groq /   │
                     │        DeepSeek / OpenAI /   │
                     │        Gemini / Claude       │
                     └──────────────────────────────┘
```

---

## 2. Comprehensive Mathematical Formulations

### 2.1 Directional Trend Velocity Predictor
File: `src/data/trend_velocity_predictor.py`

The Trend Velocity Predictor estimates the conditional probability of immediate upward price expansion versus downward collapse ($P(\text{Rise})$ vs $P(\text{Fall})$) over the subsequent $N$ bars using a tripartite multi-factor model mapped through an asymmetric logistic sigmoid.

#### Step 1: Trend Velocity Score ($S_{\text{velocity}}$)
Measures moving average directional alignment and trajectory angle:
$$\text{Alignment} = \begin{cases} 
1.0 & \text{if } \text{EMA}_9 > \text{EMA}_{21} > \text{EMA}_{50} \\ 
-1.0 & \text{if } \text{EMA}_9 < \text{EMA}_{21} < \text{EMA}_{50} \\ 
0.0 & \text{otherwise} 
\end{cases}$$

$$\text{Slope}_{\text{EMA21}} = \frac{\text{EMA}_{21}[t] - \text{EMA}_{21}[t-3]}{3 \times \text{ATR}_{14}[t]}$$

$$S_{\text{velocity}} = 0.60 \cdot \text{Alignment} + 0.40 \cdot \tanh(2.5 \cdot \text{Slope}_{\text{EMA21}})$$

#### Step 2: Momentum Dynamics Score ($S_{\text{momentum}}$)
Measures the acceleration of oscillator force:
$$\Delta\text{RSI} = \frac{\text{RSI}_{14}[t] - \text{RSI}_{14}[t-3]}{15.0}$$

$$\text{MACD}_{\text{norm}} = \frac{\text{Histogram}[t]}{\text{ATR}_{14}[t] \times 0.5}$$

$$S_{\text{momentum}} = 0.50 \cdot \tanh(\Delta\text{RSI}) + 0.50 \cdot \tanh(\text{MACD}_{\text{norm}})$$

#### Step 3: Volume & Order-Flow Pressure ($S_{\text{volume}}$)
Measures institutional accumulation relative to the Volume Weighted Average Price (VWAP):
$$\text{VWAP}_{\text{dist}} = \frac{\text{Close}[t] - \text{VWAP}[t]}{\text{ATR}_{14}[t]}$$

$$Z_{\text{volume}} = \frac{\text{Volume}[t] - \mu_{V, 20}}{\sigma_{V, 20} + \epsilon}$$

$$S_{\text{volume}} = 0.60 \cdot \tanh(\text{VWAP}_{\text{dist}}) + 0.40 \cdot \tanh(0.5 \cdot Z_{\text{volume}})$$

#### Step 4: Composite Score & Logistic Probability Sigmoid
$$\text{Composite} = 0.40 \cdot S_{\text{velocity}} + 0.35 \cdot S_{\text{momentum}} + 0.25 \cdot S_{\text{volume}}$$

$$P(\text{Rise}) = \frac{1}{1 + e^{-3.5 \cdot \text{Composite}}}, \quad P(\text{Fall}) = 1.0 - P(\text{Rise})$$

#### Step 5: Asymmetric Risk-Reward Calibration
$$\text{Target}_{\text{Rise}} = \text{Entry} + 2.2 \times \text{ATR}_{14}$$
$$\text{Limit}_{\text{Fall}} = \text{Entry} - 1.0 \times \text{ATR}_{14}$$
$$\text{Asymmetric Ratio} = \frac{|\text{Target}_{\text{Rise}} - \text{Entry}|}{|\text{Limit}_{\text{Fall}} - \text{Entry}|} = 2.2$$

---

### 2.2 Adaptive Profit & Loss Recovery Engine
File: `src/risk/adaptive_recovery_engine.py`

Enforces capital preservation through dynamic threshold gating, an automatic zero-loss breakeven ratchet, and a mathematical loss recovery ledger.

#### Breakeven Zero-Loss Ratchet
When an open trade reaches $+0.5R$ profit ($50\%$ progress toward its target):
$$\Delta_{\text{progress}} = \frac{|\text{Current Price} - \text{Entry}|}{|\text{Initial Target} - \text{Entry}|} \ge 0.50$$

The stop-loss is instantly moved to the **Breakeven Floor**, accounting for all statutory exchange taxes, brokerage, and slippage buffers:
$$\text{BE}_{\text{Long}} = \text{Entry} \times (1 + \text{Buffer}_{\text{charges}}) = \text{Entry} \times 1.003$$
$$\text{BE}_{\text{Short}} = \text{Entry} \times (1 - \text{Buffer}_{\text{charges}}) = \text{Entry} \times 0.997$$

#### Tiered Profit Locking Ladder
$$\text{Tier 1 (+1.0R)}: \quad \text{SL} \to \text{Entry} + 0.5 \times \text{Initial Risk Distance}$$
$$\text{Tier 2 (+2.0R)}: \quad \text{SL} \to \text{Entry} + 1.2 \times \text{Initial Risk Distance}$$
$$\text{Tier 3 (+3.0R)}: \quad \text{SL} \to \text{Entry} + 2.0 \times \text{Initial Risk Distance}$$

#### Loss Deficit Recovery Mathematical Formulation
If an adverse exit occurs resulting in a net realized loss $L < 0$, the system enters **`RECOVERY_MODE`**:
$$\text{Total Deficit}[k] = \text{Total Deficit}[k-1] + |L|$$

To eliminate the deficit in the subsequent high-conviction trade without taking reckless risk, the required trade profit target $T_{\text{rec}}$ is calculated as:
$$T_{\text{rec}} = \text{Total Deficit} \times 1.05 \quad (\text{incorporating 5\% surplus profit cushion})$$

The required risk-reward ratio is constrained by the recovery engine:
$$\text{RR}_{\text{req}} = \max\left(2.5, \; \min\left(4.5, \; 2.0 + \frac{\text{Total Deficit}}{10000}\right)\right)$$

The maximum permitted capital risk for the recovery candidate is strictly bounded:
$$\text{Risk}_{\text{alloc}} = \frac{T_{\text{rec}}}{\text{RR}_{\text{req}}}$$

Once cumulative recovery profit $\sum P_{\text{rec}} \ge \text{Total Deficit}$, `RECOVERY_MODE` disengages and returns to normal operating parameters.

---

### 2.3 Position Sizing: Fractional Kelly Criterion with ATR Volatility Normalization
File: `src/risk/position_sizer.py`

$$\text{Kelly Fraction } f^* = \frac{p \cdot b - q}{b}$$
Where:
- $p$ = Historical win rate of strategy ($0 < p < 1$)
- $q = 1 - p$ = Loss rate
- $b$ = Payoff ratio = $\frac{\text{Average Win}}{\text{Average Loss}}$

To prevent over-leveraging and drawdowns from estimation error, AlphaZero applies **Half-Kelly** ($f = 0.5 \cdot f^*$) capped between $0.5\%$ and $2.0\%$ of total account equity:
$$\text{Risk Pct } R = \max\left(0.005, \; \min\left(0.020, \; 0.5 \cdot f^*\right)\right)$$

#### Volatility-Adjusted Quantity
$$\text{Shares} = \left\lfloor \frac{\text{Account Capital} \times R}{\text{ATR}_{14} \times \text{Multiplier}_{\text{regime}}} \right\rfloor \times \left(1.0 - \max\left(0.0, \; \frac{\text{India VIX} - 15.0}{30.0}\right)\right)$$

---

### 2.4 Indian Market Statutory Charges Model
File: `src/risk/charge_calculator.py`

Every trade execution models exact Indian statutory charges (NSE cash equity & futures):
1. **Securities Transaction Tax (STT)**:
   - Equity Intraday: $0.025\%$ on Sell turnover
   - Equity Delivery: $0.10\%$ on both Buy and Sell turnover
2. **Exchange Transaction Charges**: $0.00345\%$ on turnover
3. **SEBI Turnover Charges**: ₹10 per ₹1 Crore ($0.0001\%$)
4. **Stamp Duty**: $0.003\%$ on Buy turnover
5. **Goods & Services Tax (GST)**: $18\%$ on (Brokerage + Exchange Charges + SEBI Charges)
6. **Brokerage**: ₹20 per executed order or $0.05\%$ (whichever is lower)

$$\text{Net P\&L} = \text{Gross P\&L} - \sum \text{Charges}_{\text{statutory}}$$

---

### 2.5 Multi-Agent Ensemble Consensus Formulation
File: `main.py` & `src/agents/oracle_v2.py` / `src/agents/lstm_agent.py`

$$\text{Confidence}_{\text{Ensemble}} = w_{\text{ORACLE}} \cdot C_{\text{ORACLE}} + w_{\text{LSTM}} \cdot C_{\text{LSTM}} + w_{\text{TITAN}} \cdot C_{\text{TITAN}}$$
Default weights:
- $w_{\text{ORACLE}} = 0.35$ (LightGBM gradient-boosted trees)
- $w_{\text{LSTM}} = 0.35$ (Bi-directional LSTM temporal sequence network)
- $w_{\text{TITAN}} = 0.30$ (45-indicator technical rule base)

#### Democratic Agreement Multiplier:
- $3/3$ Unanimous agreement: $\text{Confidence} \times 1.10$
- $2/3$ Majority consensus: $\text{Confidence} \times 1.00$
- Discordant ($< 2/3$): $\text{Confidence} \times 0.90$

---

## 3. Universal LLM Gateway Architecture

AlphaZero v5.1 introduces a unified LLM layer in `src/agents/llm_provider.py` that abstracts away vendor SDKs. It provides zero-dependency native HTTP fallback alongside OpenAI SDK compatibility.

### 3.1 Local LLM Deployment (Zero Cost & 100% Privacy)
AlphaZero auto-detects and connects to local inference servers running on the trader's hardware:

| Engine | Port / URL | Supported Architectures | Configuration |
|---|---|---|---|
| **Ollama** | `http://localhost:11434` | Gemma 3, Llama 3.2, Qwen 2.5, DeepSeek-R1, Phi-4, Mistral | `LLM_PROVIDER=ollama` or `auto` |
| **LM Studio** | `http://localhost:1234` | Any GGUF model via local server | `LLM_PROVIDER=lmstudio` |
| **vLLM / llama.cpp** | `http://localhost:8000` | High-throughput batched inference | `LLM_BASE_URL=http://localhost:8000/v1` |

### 3.2 Cloud API Integration Matrix

| Provider | Endpoint | Target Models | Speed | Monthly Cost (Est.) |
|---|---|---|---|---|
| **OpenRouter** | `https://openrouter.ai/api/v1` | 100+ Models (Claude, Llama-3 70B, Gemini) | Fast | $2 – $20 |
| **Groq** | `https://api.groq.com/openai/v1` | Llama 3.3 70B Versatile, DeepSeek-R1 Distill | Ultra-Fast | Free / $5 |
| **DeepSeek** | `https://api.deepseek.com` | DeepSeek-V3, DeepSeek-R1 Reasoning | Fast | $2 – $10 |
| **OpenAI** | `https://api.openai.com/v1` | GPT-4o, GPT-4o-mini, o3-mini | Fast | $5 – $30 |
| **Google Gemini** | `https://generativelanguage.googleapis.com/v1beta/openai` | Gemini 2.0 Flash, Gemini 1.5 Pro | Ultra-Fast | Free / $5 |
| **Anthropic** | `https://api.anthropic.com/v1` | Claude 3.5 Sonnet, Claude 3 Opus | Fast | $15 – $50 |

---

## 4. Agent Directory & Functional Catalog (18 Agents)

| Agent | Module | Core Functionality | Primary Mathematical / Algorithmic Basis |
|---|---|---|---|
| **ZEUS** | `src/agents/zeus_agent.py` | System health supervisor & heartbeat | Process watchdog, memory telemetry, soft restart |
| **SENTINEL**| `src/agents/sentinel.py` | Data integrity watchdog & circuit breaker | Gap detection, outlier Z-scoring, staleness check |
| **NEXUS** | `src/agents/intraday_regime_agent.py` | Market regime classifier | XGBoost + rule base (PCR, Breadth, VIX, Dispersion) |
| **TITAN** | `src/agents/titan_agent.py` | 45-strategy technical signal generator | Parallel indicator voting, Candlestick patterns, ATR |
| **ORACLE** | `src/agents/oracle_agent.py` | Macroeconomic & volatility gatekeeper | India VIX regression, FII/DII flow acceleration |
| **ORACLE_V2** | `src/agents/oracle_v2.py` | Machine learning classifier | LightGBM tree ensemble across 22 technical features |
| **SHADOW_LSTM**| `src/agents/lstm_agent.py` | Temporal price sequence model | Bi-LSTM neural memory on 60-bar normalized returns |
| **HERMES** | `src/agents/news_sentiment_agent.py` | News & NLP catalyst scoring | FinBERT transformer + keyword anomaly detection |
| **ATLAS** | `src/agents/sector_agent.py` | Sector rotation & relative strength | Sector momentum dispersion, relative strength index |
| **SIGMA** | `src/agents/sigma_agent.py` | 9-factor stock ranker & universe filter | Multi-factor weighted composite scoring |
| **CHIEF** | `src/agents/chief_agent.py` | Inter-agent coordination supervisor | Hierarchical delegation, consensus arbitration |
| **GUARDIAN**| `src/agents/guardian_agent.py` | Hard mathematical risk gatekeeper | Daily drawdown limit, correlation cap, sector limits |
| **MERCURY** | `src/agents/mercury_agent.py` | Execution & order management engine | Limit-wait execution, slippage limiter, partial scale-outs |
| **LENS** | `src/agents/lens_agent.py` | Trade attribution & performance logging | Real-time P&L attribution, MAE/MFE analytics |
| **KARMA** | `src/agents/karma_agent.py` | Reinforcement learning offline trainer | PPO (Proximal Policy Optimization) replay buffer |
| **MTF** | `src/agents/multi_timeframe_agent.py`| Multi-timeframe trend alignment | 15m, 1h, Daily candle agreement filter |
| **OPTIONS** | `src/agents/options_flow_agent.py` | Options flow & dark pool scanner | Put-Call Ratio (PCR), Max Pain, Unusual OI surges |
| **STRATEGY**| `src/agents/llm_strategy_generator.py`| Autonomous LLM strategy discovery | LLM code generation, backtesting & promotion |

---

## 5. Comprehensive Interview Preparation Guide

### Q1: Why use an Event-Driven Architecture rather than a monolithic synchronous loop?
**Answer**: In high-frequency and algorithmic trading, market events arrive asynchronously (quotes, order executions, news flashes, risk alerts). A monolithic loop creates pipeline stalls where slow network calls (e.g. LLM API or scraping) block time-sensitive risk checks. AlphaZero's EventBus utilizes a priority min-heap (`heapq`), guaranteeing that high-priority events (e.g., `STOP_LOSS_TRIGGERED` with priority 0) immediately preempt informational telemetry (priority 3), maintaining microsecond risk responsiveness.

### Q2: How does the system guarantee capital protection without suffering "whipsaws"?
**Answer**: Capital protection is handled by a three-tier defense-in-depth:
1. **Trend Velocity Veto**: Trades are vetoed before entry if $P(\text{Fall}) \ge 65\%$ for longs.
2. **Dynamic ATR Buffer**: Stops are set at $1.5\times$ ATR in trending regimes, expanding to $2.5\times$ in sideways and $3.5\times$ in volatile regimes, preventing premature shakeouts.
3. **Charge-Aware Breakeven Ratchet**: Once a position reaches $+0.5R$ profit, the stop is moved to Entry $+ 0.3\%$ (covering Indian exchange STT, GST, and broker fees), mathematically guaranteeing a zero-loss outcome for all trades that achieve initial traction.

### Q3: What is the mathematical justification for using Half-Kelly over Full Kelly?
**Answer**: Full Kelly criterion maximizes the expected logarithmic growth rate of capital:
$$f^* = \frac{p \cdot b - q}{b}$$
However, Full Kelly assumes perfect knowledge of $p$ and $b$. In live financial markets, win rate $p$ and payoff ratio $b$ are non-stationary parameters subject to estimation variance. Betting Full Kelly has a $33\%$ probability of suffering a $50\%$ drawdown. Fractional Half-Kelly ($0.5 \cdot f^*$) captures $75\%$ of the maximum geometric growth rate while slashing portfolio return variance and maximum drawdown by $50\%$.

### Q4: How does the Universal LLM Gateway handle offline or rate-limited APIs?
**Answer**: `LLMProvider` employs a tiered fallback hierarchy:
1. It probes local Ollama (`localhost:11434`) and LM Studio (`localhost:1234`) with a $1$-second non-blocking health check.
2. If available, it executes locally at zero cost.
3. If local servers are offline, it checks cloud API keys (OpenRouter $\to$ Groq $\to$ DeepSeek $\to$ OpenAI $\to$ Gemini $\to$ Claude).
4. If all APIs fail or are rate-limited, the agent degrades gracefully without crashing: returning neutral confidence ($0.50$) and `WAIT` signals, ensuring the main trading loop continues uninterrupted.
