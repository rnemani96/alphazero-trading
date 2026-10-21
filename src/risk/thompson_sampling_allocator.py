"""
src/risk/thompson_sampling_allocator.py
════════════════════════════════════════
Phase 6: Auto-Evolving Architecture (Evolution 2.0)
Thompson Sampling Multi-Armed Bandit Capital Allocator & Experience Replay Buffer.

Orchestrates capital allocation and conviction scaling across sub-agents and
trading strategies (Trend Following, Mean Reversion, Breakout, Volatility, Options Flow)
using Bayesian Thompson Sampling for mathematically optimal exploration/exploitation.

Mathematical Foundation:
  For each strategy k:
    Win count:   α_k = 1 + Wins_k
    Loss count:  β_k = 1 + Losses_k
    Sample:      θ_k ~ Beta(α_k, β_k)
    Allocation:  Weight_k = (θ_k * Sharpe_k) / Σ (θ_j * Sharpe_j)

Experience Replay Buffer:
  Maintains a FIFO deque of recent trade transitions (features, strategy, action, pnl, reward)
  to enable online learning without catastrophic forgetting.
"""

from __future__ import annotations
import json
import logging
import math
import os
import random
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ThompsonSampling")

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_STATE_FILE = _LOG_DIR / "thompson_sampling_state.json"


class ExperienceTransition:
    """Represents a recorded trade experience for online replay."""
    def __init__(
        self,
        strategy_id: str,
        symbol: str,
        action: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        regime: str,
        vix: float,
        timestamp: str = "",
    ):
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.action = action
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.pnl = pnl
        self.regime = regime
        self.vix = vix
        self.timestamp = timestamp or datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "action": self.action,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "regime": self.regime,
            "vix": self.vix,
            "timestamp": self.timestamp,
        }


class ThompsonSamplingAllocator:
    """
    Bayesian Thompson Sampling Multi-Armed Bandit for Strategy Capital Allocation.
    """

    def __init__(self, buffer_size: int = 500):
        self.buffer_size = buffer_size
        # Strategy priors: {strategy_id: {'alpha': float, 'beta': float, 'pnl': float, 'sharpe': float}}
        self.priors: Dict[str, Dict[str, float]] = {}
        # Experience replay buffer
        self.replay_buffer: deque = deque(maxlen=buffer_size)
        # Allocation cache
        self.current_weights: Dict[str, float] = {}
        self._load_state()

    def register_strategy(self, strategy_id: str, initial_alpha: float = 2.0, initial_beta: float = 2.0):
        """Registers a new strategy with prior Beta(2, 2) (mean 0.50 win rate)."""
        if strategy_id not in self.priors:
            self.priors[strategy_id] = {
                "alpha": initial_alpha,
                "beta": initial_beta,
                "total_pnl": 0.0,
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "sharpe": 1.0,
            }
            self.current_weights[strategy_id] = 1.0

    def record_trade_outcome(
        self,
        strategy_id: str,
        pnl: float,
        symbol: str = "",
        action: str = "BUY",
        entry_price: float = 0.0,
        exit_price: float = 0.0,
        regime: str = "TRENDING",
        vix: float = 15.0,
    ):
        """
        Updates Bayesian posterior distribution and records transition into replay buffer.
        """
        if strategy_id not in self.priors:
            self.register_strategy(strategy_id)

        strat = self.priors[strategy_id]
        strat["trades"] += 1
        strat["total_pnl"] += pnl

        won = pnl > 0
        if won:
            strat["wins"] += 1
            # Bayesian posterior update: alpha increases on success
            strat["alpha"] += 1.0
        else:
            strat["losses"] += 1
            # Bayesian posterior update: beta increases on failure
            strat["beta"] += 1.0

        # Update Sharpe estimate
        win_rate = strat["wins"] / max(1, strat["trades"])
        strat["sharpe"] = max(0.2, (win_rate - 0.45) * 4.0 + 1.0)

        # Append to experience replay buffer
        transition = ExperienceTransition(
            strategy_id=strategy_id,
            symbol=symbol,
            action=action,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            regime=regime,
            vix=vix,
        )
        self.replay_buffer.append(transition)

        # Re-compute Thompson Sampling weights
        self._recompute_weights()
        self._save_state()

        logger.info(
            f"🎯 Thompson Sampling update [{strategy_id}]: "
            f"Beta({strat['alpha']:.1f}, {strat['beta']:.1f}) | "
            f"WinRate={win_rate:.1%} | Weight={self.current_weights.get(strategy_id, 1.0):.2f}"
        )

    def sample_weights(self) -> Dict[str, float]:
        """
        Draws Thompson Samples from Beta posterior for all active strategies
        and returns normalized capital multiplier weights.
        """
        if not self.priors:
            return {}

        samples: Dict[str, float] = {}
        for s_id, stats in self.priors.items():
            # Draw theta from Beta(alpha, beta) distribution
            theta = random.betavariate(stats["alpha"], stats["beta"])
            # Scale by recent Sharpe
            score = max(0.05, theta * stats["sharpe"])
            samples[s_id] = score

        # Normalize relative to baseline mean of 1.0
        total_score = sum(samples.values())
        n = len(samples)
        if total_score > 0 and n > 0:
            avg_score = total_score / n
            weights = {s_id: max(0.20, min(2.50, val / avg_score)) for s_id, val in samples.items()}
        else:
            weights = {s_id: 1.0 for s_id in self.priors}

        self.current_weights = weights
        return weights

    def get_allocation_multiplier(self, strategy_id: str) -> float:
        """Returns the dynamic capital allocation factor for a specific strategy (0.20x to 2.50x)."""
        if strategy_id not in self.current_weights:
            self.register_strategy(strategy_id)
            self.sample_weights()
        return self.current_weights.get(strategy_id, 1.0)

    def sample_replay_batch(self, batch_size: int = 32) -> List[Dict[str, Any]]:
        """Samples a uniform random mini-batch from experience buffer for online learning."""
        if len(self.replay_buffer) == 0:
            return []
        k = min(batch_size, len(self.replay_buffer))
        batch = random.sample(list(self.replay_buffer), k)
        return [t.to_dict() for t in batch]

    def _recompute_weights(self):
        """Periodically draws fresh Thompson samples."""
        self.sample_weights()

    def _save_state(self):
        try:
            payload = {
                "priors": self.priors,
                "current_weights": self.current_weights,
                "buffer_count": len(self.replay_buffer),
                "updated_at": datetime.now().isoformat(),
            }
            with open(_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to save Thompson Sampling state: {e}")

    def _load_state(self):
        if not _STATE_FILE.exists():
            return
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.priors = data.get("priors", {})
                self.current_weights = data.get("current_weights", {})
                logger.info(f"Loaded Thompson Sampling state: {len(self.priors)} strategies")
        except Exception as e:
            logger.debug(f"Failed to load Thompson Sampling state: {e}")


# Singleton instance
_allocator_instance: Optional[ThompsonSamplingAllocator] = None


def get_thompson_allocator() -> ThompsonSamplingAllocator:
    global _allocator_instance
    if _allocator_instance is None:
        _allocator_instance = ThompsonSamplingAllocator()
    return _allocator_instance
