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

---
*Status Update: System is now running v5.0 core logic with nightly intelligence updates active.*
