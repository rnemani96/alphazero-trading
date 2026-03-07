"""
AlphaZero Capital — Agent Performance Tracker
src/reporting/agent_performance.py

Tracks per-agent statistics (signals, win rate, P&L, accuracy) and
writes them to logs/agent_performance.json for the dashboard and PDF reports.
"""

from __future__ import annotations
import os, json, logging, threading
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'logs', 'agent_performance.json')
_LOCK = threading.Lock()


class AgentPerformanceTracker:
    """
    Thread-safe per-agent statistics tracker.

    Usage:
        tracker = AgentPerformanceTracker()
        tracker.record_signal('TITAN', 'RELIANCE', 'BUY', confidence=0.78)
        tracker.record_outcome('TITAN', 'RELIANCE', pnl=1250.0, won=True)
        summary = tracker.get_summary()
    """

    def __init__(self):
        self._data: Dict[str, Any] = self._load()
        logger.info("AgentPerformanceTracker initialised")

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_signal(self, agent: str, symbol: str, signal: str, confidence: float = 0.0):
        """Call when an agent generates a signal."""
        with _LOCK:
            a = self._ensure(agent)
            a['signals_generated'] += 1
            a['last_signal'] = {
                'symbol': symbol, 'signal': signal,
                'confidence': confidence,
                'timestamp': datetime.now().isoformat()
            }
            self._save()

    def record_outcome(self, agent: str, symbol: str, pnl: float, won: bool):
        """Call when a trade attributed to this agent closes."""
        with _LOCK:
            a = self._ensure(agent)
            a['trades_attributed'] += 1
            a['total_pnl'] += pnl
            if won:
                a['winning_trades'] += 1
            else:
                a['losing_trades'] += 1
            total = a['winning_trades'] + a['losing_trades']
            a['win_rate'] = a['winning_trades'] / total if total else 0.0
            a['last_outcome'] = {
                'symbol': symbol, 'pnl': pnl, 'won': won,
                'timestamp': datetime.now().isoformat()
            }
            self._save()

    def record_accuracy(self, agent: str, correct: bool):
        """Call when an agent's prediction is verified (e.g. regime call)."""
        with _LOCK:
            a = self._ensure(agent)
            a['predictions'] = a.get('predictions', 0) + 1
            if correct:
                a['correct_predictions'] = a.get('correct_predictions', 0) + 1
            total = a['predictions']
            a['accuracy'] = a['correct_predictions'] / total if total else 0.0
            self._save()

    def set_active(self, agent: str, active: bool):
        with _LOCK:
            self._ensure(agent)['active'] = active
            self._save()

    def get_agent(self, agent: str) -> Dict:
        with _LOCK:
            return dict(self._ensure(agent))

    def get_summary(self) -> Dict[str, Any]:
        """Return full summary dict — used by dashboard and PDF reports."""
        with _LOCK:
            return {name: dict(data) for name, data in self._data.items()}

    def get_leaderboard(self) -> list:
        """Return agents sorted by P&L descending."""
        with _LOCK:
            ranked = sorted(
                [{'name': n, **d} for n, d in self._data.items()],
                key=lambda x: x.get('total_pnl', 0),
                reverse=True
            )
            for i, a in enumerate(ranked):
                a['rank'] = i + 1
                a['score'] = self._score(a)
            return ranked

    def reset_daily(self):
        """Reset daily counters at midnight."""
        with _LOCK:
            for a in self._data.values():
                a['daily_signals']     = 0
                a['daily_pnl']         = 0.0
                a['daily_trades']      = 0
                a['daily_wins']        = 0
            self._save()
        logger.info("Agent daily counters reset")

    # ── Internals ─────────────────────────────────────────────────────────────

    def _ensure(self, agent: str) -> Dict:
        if agent not in self._data:
            self._data[agent] = {
                'signals_generated':  0,
                'trades_attributed':  0,
                'winning_trades':     0,
                'losing_trades':      0,
                'win_rate':           0.0,
                'total_pnl':          0.0,
                'daily_pnl':          0.0,
                'daily_signals':      0,
                'daily_trades':       0,
                'daily_wins':         0,
                'accuracy':           0.0,
                'predictions':        0,
                'correct_predictions':0,
                'active':             True,
                'last_signal':        None,
                'last_outcome':       None,
                'created':            datetime.now().isoformat(),
            }
        return self._data[agent]

    def _score(self, a: Dict) -> float:
        """Composite score: weighted win-rate, P&L, accuracy."""
        wr  = a.get('win_rate', 0)
        pnl = max(0, a.get('total_pnl', 0)) / 100_000  # normalise
        acc = a.get('accuracy', 0)
        return round(0.4 * wr * 100 + 0.4 * pnl + 0.2 * acc * 100, 1)

    def _load(self) -> Dict:
        os.makedirs(os.path.dirname(_FILE), exist_ok=True)
        try:
            with open(_FILE) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self):
        tmp = _FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(self._data, f, indent=2, default=str)
        os.replace(tmp, _FILE)
