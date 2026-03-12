"""
src/tracker.py  —  AlphaZero Capital
═══════════════════════════════════════
Phase 8: Project Tracker

Monitors and logs:
  • System health (CPU, RAM, uptime)
  • Module status (all agents, data pipeline, training pipeline)
  • Agent status (signals generated, win rates)
  • Data pipeline health
  • Training pipeline (KARMA learning progress)
  • Strategy performance (win rate, Sharpe, drawdown, profit factor)

Runs in a background thread, writes to logs/tracker.json and logs/tracker.log.

Usage:
    from src.tracker import SystemTracker
    tracker = SystemTracker(agents_ref=self.agents)
    tracker.start()
    # Later:
    snapshot = tracker.snapshot()
    tracker.stop()
"""

from __future__ import annotations

import os
import sys
import json
import time
import logging
import threading
import platform
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Tracker")

# Optional psutil for CPU/RAM
try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False

# ── Constants ────────────────────────────────────────────────────────────────
_ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR    = os.path.join(_ROOT, 'logs')
_TRACKER_FILE  = os.path.join(_LOG_DIR, 'tracker.json')
_PERF_FILE     = os.path.join(_LOG_DIR, 'strategy_performance.json')

os.makedirs(_LOG_DIR, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

class SystemHealth:
    """CPU, RAM, disk, uptime."""

    def __init__(self):
        self._start = time.time()

    def collect(self) -> Dict[str, Any]:
        uptime_s = int(time.time() - self._start)
        info: Dict[str, Any] = {
            'uptime_seconds': uptime_s,
            'uptime_human':   _human_time(uptime_s),
            'platform':       platform.system(),
            'python':         sys.version.split()[0],
            'timestamp':      _now_str(),
        }
        if _PSUTIL_OK:
            try:
                info['cpu_pct']   = psutil.cpu_percent(interval=0.2)
                mem = psutil.virtual_memory()
                info['ram_used_mb']  = round(mem.used  / 1_048_576, 1)
                info['ram_total_mb'] = round(mem.total / 1_048_576, 1)
                info['ram_pct']      = mem.percent
                disk = psutil.disk_usage(_ROOT)
                info['disk_free_gb'] = round(disk.free / 1_073_741_824, 2)
            except Exception:
                pass
        return info


def _human_time(seconds: int) -> str:
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE STATUS
# ═══════════════════════════════════════════════════════════════════════════════

_REQUIRED_MODULES = [
    ('config.settings',               'Settings'),
    ('src.event_bus.event_bus',       'EventBus'),
    ('src.data.fetch',                'DataFetcher'),
    ('src.data.market_data',          'MarketDataEngine'),
    ('src.data.indicators',           'IndicatorEngine'),
    ('src.agents.chief_agent',        'ChiefAgent'),
    ('src.agents.titan_agent',        'TitanAgent'),
    ('src.agents.guardian_agent',     'GuardianAgent'),
    ('src.agents.mercury_agent',      'MercuryAgent'),
    ('src.agents.lens_agent',         'LensAgent'),
    ('src.agents.karma_agent',        'KarmaAgent'),
    ('src.agents.oracle_agent',       'OracleAgent'),
    ('src.risk.risk_manager',         'RiskManager'),
    ('src.risk.capital_allocator',    'CapitalAllocator'),
    ('src.monitoring.state',          'LiveState'),
    ('src.reporting.pdf_generator',   'PDFGenerator'),
    ('src.tracker',                   'Tracker'),
]

_OPTIONAL_MODULES = [
    ('src.agents.llm_earnings_analyzer',  'EarningsAnalyzer'),
    ('src.agents.llm_strategy_generator', 'StrategyGenerator'),
    ('src.backtest.engine',               'BacktestEngine'),
    ('fastapi',                           'FastAPI'),
    ('yfinance',                          'yfinance'),
    ('pandas_ta',                         'pandas-ta'),
    ('reportlab',                         'reportlab'),
    ('psutil',                            'psutil'),
]


def check_modules() -> Dict[str, Any]:
    """Dynamically import every module and report pass/fail."""
    results: Dict[str, Any] = {'required': {}, 'optional': {}}

    for mod_path, label in _REQUIRED_MODULES:
        try:
            __import__(mod_path)
            results['required'][label] = '✅ OK'
        except Exception as exc:
            results['required'][label] = f'❌ {exc}'

    for mod_path, label in _OPTIONAL_MODULES:
        try:
            __import__(mod_path)
            results['optional'][label] = '✅ OK'
        except Exception:
            results['optional'][label] = '⚠ not installed'

    ok    = sum(1 for v in results['required'].values() if v.startswith('✅'))
    total = len(results['required'])
    results['summary'] = f"{ok}/{total} required modules OK"
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT STATUS
# ═══════════════════════════════════════════════════════════════════════════════

def collect_agent_status(agents: Dict[str, Any]) -> Dict[str, Any]:
    """Pull get_stats() from every agent."""
    status: Dict[str, Any] = {}
    for name, agent in agents.items():
        try:
            if hasattr(agent, 'get_stats'):
                stats = agent.get_stats()
            else:
                stats = {'active': getattr(agent, 'is_active', True)}
            stats['name'] = name
            status[name]  = stats
        except Exception as exc:
            status[name] = {'name': name, 'active': False, 'error': str(exc)}
    return status


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY PERFORMANCE
# ═══════════════════════════════════════════════════════════════════════════════

class StrategyPerformanceTracker:
    """
    Tracks per-strategy: win_rate, sharpe, max_drawdown, profit_factor, trade_count.
    Data persisted to logs/strategy_performance.json.
    """

    def __init__(self):
        self._data: Dict[str, Any] = self._load()
        self._lock = threading.Lock()

    def _load(self) -> Dict[str, Any]:
        try:
            with open(_PERF_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self):
        try:
            with open(_PERF_FILE + '.tmp', 'w') as f:
                json.dump(self._data, f, indent=2, default=str)
            os.replace(_PERF_FILE + '.tmp', _PERF_FILE)
        except Exception as e:
            logger.warning("Strategy perf save error: %s", e)

    def record_trade(
        self,
        strategy_id: str,
        symbol:      str,
        direction:   str,           # 'BUY' | 'SELL'
        entry_price: float,
        exit_price:  float,
        qty:         int = 1,
    ):
        """Record a completed trade for a strategy."""
        with self._lock:
            s = self._data.setdefault(strategy_id, {
                'strategy_id':   strategy_id,
                'trade_count':   0,
                'wins':          0,
                'losses':        0,
                'win_rate':      0.0,
                'total_pnl':     0.0,
                'gross_profit':  0.0,
                'gross_loss':    0.0,
                'profit_factor': 0.0,
                'peak_capital':  0.0,
                'max_drawdown':  0.0,
                'returns':       [],
                'sharpe':        0.0,
                'last_updated':  _now_str(),
            })

            pnl   = (exit_price - entry_price) * qty if direction == 'BUY' else (entry_price - exit_price) * qty
            won   = pnl > 0

            s['trade_count'] += 1
            s['total_pnl']   += pnl
            s['returns'].append(round(pnl, 4))
            if len(s['returns']) > 500:
                s['returns'] = s['returns'][-500:]

            if won:
                s['wins']         += 1
                s['gross_profit'] += pnl
            else:
                s['losses']       += 1
                s['gross_loss']   += abs(pnl)

            total = s['wins'] + s['losses']
            s['win_rate']      = round(s['wins'] / total, 4) if total else 0.0
            s['profit_factor'] = round(s['gross_profit'] / max(s['gross_loss'], 0.01), 3)
            s['sharpe']        = self._sharpe(s['returns'])
            s['max_drawdown']  = self._max_drawdown(s['returns'])
            s['last_updated']  = _now_str()

            self._save()

    @staticmethod
    def _sharpe(returns: List[float], risk_free: float = 0.0) -> float:
        if len(returns) < 5:
            return 0.0
        try:
            import numpy as np
            arr   = np.array(returns, dtype=float)
            std   = arr.std()
            mean  = arr.mean() - risk_free
            return round(float(mean / std * (252 ** 0.5)) if std > 0 else 0.0, 3)
        except Exception:
            return 0.0

    @staticmethod
    def _max_drawdown(returns: List[float]) -> float:
        if len(returns) < 2:
            return 0.0
        try:
            equity = 0.0
            peak   = 0.0
            max_dd = 0.0
            for r in returns:
                equity += r
                if equity > peak:
                    peak = equity
                dd = peak - equity
                if dd > max_dd:
                    max_dd = dd
            return round(max_dd, 4)
        except Exception:
            return 0.0

    def get_leaderboard(self, top_n: int = 10) -> List[Dict]:
        """Return top-N strategies sorted by profit_factor."""
        with self._lock:
            items = list(self._data.values())
        items.sort(key=lambda x: x.get('profit_factor', 0), reverse=True)
        return items[:top_n]

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

class SystemTracker:
    """
    Background tracker that polls system health and agent status every 60s,
    writes to logs/tracker.json, and logs a summary line.

    Usage:
        tracker = SystemTracker(agents_ref=system.agents)
        tracker.start()
        snap = tracker.snapshot()
        tracker.stop()
    """

    def __init__(
        self,
        agents_ref: Optional[Dict[str, Any]] = None,
        interval:   int = 60,
    ):
        self._agents   = agents_ref or {}
        self._interval = interval
        self._running  = False
        self._health   = SystemHealth()
        self.strategy_perf = StrategyPerformanceTracker()
        self._last_snapshot: Dict[str, Any] = {}

        # Set up dedicated tracker log file
        _tracker_log = os.path.join(_LOG_DIR, 'tracker.log')
        fh = logging.FileHandler(_tracker_log, encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        logger.addHandler(fh)

        logger.info("SystemTracker initialised (interval=%ds)", interval)

    def start(self):
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True, name="SystemTracker")
        t.start()
        logger.info("SystemTracker started")

    def stop(self):
        self._running = False
        logger.info("SystemTracker stopped")

    def snapshot(self) -> Dict[str, Any]:
        """Return the most recent tracker snapshot."""
        return dict(self._last_snapshot)

    # ── Background loop ───────────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            try:
                snap = self._collect()
                self._last_snapshot = snap
                self._write(snap)
                self._log_summary(snap)
            except Exception as exc:
                logger.error("Tracker collect error: %s", exc)
            time.sleep(self._interval)

    def _collect(self) -> Dict[str, Any]:
        return {
            'timestamp':     _now_str(),
            'system_health': self._health.collect(),
            'modules':       check_modules(),
            'agents':        collect_agent_status(self._agents),
            'strategy_perf': self.strategy_perf.get_all(),
            'leaderboard':   self.strategy_perf.get_leaderboard(5),
        }

    def _write(self, snap: Dict[str, Any]):
        try:
            tmp = _TRACKER_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(snap, f, indent=2, default=str)
            os.replace(tmp, _TRACKER_FILE)
        except Exception as e:
            logger.warning("Tracker write error: %s", e)

    def _log_summary(self, snap: Dict[str, Any]):
        health = snap.get('system_health', {})
        agents = snap.get('agents', {})
        active = sum(1 for a in agents.values() if a.get('active', False))
        total  = len(agents)
        mods   = snap.get('modules', {}).get('summary', '?')
        cpu    = health.get('cpu_pct', '?')
        ram    = health.get('ram_pct', '?')
        uptime = health.get('uptime_human', '?')
        logger.info(
            "HEALTH | uptime=%s cpu=%s%% ram=%s%% | agents=%d/%d active | %s",
            uptime, cpu, ram, active, total, mods,
        )


# ── Module-level convenience functions ────────────────────────────────────────

_global_tracker: Optional[SystemTracker] = None


def get_tracker() -> Optional[SystemTracker]:
    return _global_tracker


def start_tracker(agents_ref: Optional[Dict] = None, interval: int = 60) -> SystemTracker:
    """Start the global tracker. Call once from main.py."""
    global _global_tracker
    _global_tracker = SystemTracker(agents_ref=agents_ref, interval=interval)
    _global_tracker.start()
    return _global_tracker


# ── CLI quick-check ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🔍  AlphaZero Capital — System Tracker Quick-Check\n" + "=" * 60)
    mods = check_modules()
    print("\n📦  Required Modules:")
    for name, status in mods['required'].items():
        print(f"   {name:30} {status}")
    print("\n📦  Optional Modules:")
    for name, status in mods['optional'].items():
        print(f"   {name:30} {status}")
    print(f"\n{mods['summary']}")

    health = SystemHealth().collect()
    print("\n💻  System Health:")
    for k, v in health.items():
        print(f"   {k:25} {v}")
    print("=" * 60)
