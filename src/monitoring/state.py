"""
src/monitoring/state.py
────────────────────────
Thread-safe in-memory state store shared between main.py and server.py.
main.py  → calls state.update(dict)   to push new data each iteration
server.py → calls state.read()        to serve /api/status
"""

import threading
import copy

_lock  = threading.Lock()
_store = {}


def update(data: dict) -> None:
    """Deep-merge `data` into the live state."""
    with _lock:
        _deep_merge(_store, data)


def read() -> dict:
    """Return a deep copy of the current state (safe to JSON-serialize)."""
    with _lock:
        return copy.deepcopy(_store)


def reset() -> None:
    """Clear all state (useful for tests)."""
    with _lock:
        _store.clear()


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
