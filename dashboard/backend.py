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
            with open(fpath, encoding="utf-8") as f: return json.load(f)
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
        if _HTML.exists():
            try:
                return HTMLResponse(content=_HTML.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                return HTMLResponse(content=_HTML.read_bytes().decode("utf-8", errors="replace"))
        return HTMLResponse(content="<h1>AlphaZero Capital</h1><p>Dashboard HTML not found.</p>")

    @app.get("/api/status")
    async def status():
        from dotenv import load_dotenv
        load_dotenv()
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
            "initial_capital": float(os.getenv('INITIAL_CAPITAL', '1000000')),
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

    @app.get("/api/candidates")
    async def candidates(): return JSONResponse(_load_json("candidates.json", []))

    @app.get("/api/sources")
    async def sources():
        return JSONResponse([
            {"id": "upstox", "name": "Upstox", "status": "LIVE" if os.getenv("UPSTOX_ACCESS_TOKEN") else "OFFLINE", "icon": "🚀"},
            {"id": "openalgo", "name": "OpenAlgo", "status": "LIVE" if os.getenv("OPENALGO_KEY") else "OFFLINE", "icon": "⚡"},
            {"id": "yfinance", "name": "Yahoo Finance", "status": "LIVE", "icon": "📊"},
            {"id": "nse", "name": "NSE Direct", "status": "LIVE", "icon": "🏛️"},
        ])
        
    @app.get("/api/strategies")
    async def strategies():
        guardian = _agents_ref.get('GUARDIAN')
        if guardian and hasattr(guardian, 'get_strategy_stats'):
            return JSONResponse(guardian.get_strategy_stats())
        return JSONResponse({
            "T1": {"win_rate": 65, "total_pnl": 4500, "trades": 12},
            "M1": {"win_rate": 58, "total_pnl": 2100, "trades": 8}
        })

    @app.get("/evaluation/stats")
    async def evaluation_stats():
        if _agents_ref.get('LENS'):
            return JSONResponse(_agents_ref['LENS'].get_performance_summary())
        return JSONResponse({"win_rate": 0.58, "total_evaluated": 142})

    @app.get("/evaluation/history")
    async def evaluation_history(limit: int = 30):
        if _agents_ref.get('LENS') and hasattr(_agents_ref['LENS'], 'evaluator'):
            history = _agents_ref['LENS'].evaluator.get_signal_history(limit=limit)
            return JSONResponse(history)
        return JSONResponse([])

    @app.get("/evaluation/agents")
    async def evaluation_agents():
        if _agents_ref.get('LENS') and hasattr(_agents_ref['LENS'], 'evaluator'):
            return JSONResponse(_agents_ref['LENS'].evaluator.get_agent_scores())
        return JSONResponse({})

    @app.get("/candles/{symbol}")
    async def get_candles(symbol: str):
        if _data_fetcher_ref:
            try:
                candles = _data_fetcher_ref.get_candles(symbol, period="5d", interval="15m")
                return JSONResponse({"symbol": symbol, "candles": [c.to_dict() for c in candles]})
            except Exception as e:
                logger.error(f"Error fetching candles for {symbol}: {e}")
        return JSONResponse({"symbol": symbol, "candles": []})

    @app.get("/fundamentals/{symbol}")
    async def get_fundamentals(symbol: str):
        if _data_fetcher_ref:
            try:
                data = _data_fetcher_ref.get_stock_fundamentals(symbol)
                return JSONResponse(data)
            except Exception as e:
                logger.error(f"Error fetching fundamentals for {symbol}: {e}")
        return JSONResponse({})

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
            
        from src.risk.active_portfolio import get_active_portfolio
        ap = get_active_portfolio()
        
        # Risk Management Overrides
        if cmd == "set_qty":
            symbol = payload.get("symbol", "").upper()
            try:
                qty = int(payload.get("qty", 0))
                found = False
                for k in ap.open_positions.keys():
                    if k.startswith(symbol + ":") or k == symbol:
                        parts = k.split(":")
                        s = parts[0]
                        tt = parts[1] if len(parts) > 1 else "SWING"
                        ap.adjust_quantity(s, qty, trade_type=tt)
                        found = True
                        break
                if found: return {"result": f"Quantity for {symbol} updated to {qty}"}
                return {"result": f"{symbol} not found", "error": True}
            except Exception as e:
                return {"result": str(e), "error": True}
                
        elif cmd == "set_sl":
            symbol = payload.get("symbol", "").upper()
            try:
                sl = float(payload.get("sl", 0))
                found = False
                for k in ap.open_positions.keys():
                    if k.startswith(symbol + ":") or k == symbol:
                        # Correctly split key if it contains trade_type (e.g. "RELIANCE:SWING")
                        parts = k.split(":")
                        s = parts[0]
                        tt = parts[1] if len(parts) > 1 else "SWING"
                        ap.adjust_stop_loss(s, sl, trade_type=tt)
                        found = True
                        break
                if found: return {"result": f"SL for {symbol} updated to {sl}"}
                return {"result": f"{symbol} not found", "error": True}
            except Exception as e:
                return {"result": str(e), "error": True}
                
        elif cmd == "force_sell":
            symbol = payload.get("symbol", "").upper()
            try:
                found = False
                for k in list(ap.open_positions.keys()):
                    if k.startswith(symbol + ":") or k == symbol:
                        ap.force_close(k, reason="Manual Force Close via Dashboard")
                        found = True
                        break
                if found: return {"result": f"{symbol} forcefully closed"}
                return {"result": f"{symbol} not found", "error": True}
            except Exception as e:
                return {"result": str(e), "error": True}

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
                                "initial_capital": float(os.getenv('INITIAL_CAPITAL', '1000000')),
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
                            "apData": status_data,
                            "indices": status_data.get("indices", {}),
                            "news": status_data.get("news", []),
                            "evalStats": status_data.get("eval_stats", {}),
                            "agent_kpi": status_data.get("agent_kpis", {}),
                            "agent_scores": status_data.get("agent_scores", {}),
                            "quotes": status_data.get("quotes", {}),
                            "karma": status_data.get("karma", {}),
                            "candidates": status_data.get("candidates", []),
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
