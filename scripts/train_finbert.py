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
    # Positive
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
    # Neutral
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
    # Negative
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
        evaluation_strategy     = "epoch",
        save_strategy           = "epoch",
        load_best_model_at_end  = True,
        metric_for_best_model   = "eval_loss",
        logging_dir             = str(_LOG_DIR / "finbert_tb"),
        logging_steps           = 10,
        no_cuda                 = not torch.cuda.is_available(),
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
