"""
dashboard/backend.py  —  AlphaZero Capital
═══════════════════════════════════════════
FastAPI dashboard backend.
"""

from __future__ import annotations
import os, json, logging, math, threading, asyncio, webbrowser, time, ssl, urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("DashboardBackend")

# ── Safe imports ──────────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    FASTAPI_OK = True
except ImportError:
    FASTAPI_OK = False
    logger.warning("fastapi/uvicorn not installed — pip install fastapi uvicorn")


try:
    from src.data.market_data import is_market_open, next_market_open
    from src.data.universe import get_nifty500_symbols
except ImportError:
    def is_market_open():    return False
    def next_market_open():  return datetime.now()
    def get_nifty500_symbols(): return []

try:
    from src.infra.ops import get_health_status
except ImportError:
    def get_health_status(**kwargs): return {"healthy": True, "timestamp": datetime.now().isoformat()}

# ── Constants ─────────────────────────────────────────────────────────────────
_ROOT    = Path(__file__).resolve().parents[1]
_LOG_DIR = _ROOT / "logs"
_HTML    = _ROOT / "dashboard" / "alphazero_v5.html"
_STATIC_DIR = _ROOT / "dashboard" / "static"

# ── JSON Safety ───────────────────────────────────────────────────────────────
class _SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            import numpy as np
            if isinstance(obj, (np.integer,)): return int(obj)
            if isinstance(obj, (np.floating,)):
                v = float(obj)
                return None if math.isnan(v) or math.isinf(v) else v
            if isinstance(obj, np.ndarray): return obj.tolist()
        except ImportError: pass
        if isinstance(obj, datetime): return obj.isoformat()
        if isinstance(obj, set): return list(obj)
        return None

def _safe_json_dumps(obj) -> str:
    try: return json.dumps(obj, cls=_SafeEncoder)
    except Exception: return json.dumps({"type": "error", "msg": "serialization_error"})

def _load_json(filename: str, default=None):
    try:
        fpath = _LOG_DIR / filename
        if fpath.exists():
            with open(fpath) as f: return json.load(f)
    except Exception: pass
    return default if default is not None else {}

# ── App Creation ──────────────────────────────────────────────────────────────
def create_app(agents: Dict = None, data_fetcher=None, event_bus=None) -> Any:
    if not FASTAPI_OK:
        logger.error("FastAPI not available — dashboard disabled")
        return None

    _agents_ref = agents or {}
    _data_fetcher_ref = data_fetcher
    _event_bus_ref = event_bus
    app = FastAPI(title="AlphaZero Capital Dashboard", version="4.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8001", "http://127.0.0.1:8001"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    # ── Mount Static Files ────────────────────────────────────────────────────
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    else:
        logger.warning(f"Static directory not found: {_STATIC_DIR}")


    # ── Routes ────────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def root():
        if _HTML.exists(): return HTMLResponse(content=_HTML.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>AlphaZero Capital</h1><p>Dashboard HTML not found.</p>")

    @app.get("/api/status")
    async def status():
        agent_statuses = {}
        for name, agent in _agents_ref.items():
            try:
                agent_statuses[name] = {
                    "alive": bool(getattr(agent, 'is_active', True)),
                    "status": getattr(agent, 'status', 'running'),
                    "activity": getattr(agent, 'last_activity', 'Running'),
                }
            except Exception: agent_statuses[name] = {"alive": False, "status": "error"}
        return JSONResponse({
            "market_open": is_market_open(),
            "next_open": next_market_open().isoformat(),
            "mode": os.getenv('MODE', 'PAPER'),
            "agents": agent_statuses,
            "timestamp": datetime.now().isoformat(),
        })

    @app.get("/api/portfolio")
    async def portfolio(): return JSONResponse(_load_json("status.json", {"positions": {}, "pnl": 0}))

    @app.get("/api/universe")
    async def universe():
        symbols = get_nifty500_symbols()
        # Format for frontend: {s: symbol, n: name, sec: sector, base: price}
        # For now just return symbols, or more metadata if available
        from src.data.universe import get_sector
        universe_data = []
        for s in symbols[:100]: # Limit to top 100 for dashboard performance
            universe_data.append({
                "s": s,
                "n": s.replace("-", " ").title(),
                "sec": get_sector(s),
                "base": 1000 # Default base price
            })
        return JSONResponse(universe_data)

    @app.get("/api/signals")
    async def signals(): return JSONResponse(_load_json("signals.json", []))

    @app.get("/health")
    async def health():
        return JSONResponse(get_health_status(agents=_agents_ref, data_fetcher=_data_fetcher_ref))

    @app.post("/api/command")
    async def command(payload: dict):
        # Security: require DASHBOARD_SECRET token in every command payload
        _secret = os.getenv("DASHBOARD_SECRET", "")
        if _secret and payload.get("auth_token", "") != _secret:
            raise HTTPException(status_code=403, detail="Unauthorized — invalid auth_token")
        cmd = payload.get("command", "").strip().lower()
        guardian = _agents_ref.get('GUARDIAN')
        if cmd in ("pause", "/pause"): 
            if guardian: guardian.pause()
            return {"result": "Paused"}
        elif cmd in ("resume", "/resume"):
            if guardian: guardian.resume()
            return {"result": "Resumed"}
        return {"result": "Unknown command"}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        loop = asyncio.get_running_loop()
        update_queue = asyncio.Queue()

        def on_state_updated(event):
            asyncio.run_coroutine_threadsafe(update_queue.put(event.payload), loop)

        if _event_bus_ref:
            try:
                from src.event_bus.event_bus import EventType
                _event_bus_ref.subscribe(EventType.STATE_UPDATED, on_state_updated)
            except Exception as e:
                logger.debug(f"Failed to subscribe WS: {e}")

        # Push an initial state so frontend displays immediately
        await update_queue.put(None)

        try:
            while True:
                try:
                    receive_task = asyncio.create_task(websocket.receive_text())
                    update_task  = asyncio.create_task(update_queue.get())
                    
                    done, pending = await asyncio.wait(
                        [receive_task, update_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    if update_task in done:
                        event_payload = update_task.result()
                        receive_task.cancel()
                        
                        if event_payload is None:
                            status_data = _load_json("status.json", {})
                            signals_data = _load_json("signals.json", [])
                            agent_statuses = {}
                            for name, agent in list(_agents_ref.items()):
                                try:
                                    agent_statuses[name] = {
                                        "alive": bool(getattr(agent, 'is_active', True)),
                                        "kpi": float(getattr(agent, 'kpi', 0.72)),
                                        "activity": str(getattr(agent, 'last_activity', 'Running')),
                                    }
                                except Exception: pass
                        else:
                            status_data = event_payload.get("status", {})
                            signals_data = event_payload.get("signals", [])
                            agent_statuses = event_payload.get("agents", {})
                            
                        ws_payload = {
                            "type": "status",
                            "system": {
                                "status": "RUNNING", "mode": os.getenv('MODE', 'PAPER'),
                                "timestamp": datetime.now().isoformat(), "agents": agent_statuses,
                            },
                            "regime": status_data.get("regime", "TRENDING"),
                            "sentiment": status_data.get("sentiment", 0.5),
                            "positions": list(status_data.get("positions", {}).values()) if isinstance(status_data.get("positions"), dict) else status_data.get("positions", []),
                            "picks": status_data.get("picks", []),
                            "candidates": status_data.get("candidates", []),
                            "macro": status_data.get("macro", {}),
                            "macro_status": status_data.get("macro_status", "LIVE"),
                            "intel": status_data.get("intel", {}),
                            "signals": signals_data,
                        }
                        await websocket.send_text(_safe_json_dumps(ws_payload))
                        
                    elif receive_task in done:
                        _ = receive_task.result()
                        update_task.cancel()
                        
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.debug(f"WS loop item error: {e}")
                    break
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    return app

def run_dashboard(port: int = 8000, agents: Dict = None, data_fetcher=None, event_bus=None):
    app = create_app(agents, data_fetcher, event_bus)
    if app:
        # Bind to 127.0.0.1 only — prevents LAN/network exposure
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
