"""
AlphaZero Capital v2 — Dashboard Backend
FastAPI server that bridges Python agents ↔ React dashboard.
Serves real NSE data from yfinance/OpenAlgo.
Run: uvicorn src.dashboard.backend:app --reload --port 8000
"""
import sys
import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.data.market_data import MarketDataEngine, is_market_open, next_market_open
from src.evaluator import EvaluationEngine, SignalRecord
from src.titan import TitanStrategyEngine
from src.guardian import GuardianRiskEngine, RiskConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("Backend")

# ── Init engines ───────────────────────────────────────────────────────────
app       = FastAPI(title="AlphaZero Capital v2", version="2.0")
market    = MarketDataEngine()
evaluator = EvaluationEngine()
titan     = TitanStrategyEngine()
guardian  = GuardianRiskEngine(RiskConfig())

NSE_STOCKS = [
    "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","SBIN","WIPRO",
    "TATAMOTORS","SUNPHARMA","MARUTI","BAJFINANCE","AXISBANK",
    "KOTAKBANK","HINDUNILVR","ASIANPAINT","TITAN","NTPC",
    "POWERGRID","LTIM","ULTRACEMCO",
]

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── WebSocket manager ──────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self): self.active: list[WebSocket] = []
    async def connect(self, ws: WebSocket):
        await ws.accept(); self.active.append(ws)
    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)
    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try: await ws.send_json(data)
            except Exception: dead.append(ws)
        for ws in dead: self.disconnect(ws)

ws_manager = ConnectionManager()

# ── Background tasks ───────────────────────────────────────────────────────
_quote_cache: dict = {}
_index_cache: dict = {}
_candle_cache: dict = {}

async def poll_market_data():
    """Poll live quotes every 15s and push to WebSocket clients."""
    while True:
        try:
            quotes = market.fetch_all_quotes(NSE_STOCKS)
            nifty, bnk, vix = market.get_nifty_vix()
            global _quote_cache, _index_cache
            _quote_cache  = quotes
            _index_cache  = {"nifty": nifty, "banknifty": bnk, "vix": vix,
                              "market_open": is_market_open(),
                              "timestamp": datetime.now().isoformat()}

            # Evaluate pending signals
            live_prices = {sym: q.get("ltp", 0) for sym, q in quotes.items()}
            evaluated = evaluator.evaluate_pending(live_prices)
            if evaluated:
                karma_report = evaluator.get_karma_report()
                logger.info("LENS: %d signals evaluated. KARMA report ready.", len(evaluated))

            # Push to all WebSocket clients
            await ws_manager.broadcast({
                "type":    "QUOTE_UPDATE",
                "quotes":  quotes,
                "indices": _index_cache,
                "eval_stats": evaluator.get_dashboard_stats(),
            })
        except Exception as e:
            logger.error("Poll error: %s", e)
        await asyncio.sleep(15)

async def build_candle_cache():
    """Pre-load historical candles for all stocks on startup."""
    logger.info("Loading historical candles for %d stocks...", len(NSE_STOCKS))
    for sym in NSE_STOCKS:
        candles = market.fetch_historical(sym, period="3mo", interval="15m")
        if candles:
            _candle_cache[sym] = [c.to_dict() for c in candles[-200:]]
            logger.info("  %s: %d candles loaded", sym, len(_candle_cache[sym]))
        await asyncio.sleep(0.5)  # rate limit
    logger.info("Historical data loaded.")

@app.on_event("startup")
async def startup():
    asyncio.create_task(build_candle_cache())
    asyncio.create_task(poll_market_data())
    logger.info("AlphaZero backend started. Docs at http://localhost:8000/docs")

# ── REST Endpoints ─────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "running", "version": "2.0", "market_open": is_market_open()}

@app.get("/quotes")
def get_quotes():
    return {"quotes": _quote_cache, "indices": _index_cache}

@app.get("/quote/{symbol}")
def get_quote(symbol: str):
    q = market.get_live_quote(symbol.upper())
    if not q:
        raise HTTPException(404, f"No quote for {symbol}")
    return q

@app.get("/candles/{symbol}")
def get_candles(symbol: str, period: str = "3mo", interval: str = "15m"):
    """Fetch real historical candles."""
    sym = symbol.upper()
    if sym in _candle_cache:
        return {"symbol": sym, "candles": _candle_cache[sym], "source": "cache"}
    candles = market.fetch_historical(sym, period, interval)
    data = [c.to_dict() for c in candles]
    _candle_cache[sym] = data
    return {"symbol": sym, "candles": data, "source": "live"}

@app.get("/indices")
def get_indices():
    return _index_cache or {"nifty": 0, "banknifty": 0, "vix": 0,
                             "market_open": is_market_open()}

@app.get("/signals/{symbol}")
def get_signals(symbol: str, regime: str = "TRENDING"):
    """Run TITAN strategies on real historical data and return signals."""
    import pandas as pd
    sym = symbol.upper()
    candles = market.fetch_historical(sym, period="1mo", interval="15m")
    if not candles:
        raise HTTPException(404, f"No candle data for {sym}")
    df = pd.DataFrame([c.to_dict() for c in candles])
    df.rename(columns={"close":"Close","open":"Open","high":"High","low":"Low","volume":"Volume"}, inplace=True)
    df.set_index("datetime", inplace=True)
    signals = titan.compute_all(df, symbol=sym, regime=regime)
    consensus = titan.get_consensus(signals)
    result = [{
        "id": s.strategy_id, "name": s.strategy_name, "category": s.category,
        "signal": s.signal, "confidence": s.confidence, "reason": s.reason,
    } for s in signals]
    return {"symbol": sym, "signals": result, "consensus": consensus,
            "count": len(result), "regime": regime}

@app.post("/signal/log")
def log_signal(payload: dict):
    """Log a signal for evaluation."""
    rec = SignalRecord(**payload)
    evaluator.log_signal(rec)
    return {"status": "logged", "id": rec.id}

@app.get("/evaluation/stats")
def eval_stats():
    return evaluator.get_dashboard_stats()

@app.get("/evaluation/history")
def eval_history(limit: int = 50):
    return evaluator.get_signal_history(limit)

@app.get("/evaluation/agents")
def agent_scores():
    return evaluator.get_agent_scores()

@app.get("/evaluation/strategies")
def strategy_leaderboard():
    return evaluator.get_strategy_leaderboard()

@app.get("/evaluation/karma")
def karma_report():
    """Full KARMA learning report."""
    return evaluator.get_karma_report()

@app.get("/portfolio")
def portfolio():
    return guardian.portfolio_summary()

@app.get("/market/status")
def market_status():
    open_ = is_market_open()
    return {
        "open": open_,
        "next_open": next_market_open().isoformat() if not open_ else None,
        "timestamp": datetime.now().isoformat(),
    }

# ── WebSocket ───────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    logger.info("WS client connected. Total: %d", len(ws_manager.active))
    try:
        # Send initial state
        await websocket.send_json({
            "type": "INIT",
            "quotes": _quote_cache,
            "indices": _index_cache,
            "eval_stats": evaluator.get_dashboard_stats(),
        })
        while True:
            # Keep alive — listen for client messages
            data = await websocket.receive_text()
            msg  = json.loads(data)
            if msg.get("type") == "PING":
                await websocket.send_json({"type": "PONG"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        logger.info("WS client disconnected. Total: %d", len(ws_manager.active))
