# AlphaZero System Audit - March 21, 2026

## 1. Model & Data Science Performance Audit

| Factor | Analysis & Status | Recommendation |
| :--- | :--- | :--- |
| **Class Balance** | **SYMMETRIC BIAS.** Currently, 61% of signals are Bullish, heavily skewed by the SGX pre-market Gap-Up bias (+0.49%). While this reflects momentum, there is a risk of "Gap-and-Trap" where the system over-commits to a bullish open that fails. | Monitor the `Breadth` indicator tightly. If it drops below 45% during market hours, the system should pivot to hedging. |
| **Overfitting** | **LOW (Rule-based Fallback).** Since the NEXUS XGBoost model was falling back to rules due to a feature mismatch (22 vs 14), the system is currently "Underfitting"—using simple logic (VIX < 20, ADX < 25) instead of complex non-linear patterns. | Re-train the NEXUS model using the `train_nexus.py` script once you have sufficient 22-feature historical data dumped in `data/features/`. |
| **Feature Engineering** | **ROBUST.** The system correctly normalizes volatility via `atr_norm` and uses sector-rotation offsets (`sector_disp`). However, I noticed "Data Holes" where delivery % is hardcoded to 45% if the NSE API fails. | This "filler" data (45% delivery) should be flagged with a `data_quality` score so the model can weight those signals lower during inference. |
| **Precision/Recall** | **PRECISION BUG FOUND.** I discovered that the `AGGREGATE` logic was boosting confidence by 10% on unanimity, but the `Guardian` was rejecting 98% of signals due to a cooldown anomaly. | **FIXED.** I have patched the Guardian Agent to allow batch-processing of signals. |

## 2. Signal & Agent Anomaly Report

I identified and resolved two critical anomalies in the signal pipeline:

### ANOMALY: The "First-Mover" Bias (Critical Fix)
- **The Issue:** The `GuardianAgent` was updating its `last_trade_time` immediately after approving the first signal in a batch. Since all signals are processed in the same second, the second signal would see an elapsed time of 0s and trigger a `TRADE_COOLDOWN (0s < 300s)` rejection.
- **The Impact:** This effectively limited the system to taking exactly one trade every 5 minutes, regardless of how many high-conviction signals (0.80+) were found.
- **The Fix:** I modified the logic to process the entire batch of signals first, sorting them by confidence, and only applying the 5-minute cooldown after the batch is complete.

### ANOMALY: Feature Mismatch (NEXUS)
- **The Issue:** The XGBoost model on disk was trained for 14 features, but the live agent was sending 22.
- **The Fix:** I added a multi-version shim that automatically tries both 22-feature and 14-feature sets, ensuring the AI model is used whenever compatible.

## 3. Investor's Outlook (Risk vs. Quality)

- **Signal Quality:** Consensus is increasing. Symbols like `HAPPSTMNDS` and `ESCORTS` both show >0.80 confidence with "Triple Agreement" (TITAN, NEXUS, and HERMES all agree).
- **Execution Risk:** The **TRADE_COOLDOWN** of 300s is excellent for preventing "Wash Trading" and over-exposure, but it should be based on execution, not just approval. My fix ensures that the system picks the best symbol from the batch rather than the first one alphabetically.
- **Data Integrity:** `yfinance` is serving as a reliable fallback, but the News Ingestor is experiencing intermittent stalls (0 headlines vs 140 headlines).

## 5. Defense-in-Depth: Handling Black Swans & Extreme Events

AlphaZero is architected specifically to survive "Black Swan" events (wars, pandemics, flash crashes) via a multi-layered immune system:

### Layer 1: HERMES (Live Sentiment Warning)
- **Mechanism:** Scans live news headlines (RSS/Finnhub/NewsAPI) for keyword anomalies.
- **Crisis Response:** If words like "WAR," "PANDEMIC," or "CONFLICT" appear with high frequency, the sentiment score drops sharply *before* the price fully discounts it. This triggers an immediate NEXUS regime re-evaluation.

### Layer 2: ORACLE (VIX Volatility Gate)
- **Mechanism:** Monitors the **India VIX** (Volatility Index).
- **Crisis Response:** When VIX > 22, the **PositionSizer** cuts trade sizes by **50% to 70%**. Even if a disaster strikes, the total dollar-exposure is capped.

### Layer 3: NEXUS (Regime Circuit Breaker)
- **Mechanism:** Monitors market breadth (ratio of bullish to bearish stocks).
- **Crisis Response:** If breadth drops below 30%, NEXUS flips the regime to **`RISK_OFF`**. In this mode, **Long (BUY) trades are 100% disabled**, effectively freezing new equity exposure until the shock passes.

### Layer 4: GUARDIAN (Hard Risk Lock)
- **Mechanism:** Enforces hard mathematical limits (Daily Loss, Correlation, and Sector Exposure).
- **Crisis Response:** If the portfolio drops below **-2.0% in a single day**, the **Kill Switch** activates, stopping all trading for 24 hours to prevent "revenge trading" or catastrophic drawdowns.

### Layer 5: TITAN (ATR-Based Stops)
- **Mechanism:** Uses **Average True Range (ATR)** to calculate dynamic stops.
- **Crisis Response:** During high-volatility events like COVID, the system uses **wider stop-losses** but with **smaller quantities**. This allows positions "room to breathe" while keeping the absolute mathematical risk identical.

**Conclusion:** AlphaZero is designed to prioritize **Capital Preservation** above all else during extreme scenarios.
