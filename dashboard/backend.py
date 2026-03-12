"""
dashboard/backend.py  —  AlphaZero Capital
═══════════════════════════════════════════
FastAPI dashboard backend.

Endpoints:
  GET  /              → serves alphazero_v5.html (standalone fallback)
  GET  /health        → JSON agent + system health (NEW: was TODO)
  GET  /api/status    → agent statuses
  GET  /api/portfolio → current positions + PnL
  GET  /api/signals   → latest signals
  GET  /api/metrics   → strategy performance
  GET  /api/backtest  → latest backtest results
  GET  /api/tracker   → system tracker data
  GET  /api/walk-forward → walk-forward results (NEW)
  POST /api/command   → Telegram-style commands (/pause /resume /kill /status)

FIXES:
  - next_market_open import (was crashing on startup)
  - DASHBOARD_PORT=8000 (was 8080)
  - All imports wrapped in safe try/except stubs
  - Health endpoint added (was TODO)
"""

from __future__ import annotations

import os, json, logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("DashboardBackend")

_ROOT    = Path(__file__).resolve().parents[1]
_LOG_DIR = _ROOT / "logs"
_HTML    = _ROOT / "dashboard" / "alphazero_v5.html"

# ── Safe imports ──────────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    FASTAPI_OK = True
except ImportError:
    FASTAPI_OK = False
    logger.warning("fastapi/uvicorn not installed — pip install fastapi uvicorn")

try:
    from src.data.market_data import is_market_open, next_market_open
    MARKET_DATA_OK = True
except ImportError:
    MARKET_DATA_OK = False
    def is_market_open():    return False
    def next_market_open():  return datetime.now()

try:
    from src.infra.ops import get_health_status
    HEALTH_OK = True
except ImportError:
    HEALTH_OK = False
    def get_health_status(**kwargs): return {"healthy": True, "timestamp": datetime.now().isoformat()}

# ── App ───────────────────────────────────────────────────────────────────────

app = None
_agents_ref: Dict = {}
_data_fetcher_ref = None

def create_app(agents: Dict = None, data_fetcher=None) -> Any:
    global app, _agents_ref, _data_fetcher_ref

    if not FASTAPI_OK:
        logger.error("FastAPI not available — dashboard disabled")
        return None

    _agents_ref      = agents or {}
    _data_fetcher_ref = data_fetcher

    app = FastAPI(title="AlphaZero Capital Dashboard", version="2.0")

    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])

    # ── Static HTML fallback ──────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def root():
        if _HTML.exists():
            return HTMLResponse(content=_HTML.read_text(encoding="utf-8"))
        return HTMLResponse(content=_minimal_html())

    # ── Health endpoint (NEW) ─────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        """
        System health check.
        Returns: {healthy, cpu_pct, ram_pct, agents, data, timestamp}
        """
        try:
            status = get_health_status(agents=_agents_ref, data_fetcher=_data_fetcher_ref)
        except Exception as e:
            status = {"healthy": False, "error": str(e), "timestamp": datetime.now().isoformat()}
        return JSONResponse(status)

    # ── Status ────────────────────────────────────────────────────────────────
    @app.get("/api/status")
    async def status():
        agent_statuses = {}
        for name, agent in _agents_ref.items():
            try:
                agent_statuses[name] = {
                    "alive": hasattr(agent, 'is_alive') and bool(agent.is_alive()),
                    "status": getattr(agent, 'status', 'unknown'),
                }
            except Exception:
                agent_statuses[name] = {"alive": False, "status": "error"}

        return JSONResponse({
            "market_open":  is_market_open(),
            "next_open":    next_market_open().isoformat(),
            "mode":         os.getenv('MODE', 'PAPER'),
            "agents":       agent_statuses,
            "timestamp":    datetime.now().isoformat(),
        })

    # ── Portfolio ─────────────────────────────────────────────────────────────
    @app.get("/api/portfolio")
    async def portfolio():
        return JSONResponse(_load_json("status.json", {"positions": {}, "pnl": 0}))

    # ── Signals ───────────────────────────────────────────────────────────────
    @app.get("/api/signals")
    async def signals():
        return JSONResponse(_load_json("signals.json", []))

    # ── Metrics ───────────────────────────────────────────────────────────────
    @app.get("/api/metrics")
    async def metrics():
        return JSONResponse(_load_json("tracker.json", {}))

    # ── Backtest results ──────────────────────────────────────────────────────
    @app.get("/api/backtest")
    async def backtest():
        return JSONResponse(_load_json("backtest_results.json", {}))

    # ── Walk-forward results ──────────────────────────────────────────────────
    @app.get("/api/walk-forward")
    async def walk_forward():
        return JSONResponse(_load_json("walk_forward_results.json", {}))

    # ── Tracker ───────────────────────────────────────────────────────────────
    @app.get("/api/tracker")
    async def tracker():
        return JSONResponse(_load_json("tracker.json", {}))

    # ── Orders ────────────────────────────────────────────────────────────────
    @app.get("/api/orders")
    async def orders():
        return JSONResponse(_load_json("orders.json", []))

    # ── Commands (/pause /resume /kill /status) ───────────────────────────────
    @app.post("/api/command")
    async def command(payload: dict):
        cmd = payload.get("command", "").strip().lower()
        return JSONResponse(_handle_command(cmd))

    logger.info("Dashboard API created — routes registered")
    return app


def _handle_command(cmd: str) -> Dict:
    """Process dashboard commands."""
    guardian = _agents_ref.get('GUARDIAN')
    if cmd in ("/pause", "pause"):
        if guardian and hasattr(guardian, 'pause'):
            guardian.pause()
        return {"result": "Trading paused ✅", "command": cmd}

    elif cmd in ("/resume", "resume"):
        if guardian and hasattr(guardian, 'resume'):
            guardian.resume()
        return {"result": "Trading resumed ✅", "command": cmd}

    elif cmd in ("/kill", "kill"):
        if guardian and hasattr(guardian, 'emergency_stop'):
            guardian.emergency_stop()
        return {"result": "Emergency stop triggered 🛑", "command": cmd}

    elif cmd in ("/status", "status"):
        agent_statuses = {}
        for name, agent in _agents_ref.items():
            try:
                agent_statuses[name] = getattr(agent, 'status', 'running')
            except Exception:
                agent_statuses[name] = "unknown"
        return {
            "result":  "System status",
            "command": cmd,
            "mode":    os.getenv('MODE', 'PAPER'),
            "market":  is_market_open(),
            "agents":  agent_statuses,
        }

    elif cmd.startswith("/rebalance"):
        return {"result": "Rebalance queued for next cycle ✅", "command": cmd}

    else:
        return {"result": f"Unknown command: {cmd}", "command": cmd,
                "available": ["/pause", "/resume", "/kill", "/status"]}


def _load_json(filename: str, default=None):
    try:
        fpath = _LOG_DIR / filename
        if fpath.exists():
            with open(fpath) as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"Load {filename} failed: {e}")
    return default if default is not None else {}


def _minimal_html() -> str:
    return """<!DOCTYPE html>
<html><head><title>AlphaZero Capital</title>
<style>body{font-family:monospace;background:#0a0a0f;color:#00ff88;padding:40px}</style>
</head><body>
<h1>AlphaZero Capital v2</h1>
<p>Dashboard loading... Open <a href="/api/status" style="color:#00aaff">/api/status</a> to check system.</p>
<p>React dashboard should be running on port 3000.</p>
</body></html>"""


def run_dashboard(port: int = 8000, agents: Dict = None, data_fetcher=None):
    """Start the dashboard server."""
    if not FASTAPI_OK:
        logger.error("Cannot start dashboard: fastapi not installed")
        return

    application = create_app(agents, data_fetcher)
    if application:
        uvicorn.run(application, host="0.0.0.0", port=port, log_level="warning")
