"""
src/dashboard/backend.py  —  AlphaZero Capital
════════════════════════════════════════════════
FastAPI server — bridges Python agents ↔ React dashboard (alphazero_v3.jsx).

Endpoints:
  GET  /                     → health check
  GET  /quotes               → all cached quotes
  GET  /quote/{symbol}       → single live quote
  GET  /candles/{symbol}     → historical OHLCV
  GET  /indices              → Nifty50, BankNifty, VIX
  GET  /signals/{symbol}     → TITAN strategy signals
  GET  /portfolio            → Guardian portfolio + risk summary
  GET  /market/status        → NSE open/closed
  POST /signal/log           → log a signal for LENS evaluation
  GET  /evaluation/stats     → LENS aggregated stats
  GET  /evaluation/history   → recent evaluated signals
  GET  /evaluation/agents    → agent leaderboard
  GET  /evaluation/strategies→ strategy leaderboard
  GET  /evaluation/karma     → KARMA report
  WS   /ws                   → live quote stream (every 15s)

Run:
  uvicorn src.dashboard.backend:app --reload --port 8000
  OR (from repo root):
  python -m uvicorn src.dashboard.backend:app --port 8000
"""

# root/dashboard/backend.py — AlphaZero Capital v4
# root/dashboard/backend.py — AlphaZero Capital v4
import sys
import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional

# ── Repo root on sys.path
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
# Support two layouts:
#   dashboard/backend.py      → repo root is one level up
#   src/dashboard/backend.py  → repo root is two levels up
_REPO_ROOT = os.path.abspath(os.path.join(_BACKEND_DIR, ".."))
if not os.path.exists(os.path.join(_REPO_ROOT, "src")):
    _REPO_ROOT = os.path.abspath(os.path.join(_BACKEND_DIR, "../.."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
FRONTEND_DIR = os.path.join(_BACKEND_DIR, "frontend/dist")
os.makedirs(FRONTEND_DIR, exist_ok=True)

# ── FastAPI
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse

# ── Internal modules
from src.data.market_data import MarketDataEngine, is_market_open, next_market_open
from src.evaluator import EvaluationEngine, SignalRecord
from src.titan import TitanStrategyEngine
from src.guardian import GuardianRiskEngine, RiskConfig
from src.backtest.engine import BacktestEngine
from src.backtest.forward_walk import ForwardWalk

import pandas as pd

# ── Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("Backend")

# ── NSE universe
NSE_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "WIPRO",
    "TATAMOTORS", "SUNPHARMA", "MARUTI", "BAJFINANCE", "AXISBANK",
    "KOTAKBANK", "HINDUNILVR", "ASIANPAINT", "TITAN", "NTPC",
    "POWERGRID", "LTIM", "ULTRACEMCO",
]

# ── Engine singletons
market    = MarketDataEngine()
evaluator = EvaluationEngine()
titan     = TitanStrategyEngine()

# v4 Guardian init
guardian = GuardianRiskEngine()
guardian.state.capital = float(os.getenv("INITIAL_CAPITAL", 1_000_000))
guardian.state.cash    = guardian.state.capital

# ── FastAPI app
app = FastAPI(
    title="AlphaZero Capital v4",
    version="4.0",
    description="NSE AI Trading Dashboard API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Frontend
frontend_dist = os.path.join(_BACKEND_DIR, "frontend/dist")
# ── Frontend serving (fix: mount assets at root so /assets/... paths work) ──
_ASSETS_DIR = os.path.join(_BACKEND_DIR, "frontend/dist/assets")
if os.path.exists(frontend_dist):
    # Serve /assets/* — must be registered BEFORE the catch-all GET /
    if os.path.exists(_ASSETS_DIR):
        app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")

    @app.get("/")
    def root_page():
        return FileResponse(os.path.join(frontend_dist, "index.html"))

    # Catch-all SPA route — serves index.html for any unknown path
    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        idx = os.path.join(frontend_dist, "index.html")
        if os.path.exists(idx):
            return FileResponse(idx)
        return {"error": "not found"}
else:
    @app.get("/")
    def root_page():
        return {"status": "running", "version": "v4", "frontend": "not built — run: cd dashboard/alphazero-ui && npm install && npm run build && xcopy dist ..\\frontend\\dist /E /Y"}

# ── Caches
_quote_cache:  dict = {}
_index_cache:  dict = {}
_candle_cache: dict = {}

# ── WebSocket manager
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info("WS connected. Total: %d", len(self.active))

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        logger.info("WS disconnected. Total: %d", len(self.active))

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

ws_manager = ConnectionManager()

# ── Background tasks
async def poll_market_data():
    global _quote_cache, _index_cache
    while True:
        try:
            quotes         = market.fetch_all_quotes(NSE_STOCKS)
            nifty, bnk, vix = market.get_nifty_vix()
            _quote_cache   = quotes
            _index_cache   = {
                "nifty":       nifty,
                "banknifty":   bnk,
                "vix":         vix,
                "market_open": is_market_open(),
                "timestamp":   datetime.now().isoformat(),
            }
            guardian.update_prices(quotes)
            guardian.set_vix(vix)

            live_prices = {sym: q.get("ltp", 0) for sym, q in quotes.items()}
            evaluated   = evaluator.evaluate_pending(live_prices)
            if evaluated:
                logger.info("LENS evaluated %d signals", len(evaluated))

            await ws_manager.broadcast({
                "type":       "QUOTE_UPDATE",
                "quotes":     quotes,
                "indices":    _index_cache,
                "eval_stats": evaluator.get_dashboard_stats(),
                "portfolio":  guardian.portfolio_summary(),
            })
        except Exception as e:
            logger.error("Poll error: %s", e)
        await asyncio.sleep(15)

async def build_candle_cache():
    global _candle_cache
    logger.info("Pre-loading candles for %d stocks…", len(NSE_STOCKS))
    for sym in NSE_STOCKS:
        try:
            candles = market.fetch_historical(sym, period="55d", interval="15m")
            if candles:
                _candle_cache[sym] = [c.to_dict() for c in candles[-200:]]
                logger.info("  %s: %d candles", sym, len(_candle_cache[sym]))
        except Exception as e:
            logger.warning("  %s candle load error: %s", sym, e)
        await asyncio.sleep(0.3)
    logger.info("Candle cache ready.")

@app.on_event("startup")
async def startup():
    asyncio.create_task(build_candle_cache())
    asyncio.create_task(poll_market_data())
    logger.info("━" * 60)

# ── Backtesting Endpoints
@app.get("/api/backtest")
async def run_backtest(
    start_date: str = "2024-01-01",
    end_date: str = "2024-03-31",
    symbols: Optional[str] = None
):
    """
    Run a simplified backtest for a list of symbols.
    """
    sym_list = symbols.split(",") if symbols else NSE_STOCKS[:5]
    try:
        engine = BacktestEngine(initial_capital=1_000_000)
        results = engine.run(start_date, end_date, sym_list)
        # Convert non-serializable objects (like timestamps) where needed
        return results
    except Exception as e:
        logger.error(f"Backtest API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/forward-walk")
async def run_forward_walk(
    start_date: str = "2023-01-01",
    end_date: str = "2024-03-31",
    symbols: Optional[str] = None
):
    """
    Run a forward-walk (sliding window) validation.
    """
    sym_list = symbols.split(",") if symbols else NSE_STOCKS[:1]
    try:
        engine = BacktestEngine(initial_capital=1_000_000)
        fw = ForwardWalk(engine)
        results = fw.run(start_date, end_date, sym_list)
        return fw.get_summary()
    except Exception as e:
        logger.error(f"Forward Walk API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    logger.info("AlphaZero Capital Backend v4  |  port 8000")
    logger.info("Docs: http://localhost:8000/docs")
    logger.info("WS:   ws://localhost:8000/ws")
    logger.info("━" * 60)