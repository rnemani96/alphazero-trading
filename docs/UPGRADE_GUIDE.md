# AlphaZero Capital — v3.0 Upgrade Guide

## What Changed

### 1. Multi-Source Data Engine (`src/data/multi_source_data.py`) ✅ NEW

All 6+2 data sources are now integrated in a **priority waterfall** — if the first source fails or is rate-limited, the engine silently falls back to the next one. No more data gaps.

| Priority | Source | Type | Key Required | Best For |
|---|---|---|---|---|
| 1 | **Upstox Native API** | Real-time | ✅ `UPSTOX_ACCESS_TOKEN` | Live quotes, best intraday |
| 2 | **OpenAlgo** | Real-time | ✅ `OPENALGO_API_KEY` | Broker-grade, order placement |
| 3 | **yfinance** | ~15min delay | ❌ Free | Always-available fallback |
| 4 | **NSE Direct** | EOD/real-time | ❌ Free | NSE official prices + announcements |
| 5 | **Stooq** | EOD/delayed | ❌ Free | Daily candles, long history |
| 6 | **Twelve Data** | Real-time | ✅ `TWELVE_DATA_KEY` | Intraday history, 55 req/min free |
| 7 | **Finnhub** | Real-time | ✅ `FINNHUB_KEY` | Company news, 60 req/min free |
| 8 | **Alpha Vantage** | Real-time | ✅ `ALPHA_VANTAGE_KEY` | 5 req/min free, fallback |

**News sources** (in priority order):
1. Finnhub Company News API
2. NSE Corporate Announcements (nseindia.com)

### 2. Active Portfolio Guard (`src/risk/active_portfolio.py`) ✅ NEW

The most important new feature. Key rules:

- **Once a SWING or POSITIONAL trade is entered → the system holds it until target OR stop-loss is hit.**
- **No new stock is added to the same symbol while a position is open.**
- **When all 10 position slots are filled → APEX/SIGMA stop selecting new stocks until a slot frees.**
- **Intraday trades are EXEMPT from this rule** — they are managed by their own intraday controller.

The portfolio state is saved to `data/active_portfolio.json` — so positions survive restarts.

#### Position lifecycle:
```
OPEN → TARGET_HIT (target price reached, position closed automatically)
     → STOP_HIT   (stop-loss hit, position closed automatically)
     → EXPIRED     (max_days exceeded, force-closed)
     → FORCE_CLOSED (manual override from dashboard)
```

### 3. Portfolio Tracker Dashboard (`dashboard/portfolio_tracker.html`) ✅ NEW

A standalone HTML dashboard (no build required) showing:
- All open positions with **progress bars** toward target
- Real-time P&L, days held, trailing stops
- **Near Target tab** — positions within 2% of target price (prepare to book profits)
- **Trade History** — all closed trades with outcome, P&L, strategy
- **Slot visualiser** — visual grid of 10 position slots (filled / empty)
- Buttons to force-close or adjust target/SL from the dashboard

Open `dashboard/portfolio_tracker.html` in any browser (connect to `localhost:8000`).

### 4. Updated Settings (`config/settings.py`)

New environment variables:

```env
# Upstox Native API (FREE)
UPSTOX_API_KEY=...
UPSTOX_API_SECRET=...
UPSTOX_ACCESS_TOKEN=...   # refreshed daily

# Twelve Data (free: 55 req/min)
TWELVE_DATA_KEY=...

# Finnhub (free: 60 req/min)
FINNHUB_KEY=...

# Portfolio hold logic
HOLD_UNTIL_TARGET=true
DEFAULT_TARGET_PCT=6.0    # 6% default target
DEFAULT_SL_PCT=2.5        # 2.5% default SL
MAX_SWING_DAYS=30
MAX_POSITIONAL_DAYS=90
```

### 5. Updated `main.py`

- Integrates `MultiSourceData` for all market data
- Integrates `ActivePortfolio` guard before every signal execution
- Serves portfolio state on HTTP endpoints for dashboard
- KARMA training, ZEUS health, all 16 agents — untouched

---

## Deployment Steps

### Step 1: Copy files to your repo

```
src/data/multi_source_data.py    → copy to your src/data/
src/risk/active_portfolio.py     → copy to your src/risk/
config/settings.py               → replace your config/settings.py
main.py                          → replace your main.py
.env.template                    → copy, rename to .env, fill in keys
requirements.txt                 → replace, then pip install -r requirements.txt
dashboard/portfolio_tracker.html → copy to your dashboard/
```

### Step 2: Install new dependencies

```bash
pip install -r requirements.txt
# If Upstox SDK fails:
pip install upstox-python-sdk --break-system-packages
# If Twelve Data SDK:
pip install twelve-data --break-system-packages
# Finnhub:
pip install finnhub-python --break-system-packages
```

### Step 3: Add new API keys to .env

At minimum, add **Finnhub** (free, best for news) and **Twelve Data** (free, best intraday history):

```env
FINNHUB_KEY=your_key_from_finnhub.io
TWELVE_DATA_KEY=your_key_from_twelvedata.com
```

For Upstox native API (highly recommended — free):
```env
UPSTOX_API_KEY=your_api_key
UPSTOX_API_SECRET=your_api_secret
UPSTOX_ACCESS_TOKEN=your_daily_token  # refresh daily via OAuth2
```

### Step 4: Run

```bash
python main.py
```

Dashboard: open `dashboard/portfolio_tracker.html` in browser → connects to `localhost:8000`

---

## Why Agents Run 0/16

The log shows `Agents run: 0/16` because the agents were not detecting market hours correctly
(or agent modules failed to import). After this update:

1. Check each agent module exists in `src/agents/`
2. Verify `config/settings.py` loads without error: `python -c "from config.settings import settings; print(settings.MODE)"`
3. During market hours (9:15 AM–3:30 PM IST, Mon–Fri) the main loop will activate agents
4. Off-hours: only KARMA training runs (at `TRAINING_HOUR=21`)

---

## Data Source FAQ

**Q: I don't want to add API keys for everything. What's the minimum?**

The system works with ZERO API keys — yfinance + Stooq + NSE Direct cover all basics.
Add keys progressively:
1. Finnhub first (best free news + real-time quotes)
2. Twelve Data (best intraday candle history)
3. Upstox (only if using Upstox as broker)

**Q: Will adding Finnhub/Twelve Data improve trade quality?**

Yes significantly:
- Finnhub news → HERMES gets real news instead of synthetic
- Twelve Data intraday → TITAN signals use actual 5/15min candles
- Upstox native → Real-time tick data without 15min delay

**Q: How does the portfolio guard affect existing agents?**

All 16 agents run unchanged. The guard intercepts AFTER signal generation, BEFORE execution.
Agents keep scoring and generating signals — the guard just blocks execution if a position exists.
