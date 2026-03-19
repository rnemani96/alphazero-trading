"""
KARMA Agent — Reinforcement Learning & Continuous Learning Engine
src/agents/karma_agent.py

Architecture:
  1. ONLINE LEARNING  — every closed trade updates strategy weights via
                         gradient-style online update (no PPO needed for this layer).
  2. OFFLINE PPO      — post-market nightly job fine-tunes a Stable-Baselines3 PPO
                         agent on 8 months of NSE replay.
  3. KNOWLEDGE SHARE  — broadcasts discovered winning patterns to ZEUS for relay.

KPI: Model improvement > 2% monthly Sharpe

Design rules:
  - No duplicate indicator code (uses src/utils/stats.py)
  - @safe_run decorator wraps all external calls
  - Thread-safe state via threading.Lock
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from ..event_bus.event_bus import BaseAgent, EventType
from ..utils.stats import full_metrics, sharpe, kelly_fraction

logger = logging.getLogger(__name__)


# ── Decorator ─────────────────────────────────────────────────────────────────

def _safe(fn: Callable) -> Callable:
    """Silently catch and log exceptions so one bad trade never kills the loop."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.debug("%s failed: %s", fn.__name__, exc)
            return None
    return wrapper


# ── RL environment wrapper (lazy import) ─────────────────────────────────────

class _NullModel:
    """Fallback when stable-baselines3 not installed."""
    def predict(self, obs, *a, **k):
        return [0], None


def _load_ppo(path: str):
    try:
        from stable_baselines3 import PPO
        if os.path.exists(path):
            m = PPO.load(path)
            logger.info("KARMA: PPO model loaded from %s", path)
            return m
    except ImportError:
        logger.warning("KARMA: stable-baselines3 not installed — PPO disabled")
    except Exception as exc:
        logger.warning("KARMA: PPO load failed (%s) — starting fresh", exc)
    return None


def _train_ppo(df_candles: Dict[str, List[Dict]], save_path: str) -> Optional[object]:
    """Fine-tune PPO on NSE replay environment from historical candles."""
    try:
        import numpy as np
        from stable_baselines3 import PPO
        from stable_baselines3.common.env_util import make_vec_env
        import gymnasium as gym

        class _ReplayEnv(gym.Env):
            """Minimal NSE replay env for PPO fine-tuning."""
            def __init__(self, candles_flat):
                super().__init__()
                self.candles   = candles_flat
                self.idx       = 0
                self.position  = 0
                self.entry     = 0.0
                low  = np.array([-np.inf] * 8, dtype=np.float32)
                high = np.array([np.inf]  * 8, dtype=np.float32)
                self.observation_space = gym.spaces.Box(low, high, dtype=np.float32)
                self.action_space      = gym.spaces.Discrete(3)   # 0=hold 1=buy 2=sell

            def _obs(self):
                c = self.candles[self.idx]
                price = float(c.get('close', 1))
                return np.array([
                    float(c.get('rsi',    50)) / 100,
                    float(c.get('ema20',   price)) / price - 1,
                    float(c.get('ema50',   price)) / price - 1,
                    float(c.get('atr',     0))    / max(price, 1),
                    float(c.get('volume_zscore', 0)) / 4,
                    float(c.get('macd',    0))    / max(price, 1),
                    float(c.get('adx',     20))   / 100,
                    self.position,
                ], dtype=np.float32)

            def reset(self, **kwargs):
                self.idx = 0; self.position = 0; self.entry = 0.0
                return self._obs(), {}

            def step(self, action):
                c     = self.candles[self.idx]
                price = float(c.get('close', 1))
                reward = 0.0
                if action == 1 and self.position == 0:
                    self.position = 1; self.entry = price
                elif action == 2 and self.position == 1:
                    reward = (price - self.entry) / max(self.entry, 1) * 100
                    self.position = 0; self.entry = 0.0
                self.idx += 1
                done = self.idx >= len(self.candles) - 1
                return self._obs(), reward, done, False, {}

        # Flatten candles
        flat = []
        for sym_candles in df_candles.values():
            flat.extend(sym_candles)
        if len(flat) < 100:
            return None

        env  = _ReplayEnv(flat)
        venv = make_vec_env(lambda: env, n_envs=1)

        existing = _load_ppo(save_path)
        if existing:
            model = existing
            model.set_env(venv)
        else:
            model = PPO('MlpPolicy', venv, verbose=0,
                        learning_rate=3e-4, n_steps=512, batch_size=64,
                        n_epochs=10, gamma=0.99)

        model.learn(total_timesteps=max(1000, len(flat) * 2))
        os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
        model.save(save_path)
        logger.info("KARMA: PPO trained on %d steps, saved → %s", len(flat), save_path)
        return model

    except Exception as exc:
        logger.warning("KARMA: PPO training failed — %s", exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════

class KarmaAgent(BaseAgent):
    """
    KARMA — Continuous Learning Engine.

    Two learning pathways:
      A. Online (each trade)  → update strategy weights
      B. Offline (post-market) → PPO fine-tune on historical replay

    Public API:
        karma.learn_from_outcome(signal, actual_outcome)  → call after every close
        karma.run_offline_training(historical_data)        → call 6 PM IST daily
        karma.get_optimized_weights()                      → strategy weight dict
        karma.get_knowledge_summary()                      → dashboard payload
    """

    MODEL_PATH = 'models/karma_ppo.zip'
    _STRATEGY_KEYS = [
        'trend_following', 'mean_reversion', 'breakout',
        'volume', 'momentum', 'options_flow', 'vwap',
    ]

    def __init__(self, event_bus, config: Dict[str, Any]):
        super().__init__(event_bus=event_bus, config=config, name="KARMA")

        self._lock              = threading.Lock()
        self.session_start      = datetime.now()
        self.learning_episodes  = 0
        self.knowledge_updates  = 0
        self.training_sessions: List[Dict] = []

        # Online learning: adaptive strategy weights [0.3, 2.0]
        self.strategy_weights: Dict[str, float] = {k: 1.0 for k in self._STRATEGY_KEYS}
        self.strategy_stats:   Dict[str, Dict]  = {
            k: {'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'last': ''} for k in self._STRATEGY_KEYS
        }

        # Memory structures
        self.performance_history: List[Dict] = []
        self.discovered_patterns: List[Dict] = []
        self.symbol_memory:       Dict[str, Dict] = {}
        self.regime_stats:        Dict[str, Dict] = defaultdict(lambda: {'wins': 0, 'losses': 0})
        self._returns:            List[float]      = []

        # PPO model (lazy)
        self._ppo_model   = None
        self._ppo_loaded  = False
        self._train_lock  = threading.Lock()

        # Subscribe to evaluation events from LENS
        self.subscribe(EventType.SIGNAL_EVALUATED, self._on_evaluated)

        logger.info("KARMA initialised — online learning active, PPO lazy-load enabled")

    # ── Event handler ─────────────────────────────────────────────────────────

    def _on_evaluated(self, event):
        """Triggered by LENS when a signal result is known."""
        p = event.payload
        self.learn_from_outcome(
            p.get('signal', {}),
            p.get('outcome', {}),
        )

    # ── Online Learning ───────────────────────────────────────────────────────

    def learn_from_outcome(self, signal: Dict, actual_outcome: Dict):
        """
        Update strategy weights from a closed-trade outcome.
        Called both directly and via _on_evaluated event handler.
        """
        strategy = (signal.get('strategy') or signal.get('source') or 'trend_following').lower()
        symbol   = signal.get('symbol', '')
        pnl      = float(actual_outcome.get('pnl', 0))
        regime   = signal.get('regime', 'UNKNOWN')
        won      = pnl > 0

        with self._lock:
            self.learning_episodes += 1
            self._returns.append(pnl / 10000)  # normalise

            # ── Strategy weight update (half-gradient) ────────────────────────
            strat_key = self._map_strategy(strategy)
            if strat_key in self.strategy_weights:
                lr    = 0.015
                delta = lr * (1.0 if won else -0.7)   # asymmetric — reward wins more
                self.strategy_weights[strat_key] = max(
                    0.30, min(2.0, self.strategy_weights[strat_key] + delta)
                )
                st = self.strategy_stats[strat_key]
                st['total_pnl'] += pnl
                st['last']       = 'WIN' if won else 'LOSS'
                if won:  st['wins']   += 1
                else:    st['losses'] += 1

            # ── Symbol memory ─────────────────────────────────────────────────
            if symbol:
                m = self.symbol_memory.setdefault(
                    symbol, {'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'trades': 0}
                )
                m['trades']    += 1
                m['total_pnl'] += pnl
                if won:  m['wins']   += 1
                else:    m['losses'] += 1

            # ── Regime accuracy ───────────────────────────────────────────────
            rs = self.regime_stats[regime]
            if won:  rs['wins']   += 1
            else:    rs['losses'] += 1

            # ── Episode history ───────────────────────────────────────────────
            ep = {
                'ep': self.learning_episodes, 'symbol': symbol,
                'strategy': strategy, 'regime': regime,
                'pnl': round(pnl, 2), 'outcome': 'WIN' if won else 'LOSS',
                'ts': datetime.now().strftime('%H:%M %d-%b'),
            }
            self.performance_history.append(ep)
            if len(self.performance_history) > 300:
                self.performance_history.pop(0)

            # ── Pattern discovery ─────────────────────────────────────────────
            self._discover_patterns(symbol, strategy, regime, pnl)

        logger.debug("KARMA learned: %s/%s → %s ₹%+.0f (ep %d)",
                     strategy, symbol, 'WIN' if won else 'LOSS',
                     pnl, self.learning_episodes)

    def _discover_patterns(self, symbol: str, strategy: str, regime: str, pnl: float):
        """Detect repeating profitable strategy+regime combos."""
        if len(self.performance_history) < 8:
            return
        recent = [e for e in self.performance_history[-30:]
                  if e.get('strategy') == strategy and e.get('regime') == regime]
        if len(recent) < 5:
            return
        wins    = sum(1 for e in recent if e['pnl'] > 0)
        wr      = wins / len(recent)
        avg_pnl = sum(e['pnl'] for e in recent) / len(recent)
        if wr >= 0.65 and avg_pnl > 0:
            pat_key = f"{strategy}_{regime}"
            existing = {p['key'] for p in self.discovered_patterns}
            if pat_key not in existing:
                pat = {
                    'key':       pat_key,
                    'pattern':   f"{strategy.title()} in {regime}",
                    'win_rate':  round(wr * 100, 1),
                    'sample':    len(recent),
                    'avg_pnl':   round(avg_pnl, 0),
                    'confidence':'HIGH' if len(recent) >= 15 else 'MEDIUM',
                    'discovered': datetime.now().strftime('%H:%M %d-%b'),
                }
                self.discovered_patterns.append(pat)
                if len(self.discovered_patterns) > 60:
                    self.discovered_patterns.pop(0)
                self.knowledge_updates += 1
                logger.info("KARMA pattern: %s  wr=%.0f%%", pat_key, wr * 100)
                self.share_knowledge(pat)

    def share_knowledge(self, knowledge: Dict):
        try:
            self.publish_event(EventType.STRATEGY_DISCOVERED, {
                'source': 'KARMA', 'knowledge': knowledge,
                'timestamp': datetime.now().isoformat(),
            })
        except Exception:
            pass

    # ── Offline PPO Training ──────────────────────────────────────────────────

    def run_offline_training(self, historical_data: Dict[str, List[Dict]],
                              timeframes: Optional[List[str]] = None) -> Dict:
        """
        Post-market deep training (call at 6 PM IST).
        historical_data: {symbol: [candle_dicts]}
        """
        if not historical_data:
            return {}

        tfs = timeframes or ['1min', '5min', '15min', '1D']
        t0  = datetime.now()
        syms_processed = 0

        # ── Step 1: Online learning from candle returns ───────────────────────
        for sym, candles in historical_data.items():
            prices = [float(c.get('close', 0)) for c in candles if c.get('close')]
            if len(prices) < 10:
                continue
            for i in range(5, len(prices) - 5):
                if prices[i] <= 0:
                    continue
                fwd_ret = (prices[i + 5] - prices[i]) / prices[i]
                strategy = 'trend_following' if fwd_ret > 0 else 'mean_reversion'
                self.learn_from_outcome(
                    {'symbol': sym, 'strategy': strategy, 'regime': 'HISTORICAL'},
                    {'pnl': fwd_ret * 50000},
                )
            syms_processed += 1

        # ── Step 2: PPO fine-tune (in background thread) ──────────────────────
        def _train_bg():
            with self._train_lock:
                model = _train_ppo(historical_data, self.MODEL_PATH)
                if model:
                    self._ppo_model  = model
                    self._ppo_loaded = True

        t = threading.Thread(target=_train_bg, daemon=True, name='KarmaTrainPPO')
        t.start()

        elapsed = (datetime.now() - t0).total_seconds()
        session = {
            'timestamp':   t0.strftime('%Y-%m-%d %H:%M'),
            'symbols':     syms_processed,
            'timeframes':  tfs,
            'episodes':    self.learning_episodes,
            'duration_s':  round(elapsed, 1),
            'best':        self.get_best_strategy(),
        }
        self.training_sessions.append(session)
        if len(self.training_sessions) > 30:
            self.training_sessions.pop(0)

        logger.info("KARMA offline: %d symbols in %.1fs | best=%s",
                    syms_processed, elapsed, self.get_best_strategy())
        return session

    def train(self, data: Optional[Dict] = None):
        """Live training entry point called from main loop."""
        if data:
            self.run_offline_training(data)

    # ── PPO Inference ─────────────────────────────────────────────────────────

    def ppo_signal(self, observation: List[float]) -> int:
        """Use PPO model for action suggestion. Returns 0=hold, 1=buy, 2=sell."""
        if not self._ppo_loaded:
            if not self._ppo_model:
                self._ppo_model = _load_ppo(self.MODEL_PATH)
                if self._ppo_model:
                    self._ppo_loaded = True
        if not self._ppo_model:
            return 0
        try:
            import numpy as np
            obs    = np.array(observation, dtype=np.float32).reshape(1, -1)
            action, _ = self._ppo_model.predict(obs, deterministic=True)
            return int(action[0])
        except Exception as exc:
            logger.debug("KARMA PPO predict failed: %s", exc)
            return 0

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get_optimized_weights(self) -> Dict[str, float]:
        with self._lock:
            return dict(self.strategy_weights)

    def get_best_strategy(self) -> str:
        with self._lock:
            return max(self.strategy_weights, key=self.strategy_weights.get)

    def get_worst_strategy(self) -> str:
        with self._lock:
            return min(self.strategy_weights, key=self.strategy_weights.get)

    @_safe
    def get_portfolio_sharpe(self) -> float:
        with self._lock:
            r = list(self._returns)
        return sharpe(r) if len(r) >= 5 else 0.0

    def get_knowledge_summary(self) -> Dict[str, Any]:
        """Full state for dashboard Agents → KARMA panel."""
        with self._lock:
            hist  = list(self.performance_history)
            pats  = list(self.discovered_patterns[-10:])
            sws   = dict(self.strategy_weights)
            sts   = dict(self.strategy_stats)
            rgs   = dict(self.regime_stats)
            syms  = dict(self.symbol_memory)
            sess  = self.training_sessions[-1] if self.training_sessions else None

        total = len(hist)
        wins  = sum(1 for e in hist if e['pnl'] > 0)
        wr    = round(wins / max(total, 1) * 100, 1)
        tpnl  = sum(e['pnl'] for e in hist)

        strat_details = {}
        for k, w in sws.items():
            st  = sts.get(k, {})
            tot = st.get('wins', 0) + st.get('losses', 0)
            strat_details[k] = {
                'weight':    round(w, 3),
                'win_rate':  round(st.get('wins', 0) / max(tot, 1) * 100, 1),
                'trades':    tot,
                'total_pnl': round(st.get('total_pnl', 0), 0),
                'status':    'STRONG' if w > 1.3 else 'WEAK' if w < 0.6 else 'NORMAL',
            }

        regime_wr = {
            r: round(v['wins'] / max(v['wins'] + v['losses'], 1) * 100, 1)
            for r, v in rgs.items()
        }

        top_syms = sorted(
            [{'symbol': k, **v} for k, v in syms.items()],
            key=lambda x: x['total_pnl'], reverse=True
        )[:5]

        uptime = (datetime.now() - self.session_start).total_seconds() / 3600
        ppo_sh = self.get_portfolio_sharpe()

        return {
            'learning_episodes':   self.learning_episodes,
            'knowledge_updates':   self.knowledge_updates,
            'total_trades':        total,
            'wins':                wins,
            'losses':              total - wins,
            'overall_win_rate':    wr,
            'total_pnl':           round(tpnl, 0),
            'portfolio_sharpe':    round(ppo_sh, 3),
            'best_strategy':       self.get_best_strategy(),
            'worst_strategy':      self.get_worst_strategy(),
            'strategy_weights':    strat_details,
            'regime_accuracy':     regime_wr,
            'top_symbols':         top_syms,
            'discovered_patterns': pats,
            'recent_episodes':     hist[-10:],
            'last_training':       sess,
            'ppo_active':          self._ppo_loaded,
            'uptime_hours':        round(uptime, 1),
        }

    def get_stats(self) -> Dict[str, Any]:
        return {
            'name':              self.name,
            'active':            self.is_active,
            'learning_episodes': self.learning_episodes,
            'knowledge_updates': self.knowledge_updates,
            'best_strategy':     self.get_best_strategy(),
            'ppo_active':        self._ppo_loaded,
            'kpi':               'Model improvement > 2% Sharpe',
            'last_activity':     self.last_activity,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _map_strategy(name: str) -> str:
        """Map free-form strategy name to canonical key."""
        name = name.lower()
        if any(k in name for k in ('trend', 'ema', 'macd', 'supertrend', 'adx')):
            return 'trend_following'
        if any(k in name for k in ('revers', 'rsi', 'bb', 'mean', 'stoch', 'cci')):
            return 'mean_reversion'
        if any(k in name for k in ('break', 'orb', '52', 'donch', 'resist')):
            return 'breakout'
        if any(k in name for k in ('vwap',)):
            return 'vwap'
        if any(k in name for k in ('volume', 'obv', 'mfi', 'ad')):
            return 'volume'
        if any(k in name for k in ('option', 'flow', 'dark')):
            return 'options_flow'
        if any(k in name for k in ('moment', 'roc', 'pmo')):
            return 'momentum'
        return 'trend_following'
