"""
KARMA Agent - Reinforcement Learning & Strategy Optimizer

Learns from outcomes and improves system performance over time.
The system's continuous learning engine.

FIXES:
- Removed markdown header block (lines 1-5 + closing ```) that caused SyntaxError
"""

import logging
from typing import Dict, List, Any
from datetime import datetime

from ..event_bus.event_bus import BaseAgent, EventType

logger = logging.getLogger(__name__)


class KarmaAgent(BaseAgent):
    """
    KARMA - Learning & RL Agent

    Responsibilities:
    - Learn from trade outcomes
    - Optimize strategy weights
    - Adapt to market changes
    - Knowledge sharing across agents
    - Performance improvement

    KPI: Model improvement > 2% monthly Sharpe
    """

    def __init__(self, event_bus, config):
        super().__init__(event_bus=event_bus, config=config, name="KARMA")

        # Learning state
        self.learning_episodes = 0
        self.knowledge_updates = 0

        # Strategy weights (adaptive)
        self.strategy_weights = {
            'trend_following': 1.0,
            'mean_reversion': 1.0,
            'breakout': 1.0,
            'volume': 1.0
        }

        # Performance history
        self.performance_history: List[Dict] = []

        logger.info("KARMA Agent initialized - Learning engine ready")

    def learn_from_outcome(
        self,
        signal: Dict[str, Any],
        actual_outcome: Dict[str, Any]
    ):
        """
        Learn from trade outcome.

        Args:
            signal: Original trading signal
            actual_outcome: What actually happened
        """
        self.learning_episodes += 1

        strategy = signal.get('strategy', 'unknown')
        pnl = actual_outcome.get('pnl', 0)
        reward = 1 if pnl > 0 else -1

        if strategy in self.strategy_weights:
            learning_rate = 0.01
            self.strategy_weights[strategy] += learning_rate * reward

            # Normalize weights so they sum to the number of strategies
            total_weight = sum(self.strategy_weights.values())
            if total_weight > 0:
                num_strategies = len(self.strategy_weights)
                for s in self.strategy_weights:
                    self.strategy_weights[s] = (
                        self.strategy_weights[s] / total_weight * num_strategies
                    )

        self.performance_history.append({
            'episode': self.learning_episodes,
            'strategy': strategy,
            'reward': reward,
            'pnl': pnl,
            'timestamp': datetime.now().isoformat()
        })

        logger.debug(
            f"KARMA learned: {strategy} → reward={reward} "
            f"(Episode {self.learning_episodes})"
        )

    def share_knowledge(self, knowledge: Dict[str, Any]):
        """Share discovered patterns with other agents via event bus."""
        self.knowledge_updates += 1

        self.publish_event(
            EventType.STRATEGY_DISCOVERED,
            {
                'source': 'KARMA',
                'knowledge': knowledge,
                'timestamp': datetime.now().isoformat()
            }
        )

        logger.info(f"KARMA shared knowledge: {knowledge.get('pattern')}")

    def get_optimized_weights(self) -> Dict[str, float]:
        """Get current optimized strategy weights."""
        return self.strategy_weights.copy()

    def get_best_strategy(self) -> str:
        """Return the strategy with the highest current weight."""
        return max(self.strategy_weights, key=self.strategy_weights.get)  # type: ignore[arg-type]

    def update(self):
        """Periodic housekeeping — called each main loop iteration."""
        pass  # KARMA updates reactively via learn_from_outcome(); nothing to poll

    def get_stats(self) -> Dict[str, Any]:
        """Get KARMA statistics."""
        return {
            'name': self.name,
            'active': self.is_active,
            'learning_episodes': self.learning_episodes,
            'knowledge_updates': self.knowledge_updates,
            'current_weights': self.strategy_weights,
            'best_strategy': self.get_best_strategy(),
            'kpi': 'Model improvement > 2% Sharpe'
        }
