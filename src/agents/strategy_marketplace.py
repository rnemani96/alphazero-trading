"""
src/agents/strategy_marketplace.py  —  AlphaZero Capital
══════════════════════════════════════════════════════════
Strategy Marketplace — Competition-Driven Weight Allocation

Every strategy is treated as an independent "agent" competing for capital.
  - Each strategy starts with equal weight (1.0)
  - Weight increases when a strategy wins, decreases when it loses
  - Strategies that consistently underperform are demoted to "shadow" mode
  - Strategies in shadow mode still generate signals but receive 0 capital
  - Top performers receive bonus capital allocation
  - A tournament runs weekly comparing strategies head-to-head on the same data

Design:
  - Fully event-bus driven: listens to SIGNAL_EVALUATED events from LENS
  - Publishes STRATEGY_DISCOVERED when a new champion emerges
  - Weights exported to TITAN so signal aggregation uses live rankings
  - Thread-safe, persisted to logs/marketplace.json

Usage:
    mp = StrategyMarketplace(event_bus, config)
    mp.subscribe_to_lens_events()
    weights = mp.get_weights_for_titan()   # inject into TITAN
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..event_bus.event_bus import BaseAgent, EventType
from ..utils.stats import sharpe, win_rate, full_metrics

logger = logging.getLogger("Marketplace")

_LOG_DIR    = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_STATE_FILE = str(_LOG_DIR / "marketplace.json")

# Weight bounds
_MIN_WEIGHT    = 0.10   # strategies never fully disabled — they keep a floor
_MAX_WEIGHT    = 3.00   # best strategies get 3× normal capital
_DEMOTION_THR  = 0.25   # weight below this → shadow mode
_PROMOTION_THR = 1.80   # weight above this → champion tier

# Gradient update
_LR_WIN  = 0.03   # learning rate on win
_LR_LOSS = 0.02   # learning rate on loss (asymmetric)

# Tournament settings
_TOURNAMENT_MIN_TRADES = 10   # minimum trades before a strategy can compete


class _StrategyRecord:
    """Tracks all stats for a single strategy."""

    def __init__(self, strategy_id: str):
        self.strategy_id  = strategy_id
        self.weight       = 1.0
        self.wins         = 0
        self.losses       = 0
        self.total_pnl    = 0.0
        self.returns: List[float] = []
        self.tier         = "NORMAL"     # SHADOW | NORMAL | CHAMPION
        self.last_outcome = ""
        self.tournament_wins  = 0
        self.tournament_losses= 0
        self.created_at   = datetime.now().isoformat()

    @property
    def total_trades(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / max(self.total_trades, 1)

    @property
    def sharpe_ratio(self) -> float:
        return sharpe(self.returns) if len(self.returns) >= 5 else 0.0

    def update(self, won: bool, pnl: float):
        """Gradient update after a trade outcome."""
        if won:
            self.wins   += 1
            delta        = _LR_WIN
        else:
            self.losses += 1
            delta        = -_LR_LOSS

        self.total_pnl += pnl
        self.returns.append(pnl / 10_000)   # normalise to fraction
        if len(self.returns) > 300:
            self.returns.pop(0)

        # Multiplicative weight update
        self.weight = max(_MIN_WEIGHT, min(_MAX_WEIGHT, self.weight * (1 + delta)))
        self.last_outcome = "WIN" if won else "LOSS"

        # Update tier
        if self.weight < _DEMOTION_THR:
            self.tier = "SHADOW"
        elif self.weight >= _PROMOTION_THR:
            self.tier = "CHAMPION"
        else:
            self.tier = "NORMAL"

    def to_dict(self) -> Dict:
        return {
            "strategy_id":    self.strategy_id,
            "weight":         round(self.weight, 4),
            "wins":           self.wins,
            "losses":         self.losses,
            "total_pnl":      round(self.total_pnl, 2),
            "win_rate":       round(self.win_rate, 4),
            "sharpe":         round(self.sharpe_ratio, 3),
            "tier":           self.tier,
            "last_outcome":   self.last_outcome,
            "tournament_wins":  self.tournament_wins,
            "tournament_losses":self.tournament_losses,
            "created_at":     self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "_StrategyRecord":
        rec = cls(d["strategy_id"])
        rec.weight         = d.get("weight", 1.0)
        rec.wins           = d.get("wins", 0)
        rec.losses         = d.get("losses", 0)
        rec.total_pnl      = d.get("total_pnl", 0.0)
        rec.tier           = d.get("tier", "NORMAL")
        rec.last_outcome   = d.get("last_outcome", "")
        rec.tournament_wins   = d.get("tournament_wins", 0)
        rec.tournament_losses = d.get("tournament_losses", 0)
        rec.created_at     = d.get("created_at", datetime.now().isoformat())
        return rec


class StrategyMarketplace(BaseAgent):
    """
    Strategy Marketplace — competition-based dynamic weight allocation.

    Public API:
        marketplace.on_signal_evaluated(signal, outcome)  ← from LENS
        marketplace.get_weights_for_titan()               → inject into TITAN
        marketplace.run_tournament()                       → head-to-head comparison
        marketplace.get_leaderboard()                      → sorted list
        marketplace.get_stats()                            → dashboard payload
    """

    def __init__(self, event_bus, config: Dict[str, Any]):
        super().__init__(event_bus=event_bus, config=config, name="MARKETPLACE")

        self._lock     = threading.Lock()
        self._registry: Dict[str, _StrategyRecord] = {}
        self._history:  List[Dict] = []          # recent outcome events
        self._champion: Optional[str] = None
        self._tournaments_run = 0

        self._load_state()
        self.subscribe(EventType.SIGNAL_EVALUATED, self._on_evaluated)
        logger.info("StrategyMarketplace initialised — %d strategies tracked",
                    len(self._registry))

    # ── Event handler ─────────────────────────────────────────────────────────

    def _on_evaluated(self, event):
        """Called by LENS after a signal is evaluated."""
        p        = event.payload
        signal   = p.get("signal", {})
        outcome  = p.get("outcome", {})
        strat_id = signal.get("strategy") or signal.get("source") or "UNKNOWN"
        pnl      = float(outcome.get("pnl", 0))
        won      = pnl > 0

        self.on_signal_evaluated(strat_id, won, pnl)

    def on_signal_evaluated(self, strategy_id: str, won: bool, pnl: float):
        """Direct call (also usable without event bus)."""
        with self._lock:
            if strategy_id not in self._registry:
                self._registry[strategy_id] = _StrategyRecord(strategy_id)
            rec = self._registry[strategy_id]
            old_tier = rec.tier
            rec.update(won, pnl)

            # Tier change notifications
            if rec.tier != old_tier:
                logger.info("Marketplace: %s → tier %s (weight=%.2f)",
                            strategy_id, rec.tier, rec.weight)
                if rec.tier == "CHAMPION":
                    self._champion = strategy_id
                    try:
                        self.publish_event(EventType.STRATEGY_DISCOVERED, {
                            "source":      "MARKETPLACE",
                            "champion":    strategy_id,
                            "weight":      rec.weight,
                            "win_rate":    rec.win_rate,
                            "sharpe":      rec.sharpe_ratio,
                            "timestamp":   datetime.now().isoformat(),
                        })
                    except Exception:
                        pass

            self._history.append({
                "ts":       datetime.now().strftime("%H:%M %d-%b"),
                "strategy": strategy_id,
                "won":      won,
                "pnl":      round(pnl, 0),
                "weight":   round(rec.weight, 3),
                "tier":     rec.tier,
            })
            if len(self._history) > 500:
                self._history.pop(0)

        self._save_state()

    # ── Weight export ──────────────────────────────────────────────────────────

    def get_weights_for_titan(self) -> Dict[str, float]:
        """
        Returns a weight dict that TITAN can use when aggregating signals.
        Shadow strategies get 0 weight.
        Champions get their full boosted weight.
        """
        with self._lock:
            weights = {}
            for sid, rec in self._registry.items():
                weights[sid] = 0.0 if rec.tier == "SHADOW" else rec.weight
        return weights

    # ── Tournament ────────────────────────────────────────────────────────────

    def run_tournament(self) -> Dict[str, Any]:
        """
        Head-to-head: compare each pair of strategies by Sharpe ratio
        on the overlapping set of trades. Update tournament W/L records.

        Returns tournament bracket results.
        """
        with self._lock:
            eligible = {
                sid: rec for sid, rec in self._registry.items()
                if rec.total_trades >= _TOURNAMENT_MIN_TRADES
            }

        if len(eligible) < 2:
            return {"status": "NOT_ENOUGH_STRATEGIES", "eligible": len(eligible)}

        bracket: List[Dict] = []
        sids = sorted(eligible.keys())

        for i in range(len(sids)):
            for j in range(i + 1, len(sids)):
                a_id = sids[i];  a = eligible[a_id]
                b_id = sids[j];  b = eligible[b_id]

                a_sh = a.sharpe_ratio
                b_sh = b.sharpe_ratio

                if abs(a_sh - b_sh) < 0.05:
                    # Tiebreaker: win rate
                    winner_id = a_id if a.win_rate >= b.win_rate else b_id
                else:
                    winner_id = a_id if a_sh > b_sh else b_id
                loser_id = b_id if winner_id == a_id else a_id

                with self._lock:
                    if winner_id in self._registry:
                        self._registry[winner_id].tournament_wins += 1
                    if loser_id in self._registry:
                        self._registry[loser_id].tournament_losses += 1

                bracket.append({
                    "match":    f"{a_id} vs {b_id}",
                    "winner":   winner_id,
                    "loser":    loser_id,
                    "a_sharpe": round(a_sh, 3),
                    "b_sharpe": round(b_sh, 3),
                })

        with self._lock:
            self._tournaments_run += 1

        self._save_state()
        logger.info("Tournament complete: %d matches, %d strategies",
                    len(bracket), len(eligible))

        return {
            "status":           "COMPLETE",
            "matches":          bracket,
            "strategies_competed": len(eligible),
            "tournament_number":  self._tournaments_run,
        }

    # ── Leaderboard ───────────────────────────────────────────────────────────

    def get_leaderboard(self, top_n: int = 20) -> List[Dict]:
        """Sorted by weight descending."""
        with self._lock:
            recs = sorted(self._registry.values(),
                          key=lambda r: r.weight, reverse=True)
        return [r.to_dict() for r in recs[:top_n]]

    def get_shadow_list(self) -> List[str]:
        with self._lock:
            return [sid for sid, r in self._registry.items() if r.tier == "SHADOW"]

    def get_champion(self) -> Optional[str]:
        with self._lock:
            return self._champion

    # ── Stats for dashboard ───────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            n_total    = len(self._registry)
            n_champion = sum(1 for r in self._registry.values() if r.tier == "CHAMPION")
            n_shadow   = sum(1 for r in self._registry.values() if r.tier == "SHADOW")
            top5       = sorted(self._registry.values(),
                                key=lambda r: r.weight, reverse=True)[:5]

        return {
            "name":              self.name,
            "active":            self.is_active,
            "total_strategies":  n_total,
            "champions":         n_champion,
            "shadow":            n_shadow,
            "normal":            n_total - n_champion - n_shadow,
            "champion_id":       self._champion,
            "tournaments_run":   self._tournaments_run,
            "top_5":             [r.to_dict() for r in top5],
            "recent_outcomes":   self._history[-10:],
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_state(self):
        with self._lock:
            data = {
                "saved_at":    datetime.now().isoformat(),
                "champion":    self._champion,
                "tournaments": self._tournaments_run,
                "registry":    {sid: rec.to_dict() for sid, rec in self._registry.items()},
            }
        tmp = _STATE_FILE + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, _STATE_FILE)
        except Exception as exc:
            logger.warning("Marketplace save: %s", exc)

    def _load_state(self):
        try:
            with open(_STATE_FILE) as f:
                data = json.load(f)
            self._champion       = data.get("champion")
            self._tournaments_run = data.get("tournaments", 0)
            for sid, d in data.get("registry", {}).items():
                self._registry[sid] = _StrategyRecord.from_dict(d)
            logger.info("Marketplace: loaded %d strategies from state",
                        len(self._registry))
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.warning("Marketplace load: %s", exc)
