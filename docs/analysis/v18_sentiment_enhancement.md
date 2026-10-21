# AlphaZero v18: "DeepHERMES" Sentiment Upgrade

## 1. Problem Statement
**V17 (Current):** `HERMES` scans hundreds of RSS/API headlines per minute. While fast, it suffers from **Clickbait Bias** (over-reacting to sensationalist titles) and **Context Blindness** (missing structural nuances buried in full article text).

**V18 (Proposed):** Implement a **Two-Tier Inference** engine that uses LLMs (Claude/GPT-4) to perform "Structural Deep Dives" into the top-performing signals.

## 2. Architecture: "The Sentiment Funnel"

| Tier | Scope | Speed | Method | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1 (Surface)** | Full Universe (Nifty 500) | <1 ms | Keyword-based / VADER | Filter broad market noise; identify potential movers. |
| **Tier 2 (Deep)** | Top 5-10 Candidates | 2-4 sec | **LLM + Full Text Scrape** | Analyze causality, distinguish noise from structural risk. |

## 3. Implementation Steps

### Step 1: Integrated Scraper Update (`src/agents/hermes_agent.py`)
- Add a `fetch_full_content(url)` method using Selenium or Request-based scrapers (e.g., `trafilatura` or `beautifulsoup`).
- Extract the main article body, removing navigation and ads.

### Step 2: Tiered Logic in `Main.py`
1. Run `TITAN` and `NEXUS` to get a list of "High-Conviction" candidates (e.g., Confidence > 0.75).
2. For these candidates, trigger `HERMES.deep_analyze(symbol)`.
3. If Tier 1 and Tier 2 sentiment scores diverge by more than 0.3, **trigger a Veto** or request a manual confirmation via the Dashboard.

### Step 3: LLM Reasoning Prompt
The LLM will be prompted to categorize the news into:
- **Noise:** Standard fluctuation, generic analyst upgrades/downgrades.
- **Catalytic:** Earnings beats, partnership launches, new product success.
- **Structural Risk:** Fraud probes, regulatory changes, default risk, leadership crises.
- **Sentiment Weighting:** Structural risks will carry a 2x weight multiplier on the downside.

## 4. Expected Outcomes
- **Precision Increase:** Reduce false positives triggered by "analyst clickbait."
- **Risk Mitigation:** Catch "smoking gun" structural issues mentioned in the 4th paragraph of a long article that were missing from the title.
- **Improved Alignment:** Higher agreement between human intuition and AI signal generation.

## 5. Next Actions
1.  [ ] Prototype `full_text_scraper.py` unit.
2.  [ ] Create `DeepSentiment` schema in `LENS` database.
3.  [ ] Update `settings.py` to allow `DEEP_SENTIMENT_LIMIT` (e.g., top 5 per iteration).
