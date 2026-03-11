|  |
| --- |
| **AlphaZero Capital**  Complete Master Reference  v17 | 16-Agent NSE Trading System | March 2026  *Implementation Checklist | Fund Addition Guide | Asset Expansion Roadmap* |

|  |  |  |  |
| --- | --- | --- | --- |
| **16 Agents** | **4 Data Sources** | **5 Timeframes** | **₹10L Capital** |

|  |
| --- |
| **SECTION 1 · Complete Implementation Checklist** |

*Every component of the AlphaZero Capital system, its current status, priority, and actionable notes.*

|  |  |  |  |  |
| --- | --- | --- | --- | --- |
| **AREA** | **COMPONENT** | **STATUS** | **PRIORITY** | **NOTES** |
| **Core Agents** | CHIEF — Portfolio selector | **✅ DONE** |  | Selects top 5 stocks, sigma scoring, trade type classification |
| **Core Agents** | SIGMA — Stock scoring engine | **✅ DONE** |  | Composite score: TA + FA + momentum + volume |
| **Core Agents** | ATLAS — Sector rotation | **✅ DONE** |  | Sector capping, 30% max exposure per sector |
| **Core Agents** | ORACLE — Macro intelligence | **✅ DONE** |  | VIX, FII flow, USD/INR, S&P 500, crude oil |
| **Core Agents** | NEXUS — Intraday regime | **✅ DONE** |  | TREND/RANGE/VOLATILE/RISK\_OFF classification |
| **Core Agents** | HERMES — News sentiment | **✅ DONE** |  | yfinance + ET + Moneycontrol RSS, FinBERT scoring |
| **Core Agents** | TITAN — Signal generator | **✅ DONE** |  | Technical signal generation, multi-strategy |
| **Core Agents** | GUARDIAN — Risk enforcer | **✅ DONE** |  | 2% daily loss, 5% max position, kill switch |
| **Core Agents** | MERCURY — Trade executor | **✅ DONE** |  | OpenAlgo in LIVE mode, PaperExecutor in PAPER |
| **Core Agents** | LENS — Signal evaluator | **✅ DONE** |  | SQLite logging, WIN/LOSS/SCRATCH scoring |
| **Core Agents** | KARMA — RL learning engine | **✅ DONE** |  | Strategy weights, pattern discovery, off-hours training |
| **Core Agents** | OPTIONS\_FLOW — Unusual activity | **✅ DONE** |  | OI sweep detection, dark pool proxy |
| **Core Agents** | MULTI\_TIMEFRAME — MTF filter | **✅ DONE** |  | Real candles via yfinance, pandas 2.x freq fixed |
| **Core Agents** | EARNINGS\_ANALYZER — LLM | **✅ DONE** |  | Claude Sonnet via Anthropic API |
| **Core Agents** | STRATEGY\_GENERATOR — LLM | **✅ DONE** |  | Nightly 8 PM discovery, backtest gate |
| **Core Agents** | TRAILING\_STOP — Stop manager | **✅ DONE** |  | ATR-based trailing, locks profit automatically |
| **Data Layer** | yfinance — Price & OHLCV | **✅ DONE** |  | Primary source, NSE via .NS suffix, MultiIndex fix |
| **Data Layer** | Fundamentals (P/E, ROE, etc.) | **✅ DONE** |  | yf.Ticker.info, 1-hour cache, 14 fields |
| **Data Layer** | Candle pattern detection | **✅ DONE** |  | 8 patterns, pure pandas, no TA-Lib required |
| **Data Layer** | Volume analysis (OBV, ratio) | **✅ DONE** |  | Accumulation/distribution, price-vol confirmation |
| **Data Layer** | Stooq price fallback | **✅ DONE** |  | Free NSE prices, no API key, rate-limit fallback |
| **Data Layer** | NSE Bhav Copy (EOD) | **🔶 PARTIAL** | **LOW** | Method stub present, manual enable required |
| **Data Layer** | OpenAlgo LIVE data | **🔶 PARTIAL** | **HIGH** | Only triggers in MODE=LIVE, needs broker API key |
| **Data Layer** | NSEpy / NSE Python lib | **❌ TODO** | **MEDIUM** | Direct NSE API — faster than yfinance, no rate limits |
| **Data Layer** | Screener.in fundamentals | **❌ TODO** | **MEDIUM** | P/E, ROE, debt from screener.in scraper — higher accuracy |
| **Data Layer** | Tickertape / Trendlyne feed | **❌ TODO** | **LOW** | Secondary fundamentals + analyst consensus |
| **Risk / Capital** | CapitalAllocator — sigma weighted | **✅ DONE** |  | Sigma score × sector cap, 5% per position max |
| **Risk / Capital** | GUARDIAN risk rules | **✅ DONE** |  | VIX scaling, consecutive loss limit, daily P&L gate |
| **Risk / Capital** | Position sizing (Kelly / ATR) | **🔶 PARTIAL** | **HIGH** | ATR stop present, full Kelly criterion not implemented |
| **Risk / Capital** | Correlation control | **❌ TODO** | **MEDIUM** | Avoid 2 stocks > 0.8 correlation in same portfolio |
| **Risk / Capital** | Portfolio rebalancing | **❌ TODO** | **MEDIUM** | Weekly rebalance to target weights — not yet wired |
| **Risk / Capital** | Max drawdown circuit breaker | **🔶 PARTIAL** | **HIGH** | Daily loss limit exists, rolling drawdown (7/30d) missing |
| **Risk / Capital** | Monte Carlo stress test | **❌ TODO** | **LOW** | Simulate 1000 paths before deploying new strategy |
| **Dashboard** | 5-tab stock modal | **✅ DONE** |  | Overview, Technical, Fundamental, Trade Setup, News |
| **Dashboard** | Indicator tooltips on hover | **✅ DONE** |  | RSI, ADX, EMA, ATR, MACD, VWAP explained in plain English |
| **Dashboard** | Candle patterns display | **✅ DONE** |  | Doji, Hammer, Engulfing, Morning/Evening Star, Inside Bar |
| **Dashboard** | Volume analysis panel | **✅ DONE** |  | OBV, vol ratio bar, accumulation/distribution label |
| **Dashboard** | KARMA intelligence panel | **✅ DONE** |  | Strategy weights, discovered patterns, regime accuracy |
| **Dashboard** | MTF vote count in reason | **✅ DONE** |  | e.g. "4/5 timeframe indicators aligned" |
| **Dashboard** | Capital Deployed + Cash cards | **✅ DONE** |  | Portfolio metrics strip, ₹ + % format |
| **Dashboard** | STRONG\_BUY badge colour fix | **✅ DONE** |  | includes() check — no more red for STRONG\_BUY |
| **Dashboard** | Trade type + holding badge | **✅ DONE** |  | INTRADAY/SWING/POSITIONAL/LONG TERM with colour codes |
| **Dashboard** | Live candlestick chart (TradingView) | **❌ TODO** | **MEDIUM** | Embed TradingView widget in Technical tab for real chart |
| **Dashboard** | Portfolio performance chart | **❌ TODO** | **MEDIUM** | Equity curve, drawdown chart using Chart.js or recharts |
| **Dashboard** | Telegram command log panel | **❌ TODO** | **LOW** | Show last 10 Telegram commands sent and system replies |
| **Execution** | Paper executor (simulation) | **✅ DONE** |  | Realistic slippage 0–16 bps, 100% fill rate |
| **Execution** | OpenAlgo LIVE executor | **✅ DONE** |  | Place/modify/cancel, mass cancel kill switch |
| **Execution** | Telegram alerts | **✅ DONE** |  | Trade alerts, stop hits, daily P&L briefing |
| **Execution** | Telegram bot commands | **🔶 PARTIAL** | **HIGH** | /pause /resume /kill implemented, /status partial |
| **Execution** | Order retry logic | **❌ TODO** | **HIGH** | Retry rejected orders up to 3× with 500ms backoff |
| **Execution** | Partial fill handling | **❌ TODO** | **MEDIUM** | Handle broker returning qty < requested |
| **Execution** | Bracket orders (BO/CO) | **❌ TODO** | **MEDIUM** | SL + target in single order via OpenAlgo BO endpoint |
| **Learning** | KARMA real-time weight update | **✅ DONE** |  | Every closed trade updates strategy weights |
| **Learning** | Off-hours training (6PM–9AM) | **✅ DONE** |  | Runs on last-fetched data across 5 timeframes |
| **Learning** | Pattern discovery & publish | **✅ DONE** |  | 70%+ win rate in same setup → pattern logged |
| **Learning** | LENS SQLite evaluation DB | **✅ DONE** |  | WIN/LOSS/SCRATCH per signal with timestamps |
| **Learning** | FinBERT news model fine-tune | **❌ TODO** | **MEDIUM** | Fine-tune on Indian financial news headlines (ET, MC) |
| **Learning** | NEXUS XGBoost regime model | **🔶 PARTIAL** | **HIGH** | JSON model stub present, full training data needed |
| **Learning** | Walk-forward backtesting | **❌ TODO** | **HIGH** | Validate strategies on out-of-sample data before live |
| **Learning** | RL PPO via Stable-Baselines3 | **❌ TODO** | **LOW** | Full RL agent — phase 3 upgrade, needs replay buffer |
| **Infra / Ops** | GitHub repo structure | **✅ DONE** |  | v2.0 branch, PATCH\_GUIDE.md deployment map |
| **Infra / Ops** | .env secrets management | **✅ DONE** |  | API keys, MODE, risk params in .env only |
| **Infra / Ops** | Auto-restart on crash | **❌ TODO** | **HIGH** | systemd / pm2 to restart main.py on failure |
| **Infra / Ops** | Cloud deployment (AWS/GCP) | **❌ TODO** | **MEDIUM** | EC2 t3.medium or GCP e2 — IST timezone critical |
| **Infra / Ops** | Daily DB backup | **❌ TODO** | **HIGH** | Cron to backup evaluation.db + status.json nightly |
| **Infra / Ops** | Log rotation | **❌ TODO** | **MEDIUM** | logs/ grows unbounded — add 7-day rotation |
| **Infra / Ops** | Health check endpoint | **❌ TODO** | **MEDIUM** | GET /health returns agent statuses as JSON |

|  |
| --- |
| **SECTION 2 · Immediate To-Do — Before Going LIVE** |

## **🔴 CRITICAL (Must fix before real money)**

* **Order retry logic — a rejected order today means missed trade. Add 3× retry with 500ms backoff in mercury.py.**
* **Walk-forward backtest — run every strategy on 6 months out-of-sample NSE data before switching MODE=LIVE.**
* **Rolling drawdown circuit breaker — add 7-day and 30-day rolling drawdown tracking in guardian.py. Stop trading at −5% weekly.**
* **Daily DB backup — one disk failure will wipe all KARMA learning. Automate backup to S3 or Google Drive.**
* **Auto-restart on crash — use systemd or pm2. main.py crashes at 10:15 AM on a bad data fetch, no humans watching.**

## **🟡 HIGH — Wire before first month of LIVE trading**

* Telegram /status command — full agent health, open positions, today P&L, GUARDIAN status.
* NEXUS XGBoost model training — collect 6 months of ADX/VIX/ATR labeled data, train, save to models/nexus\_regime.json.
* Partial fill handling in paper\_executor.py — simulate 80% fills on large orders (>₹2L position) for realism.
* Bracket order support — wire OpenAlgo BO/CO endpoint in mercury.py so SL+target are exchange-managed.
* NSEpy integration — replace yfinance for intraday data to avoid rate limits during market hours.

## **🔵 MEDIUM — Month 2 improvements**

* TradingView widget embed in Technical tab — replace static ind cards with actual live chart.
* Portfolio equity curve chart — visualise capital growth over time in Performance tab.
* Correlation control — before adding a new stock, check if it correlates > 0.8 with any existing position.
* Screener.in fundamentals scraper — more reliable PE/ROE data than yfinance for Indian stocks.
* FinBERT fine-tuning on Indian headlines — 15% improvement in news sentiment accuracy.

|  |
| --- |
| **SECTION 3 · How to Add Funds — Zerodha & Upstox Guide** |

*The bot never holds money itself. Money sits in your broker account. The bot talks to the broker API. Here is the exact end-to-end flow.*

## **3.1 The Money Flow — How It Works**

|  |  |
| --- | --- |
| **1** | Your Bank Account → (NEFT/IMPS/UPI) → Broker Trading Account |
| **2** | Broker Account → (available as Margin/Cash) → Can now place orders |
| **3** | AlphaZero decides to BUY RELIANCE → sends order via OpenAlgo API |
| **4** | OpenAlgo forwards to Broker → Order placed on NSE exchange |
| **5** | RELIANCE bought → shares in your Demat → cash reduced by ₹ amount |
| **6** | RELIANCE hits target → bot sends SELL order → proceeds back to cash balance |
| **7** | At end of day → cash available → you can withdraw or leave for tomorrow |

## **3.2 Zerodha — Step-by-Step Setup**

### **Step 1: Add Funds to Zerodha**

* Login to kite.zerodha.com → click "Funds" in top menu.
* Click "Add funds" → choose UPI (instant, free), Net Banking (same day) or NEFT (T+1).
* For UPI: enter amount → confirm on PhonePe/GPay → funds reflect in 2–5 minutes.
* For NEFT: copy the Zerodha IFSC + Account Number shown → use your internet banking → funds reflect in 2–4 hours.
* Check available margin at kite.zerodha.com/dashboard under "Equity" — this is what the bot can use.

### **Step 2: Connect Zerodha to AlphaZero via OpenAlgo**

* Install OpenAlgo on your machine: pip install openalgo OR git clone https://github.com/marketcalls/openalgo
* OpenAlgo is a local bridge server that converts AlphaZero's REST calls into broker-specific API calls.
* In OpenAlgo dashboard → add Zerodha broker → enter your Zerodha API key + API secret.
* Get Zerodha API key at: developers.kite.trade → create an app → note the api\_key and api\_secret.
* Zerodha API costs ₹2,000/month (charged quarterly). Required for automated trading.
* OpenAlgo gives you back a single OPENALGO\_API\_KEY you put in your .env file.

### **Step 3: Update .env in AlphaZero**

|  |
| --- |
| MODE=LIVE  OPENALGO\_HOST=http://localhost:5000  OPENALGO\_API\_KEY=your\_key\_here  MAX\_DAILY\_LOSS\_PCT=0.02 # 2% of capital  MAX\_POSITION\_SIZE\_PCT=0.05 # max 5% per stock  INITIAL\_CAPITAL=1000000 # Rs 10,00,000 |

### **Step 4: Go LIVE safely**

* Run paper mode for at least 30 trading days first. Win rate should be > 55% and Sharpe > 1.0.
* Start with 10–20% of your intended capital (e.g. ₹1L if planning ₹10L). Observe for 1 week.
* Keep the GUARDIAN limits conservative: 1% daily loss, 3% max position for the first month.
* Never leave the system running unattended on day 1 of LIVE mode. Stay at your desk.

## **3.3 Upstox — Step-by-Step Setup**

### **Step 1: Add Funds to Upstox**

* Login to pro.upstox.com → Funds → Add Money → UPI (instant) or Net Banking.
* Upstox reflects UPI funds in under 60 seconds during market hours.
* Check "Available Margin" under the Funds tab — this is what the bot uses.

### **Step 2: Upstox API Setup (free, unlike Zerodha)**

* Visit developer.upstox.com → create a new app → you get an api\_key and api\_secret.
* Upstox API is FREE — no monthly charge. Good choice for starting out.
* OAuth2 token expires daily — OpenAlgo handles token refresh automatically. Just ensure OpenAlgo is running.
* In OpenAlgo: add Upstox broker → enter api\_key + api\_secret + redirect URI (http://localhost:5000/callback).
* OpenAlgo handles the daily OAuth login automatically using stored refresh tokens.

### **Step 3: Broker Comparison**

|  |  |  |
| --- | --- | --- |
| **Feature** | **Zerodha** | **Upstox** |
| API Cost | ₹2,000/month | FREE |
| Intraday brokerage | ₹20 or 0.03% | ₹20 or 0.05% |
| Delivery brokerage | FREE | FREE (new policy) |
| API stability | Very high — industry gold standard | High — good for algo trading |
| Data quality | Tick data, historical data API | Good OHLCV, WebSocket ticks |
| Best for | Professionals, large capital | Beginners, cost-conscious |
| OpenAlgo support | Full support | Full support |
| Auto token refresh | Yes (via OpenAlgo) | Yes (via OpenAlgo) |
| TOTP 2FA support | Yes — configure in OpenAlgo | Yes — configure in OpenAlgo |

## **3.4 Capital Scaling Guide**

|  |  |  |  |
| --- | --- | --- | --- |
| **Stage** | **Capital** | **GUARDIAN Limits** | **What to watch** |
| Paper / Test | ₹0 (virtual ₹10L) | Any — learn the system | Win rate, Sharpe, max drawdown |
| Cautious Live | ₹50,000 – ₹1L | 1% daily loss, 3% pos size | Slippage vs paper, fill quality |
| Active Live | ₹1L – ₹5L | 1.5% daily loss, 4% pos size | Sector concentration, corr risk |
| Scaled Live | ₹5L – ₹25L | 2% daily loss, 5% pos size | Capital efficiency, monthly Sharpe |
| Fund Level | ₹25L+ | 2% daily loss, 5% pos, VIX scaling | Drawdown, SEBI algo registration |

*Important: SEBI requires registration as an Algorithmic Trader if your algo places > 2 orders/second or you are managing third-party capital. For personal capital below ₹1 crore, no registration is required today.*

|  |
| --- |
| **SECTION 4 · Asset Expansion Roadmap** |

*AlphaZero is designed as a multi-asset system. The agent architecture, event bus, and execution layer are all broker-agnostic. Expanding to new asset classes requires adding new data agents, a new execution adapter, and updating CHIEF's portfolio logic.*

## **4.1 Architecture Pattern for Any New Asset Class**

|  |  |  |
| --- | --- | --- |
| **Layer** | **What to add** | **Estimated effort** |
| Data Agent | New agent to fetch prices/NAV/yields for the asset | 1–3 days |
| Signal Agent | Asset-specific strategy (momentum for MF, yield curve for bonds) | 2–5 days |
| Execution Adapter | New executor class (e.g. MF API, RBI bond portal) | 2–4 days |
| CHIEF update | Add asset class weight to portfolio allocation logic | 1 day |
| Dashboard | New asset card + tab in modal with asset-specific metrics | 1–2 days |
| Risk rules | GUARDIAN rules for the new asset (illiquidity, lock-in) | 1 day |
| Total | New asset class live | 1–2 weeks per asset |

## **4.2 Mutual Funds**

### **Data Sources**

* MFAPI (mfapi.in) — free, official NAV data for all Indian mutual funds by scheme code.
* AMFI website (amfiindia.com) — official NAV downloads, fund factsheets, AUM data.
* Kuvera / Groww API (unofficial) — for direct plan comparison and exit load info.

### **Execution**

* MF Central API (mfcentral.com) — SEBI-regulated, can place direct plan orders. No brokerage.
* BSE StAR MF Platform — used by most fintech apps, allows SIP + lump sum via API.
* Zerodha Coin API — if you already have Zerodha, Coin gives direct plan MF access via Kite API.

### **New Agents to Build**

* MF\_SCREENER — scores funds by: 5-year CAGR, Sharpe > 1.0, expense ratio < 0.5%, AUM > ₹1,000 Cr.
* CATEGORY\_ROTATOR — rotates between Large Cap / Mid Cap / Small Cap / Debt based on ORACLE macro signals.
* SIP\_MANAGER — manages systematic investment: invests fixed amount on 1st of every month regardless of market.

### **Key Differences from Equities**

* MF orders are same-day NAV (cutoff: 3 PM for equity, 1:30 PM for debt). No intraday.
* Exit loads: most funds have 1% exit load if redeemed within 1 year. GUARDIAN must factor this.
* Liquid funds (Axis Liquid, etc.) can act as cash-equivalent parking — better than idle cash.
* ELSS funds have 3-year lock-in. GUARDIAN must flag these as illiquid positions.

## **4.3 Government Bonds & Debt**

### **Data Sources**

* RBI Retail Direct (rbiretaildirect.org.in) — official G-Sec prices and yields.
* CCIL (fimmda.org.in) — benchmark yield curves, G-Sec prices, T-Bill yields.
* NSE Bond platform — Government Securities traded on exchange like stocks.

### **Execution**

* RBI Retail Direct portal — buy G-Secs, T-Bills, SGBs directly. No broker fee. No secondary market.
* NSE/BSE bond segment via broker — same Zerodha/Upstox account. Use CNC product type.
* NDS-OM (institutional) — only if you scale to ₹5Cr+. Institutional bond trading platform.

### **New Agents to Build**

* YIELD\_WATCHER — monitors 10-year G-Sec yield (^TNX equivalent for India). Signals when yield crosses key levels.
* DURATION\_MANAGER — calculates modified duration of bond portfolio. Reduces duration when RBI is hiking rates.
* RBI\_CALENDAR — tracks MPC meeting dates, inflation prints, GDP data. Trades bond price reaction to RBI surprises.

### **Key Differences from Equities**

* Bond prices move inversely to yields. When RBI hikes rates → bond prices fall → sell bonds first.
* G-Secs have zero credit risk but high interest rate risk for long-dated bonds (10Y, 30Y).
* T-Bills (91/182/364 day) are essentially risk-free parking — better yield than savings account.
* SGBs (Sovereign Gold Bonds) combine gold price + 2.5% annual interest — best of both worlds.

## **4.4 Gold**

### **Data Sources**

* MCX spot gold price — via yfinance ticker GC=F (Comex) or MCX via broker API.
* IBJA rates (ibja.co) — Indian Bullion & Jewellers Association, official daily gold rate.
* Gold ETF NAV — GoldBees (GOLDBEES.NS) on NSE — trades like a stock, tracks MCX gold.

### **Instrument Options**

|  |  |  |  |
| --- | --- | --- | --- |
| **Instrument** | **How to buy** | **Costs** | **Best for** |
| Gold ETF (GOLDBEES) | Via Zerodha/Upstox CNC | 0.5% expense ratio + brokerage | Active trading, easy entry/exit |
| SGB (Govt Bond) | RBI Direct or broker | Zero — even capital gain free on maturity | Long-term hold (8 year term) |
| MCX Futures | Futures account via broker | Higher margin, P&L daily mark-to-mkt | Short-term hedging, advanced only |
| Digital Gold | PhonePe/GPay/Paytm | Higher spread 2–3%, storage fee | Avoid for algo system — no API |

### **New Agents to Build**

* GOLD\_MACRO — monitors USD index (DXY), real yields, inflation expectations. Gold rises when real yields fall.
* PRECIOUS\_METALS\_ROTATOR — switches between Gold ETF (tactical) and SGB (strategic) based on holding horizon.

## **4.5 Full Multi-Asset Architecture — Target State**

|  |  |  |  |
| --- | --- | --- | --- |
| **Asset Class** | **% of Portfolio** | **Agent** | **Data Source** |
| NSE Equities (current) | 40–60% | CHIEF + all 16 agents | yfinance, NSEpy, OpenAlgo |
| Equity Mutual Funds | 20–30% | MF\_SCREENER + CATEGORY\_ROTATOR | mfapi.in, AMFI |
| Gold (ETF + SGB) | 10–15% | GOLD\_MACRO | MCX, IBJA, yfinance GC=F |
| Government Bonds / T-Bills | 10–20% | YIELD\_WATCHER + DURATION\_MGR | RBI Direct, CCIL |
| Cash / Liquid Funds | 5–10% | SIP\_MANAGER | Zerodha Coin / MF Central |

## **4.6 Expansion Timeline (Recommended Sequence)**

|  |  |  |
| --- | --- | --- |
| **Phase** | **Timeline** | **Action** |
| Phase 0 | Now → Month 3 | Fix CRITICAL items, run paper mode 30 days, then go LIVE with NSE equities only at ₹1L |
| Phase 1 | Month 3–6 | Scale NSE equities to full capital. Add walk-forward backtest and auto-restart. Hit consistent 55%+ win rate. |
| Phase 2 | Month 6–12 | Add Gold ETF (GOLDBEES) + T-Bills/Liquid Funds as cash alternative. GOLD\_MACRO agent. Portfolio allocation: 70% equity, 15% gold, 15% liquid. |
| Phase 3 | Year 2 | Add Mutual Funds via mfapi.in + BSE StAR MF. MF\_SCREENER + CATEGORY\_ROTATOR. Equity drops to 55%, MF 25%, Gold 10%, Bonds 10%. |
| Phase 4 | Year 2–3 | Add Government Bonds. YIELD\_WATCHER + RBI\_CALENDAR. Full asset allocation system. True multi-asset autonomous fund. |
| Phase 5 | Year 3+ | Crypto (BTC/ETH via CoinDCX API), International ETFs (Motilal NASDAQ 100), REITs (Mindspace, Nexus). Register as Portfolio Management Service (PMS) if managing > ₹50L third-party capital. |

|  |
| --- |
| **SECTION 5 · Quick Reference & Status Summary** |

## **5.1 Current System Status at a Glance**

|  |  |  |
| --- | --- | --- |
| **16/16 Agents Live** | **Paper Mode Safe** | **Dashboard 5-Tab Modal** |
| **Fundamentals Fixed** | **Candle Patterns ✓** | **KARMA Learning ✓** |
| **Off-Hours Training ✓** | **Volume Analysis ✓** | **LIVE Mode: Setup Needed** |

## **5.2 File Deployment Map**

|  |  |  |
| --- | --- | --- |
| **Patch File** | **Copy to Repo at** | **Changed This Session** |
| fetch.py | src/data/fetch.py | Fundamentals, candle patterns, volume, Stooq |
| karma\_agent.py | src/agents/karma\_agent.py | Full knowledge summary, off-hours training |
| main.py | main.py (root) | KARMA wired, fundamentals in candidates, MTF count |
| dashboard.html | dashboard/dashboard.html | KARMA panel, tooltips, candle patterns, vol analysis |
| capital\_allocator.py | src/risk/capital\_allocator.py | Previous session |
| multi\_timeframe\_agent.py | src/agents/multi\_timeframe\_agent.py | Previous session — pandas 2.x fix |

## **5.3 Environment Variables Reference**

|  |  |  |
| --- | --- | --- |
| **Variable** | **Example Value** | **Purpose** |
| MODE | PAPER or LIVE | PAPER = simulation, LIVE = real broker |
| OPENALGO\_HOST | http://localhost:5000 | URL where OpenAlgo bridge is running |
| OPENALGO\_KEY | abc123xyz | API key from OpenAlgo dashboard |
| ANTHROPIC\_API\_KEY | sk-ant-... | For EARNINGS\_ANALYZER and STRATEGY\_GENERATOR |
| INITIAL\_CAPITAL | 1000000 | Starting capital for CapitalAllocator (₹10L default) |
| MAX\_DAILY\_LOSS\_PCT | 0.02 | GUARDIAN stops trading at 2% daily loss |
| MAX\_POSITION\_SIZE\_PCT | 0.05 | Max 5% of capital per single position |
| TELEGRAM\_TOKEN | 123456:ABCxyz | Your Telegram bot token from @BotFather |
| TELEGRAM\_CHAT\_ID | 987654321 | Your Telegram user/chat ID — whitelist only |

|  |
| --- |
| **You are building a real autonomous trading firm**  *The architecture is production-grade. The intelligence layer is live. The next step is your first LIVE trade.*  Respect the risk rules. Trust the paper results. Scale gradually. The system gets smarter every trade. |