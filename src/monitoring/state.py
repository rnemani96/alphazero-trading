"""
Live System State
src/monitoring/state.py

Thread-safe shared state written by main.py every iteration.
Dashboard server reads this to serve live data via /api/status.

Design: simple JSON file in logs/ — works across processes with no extra deps.
"""

import json
import os
import threading
from datetime import datetime
from typing import Dict, Any

_LOCK = threading.Lock()
_STATE_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', 'logs', 'status.json'
)


# ── Default / skeleton state ─────────────────────────────────────────────────

_DEFAULT: Dict[str, Any] = {
    'system': {
        'status':    'STARTING',
        'mode':      'PAPER',
        'version':   'v17',
        'uptime_s':  0,
        'iteration': 0,
        'last_update': ''
    },
    'portfolio': {
        'initial_capital':   1_000_000,
        'current_value':     1_000_000,
        'daily_pnl':         0.0,
        'daily_pnl_pct':     0.0,
        'total_trades':      0,
        'open_positions':    0,
        'win_rate':          0.0,
        'profit_locked':     0.0,
    },
    'regime':    'UNKNOWN',
    'sentiment': 'NEUTRAL',
    'positions': [],
    'recent_signals': [],
    'agents': {},
    'risk': {
        'kill_switch':        False,
        'daily_loss_pct':     0.0,
        'trades_today':       0,
        'consecutive_losses': 0,
    }
}


def update(patch: Dict[str, Any]):
    """
    Deep-merge patch dict into the live state and write to logs/status.json.
    Call this from main.py after every iteration.
    """
    with _LOCK:
        try:
            current = _load_raw()
            _deep_merge(current, patch)
            current['system']['last_update'] = datetime.now().isoformat()
            _write_raw(current)
        except Exception:
            pass   # never crash main loop because of state write


def read() -> Dict[str, Any]:
    """Read and return the current live state (safe, returns default on error)."""
    with _LOCK:
        return _load_raw()


# ── internals ────────────────────────────────────────────────────────────────

def _load_raw() -> Dict[str, Any]:
    try:
        with open(_STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        import copy
        return copy.deepcopy(_DEFAULT)


def _write_raw(state: Dict[str, Any]):
    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
    tmp = _STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, _STATE_FILE)   # atomic on POSIX; near-atomic on Windows


def _deep_merge(base: dict, overlay: dict):
    for k, v in overlay.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
