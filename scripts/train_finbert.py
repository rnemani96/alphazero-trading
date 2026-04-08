"""
scripts/train_finbert.py  —  AlphaZero Capital
═══════════════════════════════════════════════
FinBERT Fine-Tuning Pipeline on Indian Financial News

Workflow:
  1. Fetch ~500 labeled Indian financial headlines from:
       - Moneycontrol RSS
       - Economic Times RSS
       - NSE corporate announcements
       - Manual seed labels (embedded below)
  2. Combine with original ProsusAI/finbert training distribution
  3. Fine-tune for 3 epochs on Indian market vocabulary
  4. Evaluate on held-out validation set
  5. Save to models/finbert_india/

Usage:
    python scripts/train_finbert.py

Requirements:
    pip install transformers torch datasets scikit-learn

Expected runtime:
    CPU:  ~2-3 hours
    GPU:  ~15-20 minutes

After training, HERMES loads this model automatically if it exists:
    config.get('FINBERT_MODEL_PATH', 'models/finbert_india')
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ensure logs directory exists before logging setup
(ROOT / "logs").mkdir(exist_ok=True)
_LOG_DIR = ROOT / "logs"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DIR / "finbert_training.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("FinBERT-Train")

# ── Seed labeled corpus: Indian-specific financial headlines ──────────────────
# Format: (headline, label)   label: 0=negative, 1=neutral, 2=positive
_SEED_CORPUS: List[Tuple[str, int]] = [
    # ── Positive ──────────────────────────────────────────────────────
    ("Sensex surges 800 points as FII buying accelerates", 2),
    ("NIFTY hits all-time high of 25000; IT stocks lead rally", 2),
    ("Reliance Industries beats Q3 estimates, profit up 18%", 2),
    ("RBI cuts repo rate by 25 bps, market rallies", 2),
    ("Budget 2024: Infrastructure spending doubled, markets cheer", 2),
    ("HDFC Bank reports record PAT of Rs 16000 crore", 2),
    ("FII net buyers for 10th consecutive session in Indian equities", 2),
    ("India GDP growth beats estimates at 8.4% in Q4", 2),
    ("TCS wins $2.5 billion deal with global bank, stock up 6%", 2),
    ("Inflation falls to 4-year low of 3.8%, below RBI target", 2),
    ("Zepto, Blinkit gross order value surges 80% YoY", 2),
    ("India manufacturing PMI at 60.5, decade high expansion", 2),
    ("Adani group secures Rs 50000 crore capex plan approval", 2),
    ("SGX Nifty up 120 points, positive global cues", 2),
    ("SEBI approves new F&O framework to boost retail participation", 2),
    ("Wipro announces Rs 12000 crore buyback at premium", 2),
    ("India becomes 5th largest economy, overtakes UK", 2),
    ("Dollar index weakens, INR strengthens to 82.50", 2),
    ("EV sector stocks surge on PLI scheme extension announcement", 2),
    ("Pharmaceutical exports hit record $27 billion in FY24", 2),
    ("Nifty Bank index surges 3% on strong Q2 NIM expansion from HDFC, ICICI", 2),
    ("Auto sector stocks rally 4% as wholesale dispatches hit 3-year high", 2),
    ("Infosys revises revenue guidance upward to 8-9%, stock jumps 7%", 2),
    ("India FDI inflows rise 40% YoY to $85 billion in FY24", 2),
    ("US Fed signals pause in rate hikes; global risk-on rally lifts Indian markets", 2),
    ("FMCG sector outperforms as rural demand recovery exceeds expectations", 2),
    ("SBI reports 60% surge in net profit, NPA ratio falls to 5-year low", 2),
    ("India trade deficit narrows on strong services export growth", 2),
    ("Options data shows heavy call writing at 22000; bullish structure confirmed", 2),
    ("Nifty futures open interest surges 15% with positive price action", 2),
    ("DII buying at Rs 8000 crore offsets FII outflow; markets resilient", 2),
    ("Power sector stocks up 5% as government fast-tracks 10 GW solar auctions", 2),
    ("SEBI relaxes FPI registration norms; foreign flows expected to improve", 2),
    ("GST collections hit record Rs 2.1 lakh crore in March", 2),
    ("L&T secures Rs 15000 crore orders in Q3, highest in 5 years", 2),
    ("India credit rating outlook revised to positive by Moody's", 2),
    ("Pharma stocks gain as USFDA approves key generic application", 2),
    ("Market breadth strong: 1800 advances vs 450 declines on NSE", 2),
    ("Nifty Midcap index outperforms benchmark for 4th consecutive week", 2),
    ("IT stocks surge on strong rupee depreciation benefit to exports", 2),
    ("Nifty closes above 22500 with expanding volumes; breakout confirmed", 2),
    ("RBI MPC unanimously votes to cut rates; bond yields fall 15 bps", 2),
    ("India services PMI hits 62, fastest expansion in a decade", 2),
    ("Tata Motors Q4 results beat on all parameters, JLR profitability at record", 2),
    ("SIP inflows cross Rs 25000 crore for first time; domestic liquidity strong", 2),
    ("ONGC discovers new oil block; stock gains 9% on strong reserve estimates", 2),
    ("India retail inflation at 3.2%, gives RBI room for further rate cut", 2),
    ("Nifty500 52-week highs: 320 stocks — broad-based bull market intact", 2),
    ("Foreign portfolio investors turn net buyers after 3-month selloff", 2),
    ("HDFC Life, SBI Life quarterly premium growth beats street estimates by 12%", 2),
    # ── Neutral ───────────────────────────────────────────────────────
    ("RBI maintains repo rate at 6.5%, policy stance unchanged", 1),
    ("Sensex closes flat as investors await quarterly results", 1),
    ("SEBI releases consultation paper on algo trading norms", 1),
    ("India VIX at 14.5, markets remain range-bound", 1),
    ("FII data: net sellers Rs 800 crore today in equities", 1),
    ("NSE to extend trading hours for currency derivatives from October", 1),
    ("IT sector under pressure due to global slowdown concerns", 1),
    ("Budget session to begin on February 1, markets on watch", 1),
    ("Quarterly earnings season kicks off this week", 1),
    ("NIFTY forms doji candle at resistance, wait-and-watch mode", 1),
    ("Mid-cap index underperforms large-cap by 1.2% this week", 1),
    ("Crude oil prices stable at $85, no major impact on India", 1),
    ("AMFI data: mutual funds net buyers Rs 2300 crore in equities", 1),
    ("Global markets mixed ahead of US Fed meeting", 1),
    ("Nifty Bank consolidates near 48000 support zone", 1),
    ("Nifty50 trades in 200-point range; low volumes ahead of F&O expiry", 1),
    ("RBI releases draft guidelines on digital lending norms", 1),
    ("FII sold Rs 1200 crore, DII bought Rs 1500 crore; net neutral session", 1),
    ("India VIX at 16, slightly elevated but within normal trading range", 1),
    ("SEBI board meets today; market watchers expect minor regulatory updates", 1),
    ("Nifty options: Max pain at 21500; markets likely to stay in 21000-22000 band", 1),
    ("US markets closed for holiday; thin Indian trading expected", 1),
    ("IT sector reports mixed bag: TCS strong, Wipro disappoints", 1),
    ("Rupee at 83.50 to dollar, largely stable despite global volatility", 1),
    ("Advance-decline ratio at 1.1 — market breadth slightly positive", 1),
    ("Midcap correction of 2% brings valuations closer to 5-year averages", 1),
    ("Capital goods sector flat despite strong order inflows", 1),
    ("Q1 earnings preview: Analysts expect moderate 8-10% PAT growth", 1),
    ("NSE F&O ban list unchanged; no major positional squeeze expected", 1),
    ("Global crude oil at $88 per barrel; India monitoring import costs", 1),
    ("Nifty Realty index up 0.3%; no major triggers for the sector", 1),
    ("RBI's FX reserves at $640 billion; import cover remains comfortable", 1),
    ("SEBI proposes new risk disclosure norms for derivatives trading", 1),
    ("Nifty support seen at 50-day EMA; no directional breakout yet", 1),
    ("AMFI data shows SIP inflows steady at Rs 19000 crore in March", 1),
    ("Markets open gap-up but quickly give back gains; indecisive session", 1),
    ("Nifty50 P/E at 20x, in line with 10-year average — fairly valued", 1),
    ("Crude at $87; oil marketing companies (HPCL, BPCL) marginally lower", 1),
    ("FII flows YTD: net buyers Rs 12000 crore — positive but moderate", 1),
    ("Sector rotation: IT and pharma selling, FMCG and utilities buying", 1),
    ("India current account deficit at 1.2% of GDP, within comfortable range", 1),
    ("Mixed Q3 results: 55% of Nifty50 beat estimates, 45% disappoint", 1),
    ("PSU bank stocks consolidate after 40% YTD run; profit booking seen", 1),
    ("Derivatives data: neither bulls nor bears have clear upper hand today", 1),
    ("SEBI extends deadline for MF expense ratio compliance by 6 months", 1),
    ("Nifty forms inside bar on daily chart; range continues for 5th session", 1),
    ("India-US trade talks ongoing; no definitive outcome yet", 1),
    # ── Negative ──────────────────────────────────────────────────────
    ("Sensex crashes 1200 points on global sell-off fears", 0),
    ("Nifty breaks 21000 support as FII outflow accelerates", 0),
    ("Yes Bank stock halted after RBI imposes moratorium", 0),
    ("India inflation spikes to 7.4%, above RBI upper tolerance", 0),
    ("IL&FS defaults on debt obligations, NBFC crisis deepens", 0),
    ("Rupee hits record low of 86 against dollar amid outflows", 0),
    ("Adani stocks crash 60% as Hindenburg report alleges fraud", 0),
    ("PMC Bank scam: RBI restricts withdrawals to Rs 10000", 0),
    ("Q2 GDP growth misses at 4.5%, weakest in 6 years", 0),
    ("RBI unexpectedly hikes repo rate by 50 bps, markets tank", 0),
    ("FII outflow Rs 15000 crore in single session, worst in 2024", 0),
    ("SEBI bans 100 entities for front-running in mutual funds", 0),
    ("India CAD widens to $35 billion on high crude import bill", 0),
    ("NIFTY closes below 200-day EMA for first time in 18 months", 0),
    ("Byju's defaults on $1.2 billion term loan, NCLT petition filed", 0),
    ("Market breadth negative: 1450 declines vs 480 advances on NSE", 0),
    ("Pharma stocks tank as US FDA issues import alert on 3 plants", 0),
    ("Power Finance Corp faces Rs 8000 crore NPA write-off pressure", 0),
    ("Mid and small cap sell-off intensifies, 8% correction in 2 weeks", 0),
    ("Crude at $95/bbl, India import bill to surge, INR under pressure", 0),
    ("Nifty falls 3% as global recession fears trigger broad-based selling", 0),
    ("Bank Nifty collapses 1800 points on asset quality fears in PSU banks", 0),
    ("Rupee breaches 87, RBI intervenes but fails to stem decline", 0),
    ("India fiscal deficit widens to 6.4% of GDP, rating downgrade risk rises", 0),
    ("US Fed hikes rates 75 bps; emerging markets including India see sharp outflows", 0),
    ("IT sector tanks 5% on weak US tech earnings and recession commentary", 0),
    ("Nifty Smallcap 250 index down 18% from peak, circuit filters triggered", 0),
    ("China slowdown sends commodity prices tumbling; metals sector crashes 7%", 0),
    ("SEBI bans promoter for insider trading; stock frozen at lower circuit", 0),
    ("PSU bank NPA disclosures shock investors; sector index down 8% in a week", 0),
    ("Nifty put-call ratio at 0.6, extreme bearish signal from options market", 0),
    ("FII outflow Rs 50000 crore in March, worst month since COVID crash", 0),
    ("Auto sector down 6% as chip shortage halts production at Maruti, Tata Motors", 0),
    ("Nifty500 new 52-week lows: 310 stocks, breadth worst since March 2020", 0),
    ("India VIX spikes to 32, fear index at highest level since 2022", 0),
    ("Housing finance stocks fall as RBI flags rising unsecured NBFC loan risk", 0),
    ("Sensex erases entire year's gains in 3 sessions of relentless selling", 0),
    ("Nifty closes below all key moving averages; technical damage severe", 0),
    ("Global risk-off: Dollar surges, gold up 2%, Indian equities down sharply", 0),
    ("Nifty Bank breaks 200-day moving average; banking stocks hit 52-week lows", 0),
    ("India trade war fears: US tariffs on steel, aluminium hit metals stocks 9%", 0),
    ("Q4 earnings season disappoints broadly; 65% of Nifty50 miss estimates", 0),
    ("Nifty options: Massive put buying; derivatives suggest 5% downside risk", 0),
    ("Consumer confidence index falls to 3-year low amid high food inflation", 0),
    ("Realty stocks crash 10% after RBI warns of froth in property prices", 0),
    ("FII short positions in Nifty futures at 5-year high; bearish positioning extreme", 0),
    ("Nifty formed death cross: 50-day EMA crosses below 200-day EMA", 0),
    ("India macro triple threat: high fiscal deficit, weak rupee, elevated crude", 0),
]

# ── RSS fetcher for live headlines ────────────────────────────────────────────



def _fetch_rss_headlines(limit_per_source: int = 50) -> List[str]:
    """Fetch unlabeled headlines from Indian financial RSS feeds."""
    headlines = []
    sources = [
        "https://www.moneycontrol.com/rss/MCtopnews.xml",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://www.business-standard.com/rss/markets-106.rss",
        "https://feeds.feedburner.com/ndtvprofit-latest",
    ]
    try:
        import requests
    except ImportError:
        logger.warning("requests not installed — skipping RSS fetch")
        return headlines

    for url in sources:
        try:
            r = requests.get(url, timeout=10,
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AlphaZero/1.0"})
            # Improved regex for titles in RSS
            titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
                                r.text, re.DOTALL)
            
            for t in titles:
                # Skip source title (usually first) and very short ones
                t = re.sub(r"<[^>]+>", "", t).strip()
                if t and len(t) > 20 and not any(s in t.lower() for s in ["moneycontrol", "economic times", "business standard"]):
                    headlines.append(t)
                if len(headlines) >= limit_per_source * len(sources):
                    break
            logger.info("RSS %s: %d raw headlines", url.split("/")[2], len(titles))
        except Exception as exc:
            logger.debug("RSS fetch failed %s: %s", url, exc)

    logger.info("Total RSS headlines collected: %d", len(headlines))
    return list(set(headlines)) # Remove duplicates


def _keyword_label(text: str) -> int:
    """
    Heuristic labeler for unlabeled RSS headlines.
    Returns 0/1/2 (neg/neu/pos).
    Only used for soft labels in the training mix — not ground truth.
    """
    t = text.lower()
    pos_words = ["surge", "rally", "gain", "record", "profit", "beat",
                 "upgrade", "buy", "strong", "growth", "high", "bullish",
                 "win", "deal", "approved", "positive", "rise", "jump"]
    neg_words = ["crash", "fall", "loss", "decline", "default", "fraud",
                 "sell", "weak", "low", "bearish", "ban", "penalty",
                 "outflow", "crisis", "concern", "warning", "drop", "plunge"]

    p = sum(1 for w in pos_words if w in t)
    n = sum(1 for w in neg_words if w in t)

    if p > n and p >= 2:
        return 2
    if n > p and n >= 2:
        return 0
    return 1


# ── Fine-tuning ───────────────────────────────────────────────────────────────

def build_dataset() -> Tuple[List[str], List[int]]:
    """Build training corpus: seed labels + RSS-fetched with heuristic labels."""
    texts  = [h for h, _ in _SEED_CORPUS]
    labels = [l for _, l in _SEED_CORPUS]

    rss_headlines = _fetch_rss_headlines(limit_per_source=30)
    for h in rss_headlines:
        texts.append(h)
        labels.append(_keyword_label(h))

    logger.info("Dataset: %d total samples (%d seed + %d RSS)",
                len(texts), len(_SEED_CORPUS), len(rss_headlines))
    return texts, labels


def fine_tune(
    model_name:  str = "ProsusAI/finbert",
    output_dir:  str = "models/finbert_india",
    n_epochs:    int = 3,
    batch_size:  int = 16,
    max_len:     int = 128,
    lr:          float = 2e-5,
):
    """
    Fine-tune FinBERT on the Indian financial news corpus.

    Args:
        model_name : HuggingFace model identifier
        output_dir : where to save fine-tuned weights
        n_epochs   : training epochs (3 recommended)
        batch_size : per-device batch size (reduce to 8 on CPU)
        max_len    : max token length
        lr         : learning rate
    """
    try:
        from transformers import (
            AutoTokenizer,
            AutoModelForSequenceClassification,
            TrainingArguments,
            Trainer,
        )
        import torch
        from sklearn.model_selection import train_test_split
    except ImportError as e:
        logger.error("Missing dependency: %s\nRun: pip install transformers torch scikit-learn", e)
        sys.exit(1)

    logger.info("Loading tokenizer and model: %s", model_name)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model     = AutoModelForSequenceClassification.from_pretrained(
        model_name, num_labels=3, ignore_mismatched_sizes=True
    )

    texts, labels = build_dataset()

    # Train / validation split
    X_tr, X_val, y_tr, y_val = train_test_split(
        texts, labels, test_size=0.15, random_state=42, stratify=labels
    )
    logger.info("Train: %d  Val: %d", len(X_tr), len(X_val))

    # Tokenise
    def tokenise(texts_list, labels_list):
        enc = tokenizer(texts_list, max_length=max_len, padding=True,
                        truncation=True, return_tensors="pt")
        import torch
        enc["labels"] = torch.tensor(labels_list, dtype=torch.long)
        return enc

    class _DS(torch.utils.data.Dataset):
        def __init__(self, enc):
            self._enc = enc
        def __len__(self):
            return len(self._enc["input_ids"])
        def __getitem__(self, i):
            return {k: v[i] for k, v in self._enc.items()}

    train_ds = _DS(tokenise(X_tr, y_tr))
    val_ds   = _DS(tokenise(X_val, y_val))

    os.makedirs(output_dir, exist_ok=True)

    args = TrainingArguments(
        output_dir              = output_dir,
        num_train_epochs        = n_epochs,
        per_device_train_batch_size = batch_size,
        per_device_eval_batch_size  = batch_size,
        learning_rate           = lr,
        eval_strategy           = "epoch",
        save_strategy           = "epoch",
        load_best_model_at_end  = True,
        metric_for_best_model   = "eval_loss",
        logging_dir             = str(_LOG_DIR / "finbert_tb"),
        logging_steps           = 10,
        use_cpu                 = not torch.cuda.is_available(),
        fp16                    = torch.cuda.is_available(),
        report_to               = "none" # Avoid wandb etc.
    )

    trainer = Trainer(
        model          = model,
        args           = args,
        train_dataset  = train_ds,
        eval_dataset   = val_ds,
    )

    logger.info("Fine-tuning started — %d epochs, batch=%d, lr=%.0e",
                n_epochs, batch_size, lr)
    start = time.time()
    trainer.train()
    elapsed = time.time() - start
    logger.info("Training complete in %.1f minutes", elapsed / 60)

    # Save
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    # Evaluation
    results = trainer.evaluate()
    logger.info("Validation metrics: %s", results)

    # Save training metadata
    meta = {
        "base_model":    model_name,
        "output_dir":    output_dir,
        "trained_at":    datetime.now().isoformat(),
        "train_samples": len(X_tr),
        "val_samples":   len(X_val),
        "epochs":        n_epochs,
        "eval_loss":     results.get("eval_loss"),
        "elapsed_mins":  round(elapsed / 60, 1),
    }
    with open(os.path.join(output_dir, "training_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    logger.info("✅ FinBERT India model saved → %s", output_dir)
    return output_dir


# ── Quick eval: test the saved model ─────────────────────────────────────────

def evaluate_saved(model_dir: str = "models/finbert_india"):
    """Quick sanity check on the saved model."""
    try:
        from transformers import pipeline
        pipe = pipeline("text-classification", model=model_dir, truncation=True)
    except Exception as exc:
        logger.error("Could not load model: %s", exc)
        return

    test_headlines = [
        "Sensex surges 1000 points on strong FII buying",
        "RBI maintains repo rate, markets unchanged",
        "Nifty crashes 800 points, FII outflow accelerates",
        "HDFC Bank reports record profit beating estimates",
        "Rupee hits all-time low vs dollar, markets concerned",
    ]
    expected = ["positive", "neutral", "negative", "positive", "negative"]

    print("\n" + "=" * 60)
    print("  FINBERT INDIA — SANITY CHECK")
    print("=" * 60)
    correct = 0
    for headline, exp in zip(test_headlines, expected):
        result = pipe(headline)[0]
        label  = result["label"].lower()
        score  = result["score"]
        match  = "✅" if exp in label else "❌"
        if exp in label:
            correct += 1
        print(f"  {match} [{score:.2f}] {label:10} | {headline[:55]}")

    print(f"\n  Accuracy: {correct}/{len(test_headlines)} = {correct/len(test_headlines)*100:.0f}%")
    print("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fine-tune FinBERT on Indian financial news")
    parser.add_argument("--epochs",     type=int,   default=3,                    help="Training epochs")
    parser.add_argument("--batch",      type=int,   default=16,                   help="Batch size")
    parser.add_argument("--output",     type=str,   default="models/finbert_india", help="Output directory")
    parser.add_argument("--eval-only",  action="store_true",                      help="Skip training, just evaluate saved model")
    args = parser.parse_args()

    # Ensure logs directory exists before logging setup (already done at top level too)
    (ROOT / "logs").mkdir(exist_ok=True)

    if args.eval_only:
        evaluate_saved(args.output)
    else:
        out = fine_tune(
            output_dir=args.output,
            n_epochs=args.epochs,
            batch_size=args.batch,
        )
        evaluate_saved(out)
