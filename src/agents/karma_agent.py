"""
KARMA Agent - Reinforcement Learning & Strategy Optimizer
src/agents/karma_agent.py

Learns from trade outcomes and exposes a rich knowledge summary
that the dashboard displays in the Agents → KARMA panel.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict

from ..event_bus.event_bus import BaseAgent, EventType

logger = logging.getLogger(__name__)


class KarmaAgent(BaseAgent):
    """
    KARMA - Continuous Learning Engine

    Responsibilities:
    - Learn from every trade outcome (win / loss / stop)
    - Adjust strategy weights in real-time
    - Track per-symbol and per-regime performance
    - Expose knowledge summary for dashboard

    KPI: Model improvement > 2% monthly Sharpe
    """

    def __init__(self, event_bus, config):
        super().__init__(event_bus=event_bus, config=config, name="KARMA")

        # ── Learning state ────────────────────────────────────────────────
        self.learning_episodes  = 0
        self.knowledge_updates  = 0
        self.session_start      = datetime.now()

        # Strategy weights (adaptive, start at 1.0 = neutral)
        self.strategy_weights: Dict[str, float] = {
            'trend_following': 1.0,
            'mean_reversion':  1.0,
            'breakout':        1.0,
            'volume':          1.0,
            'momentum':        1.0,
            'options_flow':    1.0,
        }

        # Per-strategy stats: wins, losses, total_pnl
        self.strategy_stats: Dict[str, Dict] = {
            s: {'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'last_outcome': ''}
            for s in self.strategy_weights
        }

        # Per-symbol learning memory
        self.symbol_memory: Dict[str, Dict] = {}

        # Per-regime accuracy
        self.regime_stats: Dict[str, Dict] = defaultdict(lambda: {'wins': 0, 'losses': 0})

        # Full episode history (last 200)
        self.performance_history: List[Dict] = []
        self._MAX_HISTORY = 200

        # Discovered patterns / insights
        self.discovered_patterns: List[Dict] = []
        self._MAX_PATTERNS = 50

        # Off-hours training log
        self.training_sessions: List[Dict] = []

        logger.info("KARMA Agent initialized - Learning engine ready")

    # ── Core learning ─────────────────────────────────────────────────────────

    def learn_from_outcome(self, signal: Dict, actual_outcome: Dict):
        """
        Core learning call — triggered on every closed trade.
        Updates strategy weights, symbol memory, and regime stats.
        """
        self.learning_episodes += 1

        strategy = signal.get('strategy') or signal.get('source', 'unknown')
        sym      = signal.get('symbol', '')
        pnl      = actual_outcome.get('pnl', 0)
        regime   = signal.get('regime', 'UNKNOWN')
        event_t  = actual_outcome.get('event', '')

        reward   = 1 if pnl > 0 else -1
        outcome_label = 'WIN' if pnl > 0 else 'LOSS'

        # ── Strategy weight update (gradient ascent with decay) ───────────
        strat_key = strategy.lower().replace(' ', '_').replace('-', '_')
        # Map partial names to known keys
        for k in self.strategy_weights:
            if k in strat_key or strat_key in k:
                strat_key = k
                break

        if strat_key in self.strategy_weights:
            lr = 0.02
            self.strategy_weights[strat_key] += lr * reward
            # Soft clamp [0.3, 2.0] — never fully disable a strategy
            self.strategy_weights[strat_key] = max(0.3, min(2.0, self.strategy_weights[strat_key]))
            # Update per-strategy stats
            st = self.strategy_stats[strat_key]
            if pnl > 0:
                st['wins']    += 1
            else:
                st['losses']  += 1
            st['total_pnl']    += pnl
            st['last_outcome'] = outcome_label

        # ── Symbol memory ─────────────────────────────────────────────────
        if sym:
            if sym not in self.symbol_memory:
                self.symbol_memory[sym] = {'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'trades': 0}
            m = self.symbol_memory[sym]
            m['trades']    += 1
            m['total_pnl'] += pnl
            if pnl > 0: m['wins']   += 1
            else:        m['losses'] += 1

        # ── Regime accuracy ───────────────────────────────────────────────
        if regime and regime != 'UNKNOWN':
            rs = self.regime_stats[regime]
            if pnl > 0: rs['wins']   += 1
            else:        rs['losses'] += 1

        # ── Episode history ───────────────────────────────────────────────
        episode = {
            'episode':   self.learning_episodes,
            'symbol':    sym,
            'strategy':  strategy,
            'regime':    regime,
            'pnl':       round(pnl, 2),
            'outcome':   outcome_label,
            'event':     event_t,
            'timestamp': datetime.now().isoformat(),
        }
        self.performance_history.append(episode)
        if len(self.performance_history) > self._MAX_HISTORY:
            self.performance_history.pop(0)

        # ── Auto-discover patterns ────────────────────────────────────────
        self._try_discover_pattern(sym, strategy, regime, pnl, signal)

        logger.debug(f"KARMA learned: {strategy}/{sym} → {outcome_label} ₹{pnl:+.0f} (ep {self.learning_episodes})")

    def _try_discover_pattern(self, sym, strategy, regime, pnl, signal):
        """Detect repeating profitable patterns and log them."""
        if not sym or len(self.performance_history) < 5:
            return
        # Count recent wins with this strategy+regime combo
        recent = [e for e in self.performance_history[-20:]
                  if e.get('strategy') == strategy and e.get('regime') == regime]
        if len(recent) < 3:
            return
        wins = sum(1 for e in recent if e['pnl'] > 0)
        win_rate = wins / len(recent)
        if win_rate >= 0.70 and pnl > 0:
            pattern = {
                'pattern':    f"{strategy} in {regime} regime",
                'win_rate':   round(win_rate * 100, 1),
                'sample':     len(recent),
                'avg_pnl':    round(sum(e['pnl'] for e in recent) / len(recent), 0),
                'discovered': datetime.now().strftime('%H:%M %d-%b'),
                'symbol':     sym,
                'confidence': 'HIGH' if len(recent) >= 10 else 'MEDIUM',
            }
            # Avoid duplicates
            existing = [p['pattern'] for p in self.discovered_patterns]
            if pattern['pattern'] not in existing:
                self.discovered_patterns.append(pattern)
                if len(self.discovered_patterns) > self._MAX_PATTERNS:
                    self.discovered_patterns.pop(0)
                self.knowledge_updates += 1
                logger.info(f"🧠 KARMA discovered: {pattern['pattern']} ({win_rate*100:.0f}% win rate)")
                self.share_knowledge(pattern)

    # ── Off-hours training ────────────────────────────────────────────────────

    def run_offline_training(self, historical_data: Dict, timeframes: List[str] = None) -> Dict:
        """
        Called during non-trading hours (6 PM – 9 AM IST).
        Reviews historical outcomes across multiple timeframes and
        fine-tunes strategy weights more aggressively.

        historical_data: {symbol: [candle_dicts]} from DataFetcher
        timeframes: list of TFs analysed — for logging only
        """
        tfs = timeframes or ['1min', '5min', '15min', '1hour', '1day']
        t0  = datetime.now()
        symbols_processed = 0
        patterns_found    = 0

        for sym, candles in historical_data.items():
            if not candles or len(candles) < 20:
                continue
            # Replay: detect if price went up or down
            prices = [c.get('close', 0) for c in candles[-50:] if c.get('close')]
            if len(prices) < 10:
                continue
            for i in range(5, len(prices) - 5):
                fwd_ret = (prices[i + 5] - prices[i]) / prices[i] if prices[i] else 0
                # Synthetic outcome — train strategy selector
                self.learn_from_outcome(
                    {'symbol': sym, 'strategy': 'trend_following', 'regime': 'HISTORICAL'},
                    {'pnl': fwd_ret * 10000}   # scaled to ₹ equivalent
                )
            symbols_processed += 1

        elapsed = (datetime.now() - t0).total_seconds()
        session = {
            'timestamp':         t0.strftime('%Y-%m-%d %H:%M'),
            'symbols':           symbols_processed,
            'timeframes':        tfs,
            'episodes':          self.learning_episodes,
            'patterns_found':    len(self.discovered_patterns),
            'duration_sec':      round(elapsed, 1),
            'best_strategy':     self.get_best_strategy(),
        }
        self.training_sessions.append(session)
        if len(self.training_sessions) > 30:
            self.training_sessions.pop(0)

        logger.info(
            f"🧠 KARMA offline training: {symbols_processed} symbols × {len(tfs)} TFs "
            f"in {elapsed:.1f}s · best={self.get_best_strategy()}"
        )
        return session

    # ── Knowledge sharing ─────────────────────────────────────────────────────

    def share_knowledge(self, knowledge: Dict):
        """Broadcast discovered pattern via event bus."""
        self.publish_event(EventType.STRATEGY_DISCOVERED, {
            'source':    'KARMA',
            'knowledge': knowledge,
            'timestamp': datetime.now().isoformat(),
        })

    # ── Public accessors ──────────────────────────────────────────────────────

    def get_optimized_weights(self) -> Dict[str, float]:
        return self.strategy_weights.copy()

    def get_best_strategy(self) -> str:
        return max(self.strategy_weights, key=self.strategy_weights.get)

    def get_worst_strategy(self) -> str:
        return min(self.strategy_weights, key=self.strategy_weights.get)

    def get_knowledge_summary(self) -> Dict:
        """
        Full knowledge state for the dashboard Agents → KARMA panel.
        """
        total = len(self.performance_history)
        wins  = sum(1 for e in self.performance_history if e['pnl'] > 0)
        losses= total - wins
        wr    = round(wins / total * 100, 1) if total else 0
        total_pnl = sum(e['pnl'] for e in self.performance_history)

        # Per-strategy win rates
        strat_wr = {}
        for s, st in self.strategy_stats.items():
            tot = st['wins'] + st['losses']
            strat_wr[s] = {
                'weight':    round(self.strategy_weights.get(s, 1.0), 3),
                'win_rate':  round(st['wins'] / tot * 100, 1) if tot else 0,
                'trades':    tot,
                'total_pnl': round(st['total_pnl'], 0),
                'status':    'STRONG' if self.strategy_weights.get(s, 1.0) > 1.3
                             else 'WEAK' if self.strategy_weights.get(s, 1.0) < 0.6
                             else 'NORMAL',
            }

        # Per-regime accuracy
        regime_wr = {}
        for reg, rs in self.regime_stats.items():
            tot = rs['wins'] + rs['losses']
            regime_wr[reg] = round(rs['wins'] / tot * 100, 1) if tot else 0

        # Best symbols
        sym_perf = sorted(
            [{'symbol': k, **v} for k, v in self.symbol_memory.items()],
            key=lambda x: x['total_pnl'], reverse=True
        )[:5]

        # Uptime
        uptime_hrs = (datetime.now() - self.session_start).total_seconds() / 3600

        return {
            'learning_episodes':  self.learning_episodes,
            'knowledge_updates':  self.knowledge_updates,
            'total_trades':       total,
            'wins':               wins,
            'losses':             losses,
            'overall_win_rate':   wr,
            'total_pnl':          round(total_pnl, 0),
            'best_strategy':      self.get_best_strategy(),
            'worst_strategy':     self.get_worst_strategy(),
            'strategy_weights':   strat_wr,
            'regime_accuracy':    regime_wr,
            'top_symbols':        sym_perf,
            'discovered_patterns': self.discovered_patterns[-10:],
            'recent_episodes':    self.performance_history[-10:],
            'last_training':      self.training_sessions[-1] if self.training_sessions else None,
            'uptime_hours':       round(uptime_hrs, 1),
        }

    def update(self):
        """Periodic housekeeping — called each main loop iteration."""
        pass

    def get_stats(self) -> Dict:
        return {
            'name':              self.name,
            'active':            self.is_active,
            'learning_episodes': self.learning_episodes,
            'knowledge_updates': self.knowledge_updates,
            'current_weights':   self.strategy_weights,
            'best_strategy':     self.get_best_strategy(),
            'kpi':               'Model improvement > 2% Sharpe',
        }
