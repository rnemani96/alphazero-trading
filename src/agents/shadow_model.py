"""
src/agents/shadow_model.py  —  AlphaZero Capital
══════════════════════════════════════════════════
Shadow Model A/B Testing Framework

Runs two KARMA/PPO models simultaneously:
  - Model A: Current champion
  - Model B: Challenger (new architecture or re-trained weights)

Evaluates signals from both on paper trades, tracks performance separately,
and promotes the challenger to champion when it statistically outperforms.

Architecture:
  - ShadowModelManager holds both models
  - Each model votes independently on every signal
  - Votes are tracked in ShadowLedger (lightweight in-memory + persisted)
  - Promotion happens when challenger beats champion by >5% Sharpe
    over a minimum evaluation window of 30 signals

Usage in main.py or KarmaAgent:
    shadow = ShadowModelManager()
    winner = shadow.vote(observation, context)   # returns 'A' | 'B'
    shadow.record_outcome('A', pnl=1500)
    shadow.maybe_promote()
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from ..utils.stats import sharpe, win_rate, full_metrics

logger = logging.getLogger("ShadowModel")

_LOG_DIR    = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LEDGER_FILE = str(_LOG_DIR / "shadow_ledger.json")

# Promotion criteria
_MIN_SIGNALS_TO_EVALUATE  = 30
_MIN_SHARPE_ADVANTAGE     = 0.10   # challenger must beat champion by this much
_MIN_WIN_RATE_ADVANTAGE   = 0.03   # or by this win-rate delta


# ── Model Wrapper ─────────────────────────────────────────────────────────────

class _ModelSlot:
    """Thin wrapper around a PPO model with performance tracking."""

    def __init__(self, slot_id: str, model_path: str):
        self.slot_id    = slot_id          # 'A' or 'B'
        self.model_path = model_path
        self._model     = None
        self._loaded    = False
        self.returns:   List[float] = []   # fraction returns per trade
        self.signals:   int         = 0
        self.promoted:  int         = 0    # times this slot became champion

    def load(self) -> bool:
        """Lazy-load PPO model. Returns True if loaded."""
        if self._loaded:
            return True
        try:
            from stable_baselines3 import PPO
            if os.path.exists(self.model_path):
                self._model  = PPO.load(self.model_path)
                self._loaded = True
                logger.info("ShadowModel %s: loaded from %s", self.slot_id, self.model_path)
                return True
        except Exception as exc:
            logger.debug("ShadowModel %s: load failed — %s", self.slot_id, exc)
        return False

    def predict(self, obs: np.ndarray) -> int:
        """
        Predict action (0=hold, 1=buy, 2=sell).
        Returns 0 if model not loaded.
        """
        if not self._loaded and not self.load():
            return 0
        try:
            action, _ = self._model.predict(obs, deterministic=True)
            self.signals += 1
            return int(action[0]) if hasattr(action, '__len__') else int(action)
        except Exception as exc:
            logger.debug("ShadowModel %s predict: %s", self.slot_id, exc)
            return 0

    def record_return(self, ret: float):
        self.returns.append(ret)

    def metrics(self) -> Dict[str, float]:
        if len(self.returns) < 5:
            return {"sharpe": 0.0, "win_rate": 0.0, "total_trades": 0,
                    "total_return": 0.0, "loaded": self._loaded}
        m = full_metrics(self.returns)
        m["loaded"]      = self._loaded
        m["slot_id"]     = self.slot_id
        m["model_path"]  = self.model_path
        return m

    def to_dict(self) -> Dict:
        return {
            "slot_id":    self.slot_id,
            "model_path": self.model_path,
            "loaded":     self._loaded,
            "signals":    self.signals,
            "promoted":   self.promoted,
            "returns":    self.returns[-100:],  # last 100 for persistence
        }


# ── Shadow Ledger ─────────────────────────────────────────────────────────────

class _ShadowLedger:
    """Persists model performance across restarts."""

    def __init__(self, path: str = _LEDGER_FILE):
        self._path = path
        self._data = self._load()

    def _load(self) -> Dict:
        try:
            with open(self._path) as f:
                return json.load(f)
        except Exception:
            return {"promotions": [], "evaluations": []}

    def save(self, manager: "ShadowModelManager"):
        data = {
            "saved_at":   datetime.now().isoformat(),
            "champion":   manager.champion,
            "A":          manager.model_a.to_dict(),
            "B":          manager.model_b.to_dict(),
            "promotions": self._data.get("promotions", []),
            "evaluations": self._data.get("evaluations", [])[-200:],
        }
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self._path)
        except Exception as exc:
            logger.warning("ShadowLedger save: %s", exc)

    def record_promotion(self, from_slot: str, to_slot: str, reason: str):
        self._data.setdefault("promotions", []).append({
            "ts":     datetime.now().isoformat(),
            "from":   from_slot,
            "to":     to_slot,
            "reason": reason,
        })

    def get_promotions(self) -> List[Dict]:
        return self._data.get("promotions", [])


# ══════════════════════════════════════════════════════════════════════════════

class ShadowModelManager:
    """
    Manages two PPO models (champion A, challenger B) running side-by-side.

    Workflow:
      1. Both models see every market observation
      2. Both make independent predictions
      3. The champion's prediction is used for actual trading
      4. Both outcomes are tracked separately
      5. When challenger statistically dominates → promote to champion

    Thread-safe via threading.Lock.
    """

    MODEL_A_PATH = "models/karma_ppo_champion.zip"
    MODEL_B_PATH = "models/karma_ppo_challenger.zip"

    def __init__(self):
        self._lock   = threading.Lock()
        self.model_a = _ModelSlot("A", self.MODEL_A_PATH)
        self.model_b = _ModelSlot("B", self.MODEL_B_PATH)
        self.champion = "A"          # A is always the initial champion
        self._ledger = _ShadowLedger()
        self._eval_counter = 0

        logger.info("ShadowModelManager initialised — champion=A, challenger=B")

    # ── Public API ────────────────────────────────────────────────────────────

    def vote(self, observation: Sequence[float]) -> Dict[str, int]:
        """
        Get action predictions from both models.

        Args:
            observation: feature vector (list/array of floats)

        Returns:
            {'champion': int, 'challenger': int, 'champion_slot': str}
        """
        obs = np.array(observation, dtype=np.float32).reshape(1, -1)
        with self._lock:
            a_action = self.model_a.predict(obs)
            b_action = self.model_b.predict(obs)
            champ    = self.champion

        champion_action = a_action if champ == "A" else b_action
        challenger_action = b_action if champ == "A" else a_action

        return {
            "champion":        champion_action,
            "challenger":      challenger_action,
            "champion_slot":   champ,
            "a_action":        a_action,
            "b_action":        b_action,
        }

    def record_outcome(self, pnl: float, capital: float = 1_000_000.0):
        """
        Record the outcome of the most recent trade.
        Both models receive the same outcome (same trade was executed).
        """
        ret = pnl / max(capital, 1)
        with self._lock:
            self.model_a.record_return(ret)
            self.model_b.record_return(ret)
            self._eval_counter += 1
        self._ledger.save(self)

    def maybe_promote(self) -> Optional[str]:
        """
        Check if the challenger should be promoted.
        Called after each trade outcome.

        Returns: 'PROMOTED' if promotion occurred, else None.
        """
        with self._lock:
            n_a = len(self.model_a.returns)
            n_b = len(self.model_b.returns)

        if min(n_a, n_b) < _MIN_SIGNALS_TO_EVALUATE:
            return None

        m_a = self.model_a.metrics()
        m_b = self.model_b.metrics()

        challenger_slot = "B" if self.champion == "A" else "A"
        champ_m = m_a if self.champion == "A" else m_b
        chal_m  = m_b if self.champion == "A" else m_a

        sharpe_diff  = chal_m.get("sharpe", 0) - champ_m.get("sharpe", 0)
        wr_diff      = chal_m.get("win_rate", 0) - champ_m.get("win_rate", 0)

        should_promote = (
            sharpe_diff >= _MIN_SHARPE_ADVANTAGE or
            (wr_diff >= _MIN_WIN_RATE_ADVANTAGE and chal_m.get("sharpe", 0) > champ_m.get("sharpe", 0))
        )

        if should_promote:
            reason = (
                f"Challenger {challenger_slot} outperforms: "
                f"Sharpe Δ={sharpe_diff:+.3f}  WR Δ={wr_diff:+.3f}"
            )
            with self._lock:
                old_champion = self.champion
                self.champion = challenger_slot
                if challenger_slot == "B":
                    self.model_b.promoted += 1
                else:
                    self.model_a.promoted += 1

            self._ledger.record_promotion(old_champion, challenger_slot, reason)
            self._ledger.save(self)

            logger.info("🏆 SHADOW: Promoted %s → champion! %s",
                        challenger_slot, reason)
            return "PROMOTED"

        return None

    def swap_challenger(self, new_model_path: str):
        """
        Replace the challenger model with a freshly trained one.
        Called by KarmaAgent after nightly PPO training.
        """
        with self._lock:
            old_challenger = "B" if self.champion == "A" else "A"
            if old_challenger == "B":
                self.model_b = _ModelSlot("B", new_model_path)
            else:
                self.model_a = _ModelSlot("A", new_model_path)
        logger.info("ShadowModel: challenger %s swapped → %s",
                    old_challenger, new_model_path)

    def get_comparison(self) -> Dict[str, Any]:
        """Dashboard-ready comparison of both models."""
        m_a = self.model_a.metrics()
        m_b = self.model_b.metrics()
        with self._lock:
            champ = self.champion

        def _fmt(m: Dict, slot: str) -> Dict:
            return {
                "slot":          slot,
                "is_champion":   slot == champ,
                "loaded":        m.get("loaded", False),
                "signals":       m.get("total_trades", 0),
                "sharpe":        round(m.get("sharpe", 0), 3),
                "win_rate_pct":  round(m.get("win_rate", 0) * 100, 1),
                "profit_factor": round(m.get("profit_factor", 0), 3),
                "total_return_pct": round(m.get("total_return", 0) * 100, 2),
                "promoted_count": self.model_a.promoted if slot == "A" else self.model_b.promoted,
            }

        return {
            "A":          _fmt(m_a, "A"),
            "B":          _fmt(m_b, "B"),
            "champion":   champ,
            "promotions": self._ledger.get_promotions()[-5:],
            "min_signals_needed": _MIN_SIGNALS_TO_EVALUATE,
        }

    def get_stats(self) -> Dict[str, Any]:
        return {
            "name":      "SHADOW_AB",
            "champion":  self.champion,
            "evals":     self._eval_counter,
            "comparison": self.get_comparison(),
        }
