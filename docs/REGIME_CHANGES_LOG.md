# AlphaZero Capital - Regime & Risk Engine Update
**Date:** March 23, 2026
**Purpose:** Documenting the massive overhaul to Risk Management, Regime Gating, and Directional Logic.

This document serves as a backup log. If the new logic performs poorly in PAPER mode, use this document to manually revert the changes or rollback using version control.

---

## 📂 Files Modified

### 1. `src/risk/active_portfolio.py`
**What Changed:**
- **Math Bug Fix:** Corrected the P&L math for Short positions. Previously, Short trades used Long Math `(Current Price - Entry)` which resulted in fake losses when the price dropped. It now uses `(Entry - Current Price)` for Short trades.
- **0.5R Breakeven Logic:** Added logic to track `profit_dist`. Once a trade moves 50% towards its target risk, the stop-loss is updated to `Entry + 0.5%` to guarantee a "no-loss" trade.
- **1R Partial Profit Taking:** Once a trade hits a 1:1 risk-to-reward (1R), it automatically sells 50% of the position to secure profits. The remainder continues trailing.
- **Broker Executions:** `update_prices` now returns a third list called `partial_exits` which is sent back to the main loop so the `MERCURY` agent can actually execute the partial scale-outs.

### 2. `src/agents/guardian_agent.py`
**What Changed:**
- **Regime-Aware Stop Losses (ATR):** Altered `_compute_sl_target` to accept the current market `regime`. Stop distances are now dynamic:
  - `TRENDING`: 1.5x ATR
  - `SIDEWAYS`: 2.5x ATR
  - `VOLATILE`: 3.5x ATR
- **Directional Initialization:** Passed `action_side` (LONG/SHORT) through the Guardian check to ensure positions initialize accurately from the start.

### 3. `main.py`
**What Changed:**
- **Contextual Score System (Soft Gating):** In `_aggregate_signals` (Step 9), rigid threshold filters were replaced with a scoring system out of 7 points for every signal:
  - **Market Breadth (+2 Points):** Evaluates if the majority of the market is trending in the direction of the trade.
  - **Volume Confirmation (+2 Points):** Checks `volume_zscore > 0.5` against recent averages.
  - **Regime Match (+2 Points):** Flags trend-following strategies trying to trade in choppy/sideways markets.
  - **Sector Alignment (+1 Point):** Uses `ATLAS` metrics to verify the sector supports the individual stock trade.
- **Thresholds:** Requires a score of `4/7` in normal markets, and `5/7` in VOLATILE markets.
- **Time-of-Day Volatility Gap:** Added a penalty during the `12:00 PM – 1:30 PM IST` lunch range. Trades aren't blocked, but they require a higher `> 0.80` base confidence to execute.
- **Symbol Cooldown:** If a stock hits its Stop-Loss, it receives a 1-hour "cooldown" flag (`_state['symbol_cooldowns']`) blocking any re-entries to prevent revenge trading.
- **Position Upgrades:** If `MAX_POSITIONS` is reached, a weak open position (low profit + low confidence) is force-closed to make room for a significantly higher confidence (+15% more) new signal.

---

## ⏪ How to Revert to Old Code

If you are using **Git** (Version Control), fixing this is simple. Run the following command in your terminal to view the differences and rollback:

```bash
# Check what has changed
git status
git diff

# To throw away ALL changes made to these files and revert back:
git restore src/risk/active_portfolio.py
git restore src/agents/guardian_agent.py
git restore main.py
```

If you are **not** using Git, you will need to manually open `main.py`, `active_portfolio.py`, and `guardian_agent.py` and delete the blocks of code explicitly checking for `breakeven_done`, `scale_out_done`, the `Contextual Score System` in `main.py`, and the `in_lunch_zone` checks.
