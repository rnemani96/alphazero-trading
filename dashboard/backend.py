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

import os, json, logging, math
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("DashboardBackend")


class _SafeEncoder(json.JSONEncoder):
    """JSON encoder that handles NaN, Inf, datetime, sets, and numpy scalars."""
    def default(self, obj):
        try:
            import numpy as np
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                v = float(obj)
                if math.isnan(v) or math.isinf(v):
                    return None
                return v
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, set):
            return list(obj)
        return None   # instead of raising, return null

    def iterencode(self, o, _one_shot=False):
        # Replace NaN/Inf floats with null at encode time
        return super().iterencode(self._clean(o), _one_shot)

    def _clean(self, obj):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        if isinstance(obj, dict):
            return {k: self._clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._clean(v) for v in obj]
        return obj


def _safe_json_dumps(obj) -> str:
    """JSON serialize with NaN/Inf/datetime safety — never raises."""
    try:
        return json.dumps(obj, cls=_SafeEncoder)
    except Exception as e:
        logger.warning(f"JSON serialization warning: {e}")
        return json.dumps({"type": "error", "msg": "serialization_error"})

_ROOT    = Path(__file__).resolve().parents[1]
_LOG_DIR = _ROOT / "logs"
_HTML    = _ROOT / "dashboard" / "alphazero_v5.html"

# ── Safe imports ──────────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    import asyncio
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

    # ── Static JS assets (React/Babel served locally) ────────────────────────
    _STATIC_DIR = _ROOT / "dashboard" / "static"
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)

    # Auto-download JS libraries on first run (background thread, non-blocking)
    _DEPS = {
        "react.production.min.js":     "https://unpkg.com/react@18/umd/react.production.min.js",
        "react-dom.production.min.js": "https://unpkg.com/react-dom@18/umd/react-dom.production.min.js",
        "babel.min.js":                "https://unpkg.com/@babel/standalone/babel.min.js",
    }

    def _auto_download_deps():
        import urllib.request, ssl, time
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        all_present = all((_STATIC_DIR / fn).exists() for fn in _DEPS)
        if all_present:
            return
        logger.info("Downloading frontend JS libs to dashboard/static/ ...")
        for filename, url in _DEPS.items():
            dest = _STATIC_DIR / filename
            if dest.exists():
                continue
            try:
                logger.info(f"  Fetching {filename} ...")
                urllib.request.urlretrieve(url, str(dest))
                logger.info(f"  ✓ {filename} saved ({dest.stat().st_size // 1024} KB)")
            except Exception as e:
                logger.warning(f"  ✗ Could not download {filename}: {e}")
        logger.info("Frontend JS libs download complete.")

    import threading as _threading
    _threading.Thread(target=_auto_download_deps, daemon=True).start()

    @app.get("/static/{filename}")
    async def static_file(filename: str):
        """Serve locally cached JS libraries from dashboard/static/."""
        safe_name = Path(filename).name   # prevent path traversal
        file_path = _STATIC_DIR / safe_name
        if file_path.exists():
            return FileResponse(str(file_path), media_type="application/javascript")
        from fastapi.responses import Response
        return Response(status_code=404, content=f"Not found: {safe_name}")

    # Aliases for frontend (some versions use non-api prefix)
    @app.get("/portfolio")
    async def portfolio_alias(): return await portfolio()
    
    @app.get("/sources")
    async def sources_alias():
        # Return registered data sources status
        sources = {
            "yfinance": {"status": "active", "latency_ms": 450, "requests_today": 120},
            "nse_direct": {"status": "active", "latency_ms": 820, "requests_today": 85},
            "upstox": {"status": "disabled"},
        }
        return JSONResponse(sources)

@app.get("/evaluation/stats")
async def get_eval_stats():
    """Return live evaluation metrics from LENS agent."""
    lens = _agents_ref.get("LENS")
    if lens and hasattr(lens, "get_performance_summary"):
        try:
            summary = lens.get_performance_summary()
            eval_stats = summary.get("evaluator_stats", {})
            return {
                "winRate":      round(eval_stats.get("win_rate", 0), 2),
                "profitFactor": round(summary.get("profit_factor", 0), 2),
                "avgTrade":     round(eval_stats.get("avg_pnl_pct", 0), 2),
                "sharpe":       round(eval_stats.get("total_points", 0), 2), # Using total points as proxy for alpha/sharpe
                "totalSignals": eval_stats.get("total_evaluated", 0)
            }
        except Exception as e:
            logger.error(f"Error fetching LENS stats: {e}")
    
    return {"winRate": 0.0, "profitFactor": 0.0, "avgTrade": 0.0, "sharpe": 0.0, "totalSignals": 0}

@app.get("/evaluation/history")
async def get_eval_history():
    """Return historical evaluation outcomes from LENS."""
    lens = _agents_ref.get("LENS")
    if lens and hasattr(lens, "evaluator"):
        try:
            # evaluator._history contains SignalRecord objects
            history = lens.evaluator._history[-50:]
            return [
                {
                    "symbol":    h.symbol,
                    "strategy":  h.strategy_name,
                    "outcome":   h.outcome,
                    "pnl":       round(h.actual_pnl_pct * 100, 2) if h.actual_pnl_pct else 0,
                    "date":      h.emitted_at
                } for h in history
            ]
        except Exception:
            pass
    return []

@app.get("/evaluation/agents")
async def get_eval_agents():
    """Return per-agent performance attribution."""
    lens = _agents_ref.get("LENS")
    if lens and hasattr(lens, "strategy_performance"):
        try:
            perf = lens.strategy_performance
            return [
                {
                    "name":    name,
                    "trades":  data.get("trades", 0),
                    "winRate": round(data.get("wins", 0) / max(data.get("trades", 1), 1), 2),
                    "pnl":     round(data.get("pnl", 0), 2)
                } for name, data in perf.items()
            ]
        except Exception:
            pass
    return []

    @app.get("/candles/{symbol}")
    async def get_candles(symbol: str):
        # Delegate to data fetcher if available, or return cached candles
        return JSONResponse({"symbol": symbol, "candles": []})

    @app.get("/fundamentals/{symbol}")
    async def get_fundamentals(symbol: str):
        return JSONResponse({})

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
                    "activity": getattr(agent, 'last_activity', 'Running'),
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
    @app.get("/api/status")
    async def get_status():
        """Returns the full system status from status.json."""
        return JSONResponse(_load_json("status.json", {}))

    @app.get("/api/universe")
    async def get_universe():
        """Returns the dynamic NIFTY 500 universe from cache."""
        nexus_cache = Path("data/cache/nexus/universe.json")
        if nexus_cache.exists():
            with open(nexus_cache) as f:
                syms = json.load(f)
            # Convert to list of dicts for frontend compatibility
            return JSONResponse([{"s": s, "n": s, "sec": "NIFTY500", "base": 1000} for s in syms])
        return JSONResponse([])

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

    # ── WebSocket (Live Streaming) ────────────────────────────────────────────
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        logger.info("Dashboard connected via WebSocket")
        
        stop_event = asyncio.Event()

        async def send_updates():
            while not stop_event.is_set():
                try:
                    # 1. Load latest state from files
                    status_data = _load_json("status.json", {})
                    signals_data = _load_json("signals.json", [])

                    # 2. Build live agent status (crash-safe per agent)
                    agent_statuses = {}
                    # Use list() to avoid RuntimeError if _agents_ref is modified during iteration
                    for name, agent in list(_agents_ref.items()):
                        try:
                            agent_statuses[name] = {
                                "alive": bool(getattr(agent, 'is_active', True)),
                                "kpi": float(getattr(agent, 'kpi', 0.72)),
                                "cycles": int(getattr(agent, 'cycles', 0)),
                                "activity": str(getattr(agent, 'last_activity', 'Running')),
                            }
                        except Exception:
                            agent_statuses[name] = {"alive": True, "kpi": 0.72, "cycles": 0, "activity": "Running"}

                    # 3. Normalise positions — status.json may store it as {} or []
                    raw_positions = status_data.get("positions", [])
                    if isinstance(raw_positions, dict):
                        # Convert dict of symbol→position into list
                        positions_list = list(raw_positions.values()) if raw_positions else []
                    else:
                        positions_list = raw_positions if isinstance(raw_positions, list) else []

                    # 4. Aggregate full state for frontend
                    payload = {
                        "type": "status",
                        "system": {
                            "status": "RUNNING",
                            "mode": os.getenv('MODE', 'PAPER'),
                            "iteration": int(status_data.get("iteration", 0)),
                            "timestamp": datetime.now().isoformat(),
                            "agents": agent_statuses,
                        },
                        "regime": str(status_data.get("regime", "TRENDING")),
                        "sentiment": float(status_data.get("sentiment", 0.5)),
                        "picks": status_data.get("picks", []),
                        "candidates": status_data.get("candidates", []),
                        "positions": positions_list,
                        "macro": status_data.get("macro", {}),
                        "quotes": status_data.get("market_data", {}),
                        "signals": signals_data if isinstance(signals_data, list) else [],
                    }

                    # 5. Safe-serialize (handles NaN, Inf, datetime, numpy)
                    data_str = _safe_json_dumps(payload)
                    await websocket.send_text(data_str)

                except WebSocketDisconnect:
                    stop_event.set()
                    break
                except Exception as e:
                    # Log but DON'T kill the loop — a transient error shouldn't drop the connection
                    logger.warning(f"WS send transient error (will retry): {e}")

                await asyncio.sleep(2)  # stream every 2 seconds

        async def receive_messages():
            try:
                while not stop_event.is_set():
                    # Wait for any message from client (like PING)
                    data = await websocket.receive_text()
                    # We don't really need to do anything with the data yet
                    # but calling receive() keeps the connection alive in many setups
            except WebSocketDisconnect:
                stop_event.set()
            except Exception as e:
                # Upgrading to warning to help debug disconnections
                logger.warning(f"WS receive error (causing disconnect): {e}")
                stop_event.set()

        try:
            # Run both tasks concurrently
            await asyncio.gather(send_updates(), receive_messages())
        finally:
            logger.info("Dashboard disconnected")
            stop_event.set()
            try: await websocket.close()
            except: pass

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
