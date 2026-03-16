"""
main.py  —  AlphaZero Capital  (v3.0)
═══════════════════════════════════════════════════════════════════════════════
Main orchestrator — 16 Agents + Multi-Source Data + Active Portfolio Guard

KEY CHANGES in v3.0:
  ✅ Multi-source data engine (Upstox + OpenAlgo + yfinance + NSE Direct
     + Stooq + Twelve Data + Finnhub + Alpha Vantage)
  ✅ ActivePortfolio guard — swing/positional positions held until target/SL
  ✅ No new stocks added while max positions filled (except intraday)
  ✅ All agents still intact and operational
  ✅ Persistent position tracking across restarts
"""

from __future__ import annotations
import json
import logging
import os
import signal
import sys
import time
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# ── Load env before any internal imports ─────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

IST = ZoneInfo("Asia/Kolkata")

# ── Logging setup ─────────────────────────────────────────────────────────────
LOG_FMT = "%(asctime)s │ %(name)-8s │ %(levelname)-5s │ %(message)s"
logging.basicConfig(
    level   = logging.INFO,
    format  = LOG_FMT,
    datefmt = "%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/alphazero.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("Main")

# ── Internal imports ──────────────────────────────────────────────────────────
try:
    from config.settings import settings
except ImportError:
    logger.error("config/settings.py missing — run from project root.")
    sys.exit(1)

# Multi-source data engine (v3.0)
try:
    from src.data.multi_source_data import get_msd, MultiSourceData
    MSD: MultiSourceData = get_msd()
    logger.info("MultiSourceData engine initialised. Sources: %s", MSD.get_source_status())
except ImportError as e:
    logger.warning("multi_source_data not found, falling back to fetch.py: %s", e)
    MSD = None

# Legacy DataFetcher fallback
try:
    from src.data.fetch import DataFetcher
    _fetcher = DataFetcher(vars(settings))
    FETCHER_OK = True
except Exception as e:
    logger.warning("DataFetcher failed: %s", e)
    FETCHER_OK = False
    _fetcher = None

# Active Portfolio Guard (v3.0)
try:
    from src.risk.active_portfolio import get_active_portfolio, ActivePortfolio
    AP: ActivePortfolio = get_active_portfolio(max_positions=settings.MAX_POSITIONS)
    logger.info("ActivePortfolio loaded. Open positions: %d", AP.get_summary()["total_open"])
except ImportError as e:
    logger.warning("active_portfolio not found: %s", e)
    AP = None

# ── Agent imports (all 16 — unchanged) ───────────────────────────────────────
agents: Dict[str, Any] = {}

def _try_import_agent(name: str, module: str, cls: str, *args, **kwargs):
    try:
        mod  = __import__(module, fromlist=[cls])
        klass = getattr(mod, cls)
        agents[name] = klass(*args, **kwargs) if (args or kwargs) else klass()
        logger.info("✓ Agent %s loaded", name)
    except Exception as e:
        logger.warning("✗ Agent %s failed: %s", name, e)
        agents[name] = None

_cfg = vars(settings)

_try_import_agent("ZEUS",      "src.agents.zeus_agent",             "ZeusAgent",     _cfg)
_try_import_agent("ORACLE",    "src.agents.oracle_agent",           "OracleAgent",   _cfg)
_try_import_agent("ATLAS",     "src.agents.sector_agent",            "SectorAgent",    _cfg)
_try_import_agent("SIGMA",     "src.agents.sigma_agent",            "SigmaAgent",    _cfg)
_try_import_agent("APEX",      "src.agents.chief_agent",             "ChiefAgent",     _cfg)
_try_import_agent("NEXUS",     "src.agents.intraday_regime_agent",            "IntradayRegimeAgent",    _cfg)
_try_import_agent("HERMES",    "src.agents.news_sentiment_agent",           "NewsSentimentAgent",   _cfg)
_try_import_agent("TITAN",     "src.agents.titan_agent",            "TitanAgent",    _cfg)
_try_import_agent("GUARDIAN",  "src.agents.guardian_agent",         "GuardianAgent", _cfg)
_try_import_agent("MERCURY",   "src.agents.mercury_agent",          "MercuryAgent",  _cfg)
_try_import_agent("LENS",      "src.agents.lens_agent",             "LensAgent",     _cfg)
_try_import_agent("KARMA",     "src.agents.karma_agent",            "KarmaAgent",    _cfg)
_try_import_agent("MTF",       "src.agents.multi_timeframe_agent",  "MultiTimeframeAgent", _cfg)
_try_import_agent("OPTIONS",   "src.agents.options_flow_agent",     "OptionsFlowAgent",    _cfg)
_try_import_agent("EARNINGS",  "src.agents.earnings_agent",         "EarningsAnalyzer",    _cfg)
_try_import_agent("STRATEGY",  "src.agents.strategy_generator",     "StrategyGenerator",   _cfg)

active_agents = {k: v for k, v in agents.items() if v is not None}
logger.info("Agents online: %d / %d", len(active_agents), 16)

# ── Capital Allocator ─────────────────────────────────────────────────────────
try:
    from src.risk.capital_allocator import CapitalAllocator
    capital_allocator = CapitalAllocator(total_capital=settings.INITIAL_CAPITAL)
except ImportError:
    capital_allocator = None

# ── Paper / Live Executor ─────────────────────────────────────────────────────
executor = None
try:
    if settings.MODE == "LIVE":
        from src.execution.openalgo_executor import OpenAlgoExecutor
        executor = OpenAlgoExecutor(_cfg)
    else:
        from src.execution.paper_executor import PaperExecutor
        executor = PaperExecutor(_cfg)
    logger.info("Executor: %s", type(executor).__name__)
except ImportError as e:
    logger.warning("Executor not loaded: %s", e)

# ── State ─────────────────────────────────────────────────────────────────────
_state: Dict[str, Any] = {
    "iteration":       0,
    "regime":          "TRENDING",
    "sentiment":       0.5,
    "selected_stocks": [],
    "capital_alloc":   {},
    "portfolio":       {},
    "market_data":     {},
    "running":         True,
}
_state_lock = threading.Lock()

os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)
os.makedirs("models", exist_ok=True)

STATE_FILE = "data/alphazero_state.json"


def _write_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(_state, f, indent=2, default=str)
    except Exception as e:
        logger.warning("State write error: %s", e)


# ── Market data helpers ───────────────────────────────────────────────────────

def _get_market_data(symbols: List[str]) -> Dict[str, Any]:
    """Fetch live market data via multi-source engine with fallback."""
    if MSD:
        try:
            quotes = MSD.get_bulk_quotes(symbols)
            prices = {sym: q.get("ltp", 0) for sym, q in quotes.items()}
            return {"prices": prices, "quotes": quotes}
        except Exception as e:
            logger.warning("MSD bulk quote failed: %s", e)
    # Fallback to legacy fetcher
    if FETCHER_OK and _fetcher:
        try:
            return _fetcher.get_market_data(symbols)
        except Exception as e:
            logger.warning("Legacy fetcher failed: %s", e)
    return {"prices": {s: 0 for s in symbols}, "quotes": {}}


def _get_candles(symbol: str, period: str = "60d", interval: str = "1d") -> list:
    """Fetch OHLCV candles via multi-source engine with fallback."""
    if MSD:
        try:
            bars = MSD.get_candles(symbol, period=period, interval=interval)
            return [b.to_dict() for b in bars] if bars else []
        except Exception as e:
            logger.debug("MSD candles failed for %s: %s", symbol, e)
    if FETCHER_OK and _fetcher:
        try:
            return _fetcher.get_ohlcv(symbol, interval=interval)
        except Exception:
            pass
    return []


# ── Portfolio guard integration ───────────────────────────────────────────────

def _check_position_allowed(symbol: str, trade_type: str = "SWING") -> tuple[bool, str]:
    """Check if a new position can be opened using the ActivePortfolio guard."""
    if AP and settings.HOLD_UNTIL_TARGET:
        return AP.can_add_position(symbol, trade_type)
    return True, "Guard disabled"


def _register_trade(signal: Dict):
    """Register a new trade with the ActivePortfolio after execution."""
    if not AP:
        return
    sym      = signal.get("symbol", "")
    trade_type = signal.get("trade_type", "SWING").upper()
    if trade_type == "INTRADAY":
        return  # Intraday managed separately
    entry    = signal.get("entry_price", signal.get("price", 0))
    qty      = signal.get("quantity", signal.get("qty", 0))
    target   = signal.get("target", 0)
    sl       = signal.get("stop_loss", 0)
    strategy = signal.get("strategy_name", signal.get("strategy", ""))
    atr      = signal.get("atr", 0)
    sector   = signal.get("sector", "")
    conf     = signal.get("confidence", 0)
    if entry > 0 and qty > 0 and sym:
        AP.open_position(sym, entry, qty, target=target or None, stop_loss=sl or None,
                         strategy=strategy, trade_type=trade_type,
                         atr=atr, sector=sector, confidence=conf)


def _update_portfolio_prices(prices: Dict[str, float]):
    """Tick the ActivePortfolio with current prices and handle target/SL hits."""
    if not AP:
        return
    closed = AP.update_prices(prices)
    for pos in closed:
        sym    = pos["symbol"]
        status = pos["status"]
        reason = pos.get("close_reason", "")
        pnl    = pos.get("realised_pnl", 0)
        logger.info("🔔 POSITION CLOSED — %s | %s | P&L ₹%+,.0f | %s", sym, status, pnl, reason)
        # Telegram alert if enabled
        _send_telegram_alert(f"🔔 *{sym}* {status}\n{reason}\nP&L: ₹{pnl:+,.0f}")


def _send_telegram_alert(message: str):
    """Send a Telegram notification if configured."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=5,
        )
    except Exception:
        pass


# ── Main loop ─────────────────────────────────────────────────────────────────

def _is_market_hours() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Saturday, Sunday
        return False
    market_open  = now.replace(hour=settings.MARKET_OPEN_HOUR,  minute=settings.MARKET_OPEN_MIN,  second=0)
    market_close = now.replace(hour=settings.MARKET_CLOSE_HOUR, minute=settings.MARKET_CLOSE_MIN, second=0)
    return market_open <= now <= market_close


def _run_iteration():
    global _state
    _state["iteration"] += 1
    it = _state["iteration"]
    logger.info("─" * 50)
    logger.info("Iteration %d | %s", it, datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"))

    market_hours = _is_market_hours()
    agents_run   = 0

    # ── Step 1: Macro / Regime ───────────────────────────────────────────────
    regime    = _state.get("regime", "TRENDING")
    sentiment = _state.get("sentiment", 0.5)

    if agents["ORACLE"] and hasattr(agents["ORACLE"], "analyze"):
        try:
            macro = agents["ORACLE"].analyze()
            _state["macro"] = macro
        except Exception as e:
            logger.warning("[ORACLE] failed: %s", e)

    if agents["NEXUS"] and hasattr(agents["NEXUS"], "detect_regime"):
        try:
            r = agents["NEXUS"].detect_regime()
            regime = r.get("regime", regime) if isinstance(r, dict) else regime
            _state["regime"] = regime
            agents_run += 1
        except Exception as e:
            logger.warning("[NEXUS] failed: %s", e)

    if agents["HERMES"] and hasattr(agents["HERMES"], "analyze_market_sentiment"):
        try:
            sent = agents["HERMES"].analyze_market_sentiment()
            sentiment = sent.get("overall_sentiment", sentiment) if isinstance(sent, dict) else sentiment
            _state["sentiment"] = sentiment
            agents_run += 1
        except Exception as e:
            logger.warning("[HERMES] failed: %s", e)

    # ── Step 2: Sector + Stock Selection (only if slots available) ────────────
    new_stocks_allowed = True
    if AP and settings.HOLD_UNTIL_TARGET:
        summary = AP.get_summary()
        slots   = summary["slots_available"]
        new_stocks_allowed = slots > 0
        if not new_stocks_allowed:
            logger.info("All %d position slots filled. Monitoring existing positions...", settings.MAX_POSITIONS)

    selected_stocks = _state.get("selected_stocks", [])

    if new_stocks_allowed:
        if agents["ATLAS"] and hasattr(agents["ATLAS"], "allocate_sectors"):
            try:
                agents["ATLAS"].allocate_sectors()
                agents_run += 1
            except Exception as e:
                logger.warning("[ATLAS] failed: %s", e)

        if agents["SIGMA"] and hasattr(agents["SIGMA"], "score_stocks"):
            try:
                candidates = _build_sigma_candidates()
                scored = agents["SIGMA"].score_stocks(candidates, regime)
                if agents["APEX"] and hasattr(agents["APEX"], "select_portfolio"):
                    selected = agents["APEX"].select_portfolio(scored, {}, regime)
                    # Filter out symbols already in open positions
                    if AP:
                        blocked = AP.get_summary().get("blocked_symbols", [])
                        selected = [s for s in selected if s.get("symbol") not in blocked]
                    _state["selected_stocks"] = selected
                    selected_stocks = selected
                    agents_run += 1
            except Exception as e:
                logger.warning("[SIGMA/APEX] failed: %s", e)

    # ── Step 3: Market data for all relevant symbols ──────────────────────────
    symbols = list({s.get("symbol") for s in selected_stocks if s.get("symbol")})
    if AP:
        symbols += list(AP.open_positions.keys())
    symbols = list(set(symbols))

    mdata = {}
    prices = {}
    if symbols:
        raw = _get_market_data(symbols)
        prices = raw.get("prices", {})
        mdata  = raw
        _state["market_data"] = {sym: {"ltp": prices.get(sym, 0)} for sym in symbols}
        # Update open position prices
        _update_portfolio_prices(prices)

    # ── Step 4: TITAN signals ─────────────────────────────────────────────────
    signals = []
    if market_hours and agents["TITAN"] and hasattr(agents["TITAN"], "generate_signals"):
        try:
            signals = agents["TITAN"].generate_signals(selected_stocks, regime, mdata)
            agents_run += 1
        except Exception as e:
            logger.warning("[TITAN] failed: %s", e)

    # ── Step 5: Multi-timeframe confirmation ──────────────────────────────────
    confirmed_signals = []
    if signals and agents["MTF"] and hasattr(agents["MTF"], "confirm_signals"):
        try:
            confirmed_signals = agents["MTF"].confirm_signals(signals)
            agents_run += 1
        except Exception as e:
            logger.warning("[MTF] failed: %s", e)
            confirmed_signals = signals

    # ── Step 6: Risk check → Capital allocation ───────────────────────────────
    approved_signals = []
    if confirmed_signals and agents["GUARDIAN"] and hasattr(agents["GUARDIAN"], "approve_signals"):
        try:
            approved_signals = agents["GUARDIAN"].approve_signals(confirmed_signals)
            agents_run += 1
        except Exception as e:
            logger.warning("[GUARDIAN] failed: %s", e)
            approved_signals = confirmed_signals

    # ── Step 7: Portfolio guard — block stocks already invested ───────────────
    final_signals = []
    blocked_count = 0
    for sig in approved_signals:
        sym        = sig.get("symbol", "")
        trade_type = sig.get("trade_type", "SWING").upper()
        allowed, reason = _check_position_allowed(sym, trade_type)
        if allowed:
            final_signals.append(sig)
        else:
            blocked_count += 1
            logger.info("🔒 BLOCKED %s — %s", sym, reason)

    if blocked_count:
        logger.info("Portfolio guard blocked %d signal(s) — existing positions not yet at target", blocked_count)

    # ── Step 8: Capital allocation ────────────────────────────────────────────
    if final_signals and capital_allocator:
        alloc = capital_allocator.allocate(
            [{"symbol": s.get("symbol"), "sigma_score": s.get("confidence", 0.5),
              "sector": s.get("sector", ""), "price": prices.get(s.get("symbol", ""), 0)}
             for s in final_signals]
        )
        _state["capital_alloc"] = alloc
        # Wire quantity back into signals
        for sig in final_signals:
            sym = sig.get("symbol", "")
            if sym in alloc:
                sig["quantity"] = alloc[sym].get("qty", 0)
                sig["qty"]      = sig["quantity"]

    # ── Step 9: Execution ─────────────────────────────────────────────────────
    executed = 0
    if final_signals and executor and market_hours:
        for sig in final_signals:
            if sig.get("quantity", 0) <= 0:
                continue
            try:
                if settings.MODE == "LIVE":
                    result = executor.execute(sig)
                else:
                    result = executor.execute(sig)  # paper executor
                if result and result.get("status") in ("success", "COMPLETE", "filled"):
                    _register_trade(sig)
                    executed += 1
                    logger.info(
                        "✅ EXECUTED %s × %d @ ₹%.2f [%s]",
                        sig.get("symbol"), sig.get("quantity", 0),
                        sig.get("entry_price", sig.get("price", 0)),
                        sig.get("strategy", ""),
                    )
            except Exception as e:
                logger.error("[Mercury] execution error for %s: %s", sig.get("symbol"), e)
        agents_run += 1

    # ── Step 10: Intraday (if market hours) ───────────────────────────────────
    if market_hours and agents["NEXUS"]:
        try:
            intraday_regime = regime
            if agents["MTF"] and hasattr(agents["MTF"], "get_intraday_regime"):
                intraday_regime = agents["MTF"].get_intraday_regime() or regime
            # Intraday signals bypass the portfolio guard
        except Exception:
            pass

    # ── Step 11: LENS — Attribution ───────────────────────────────────────────
    if agents["LENS"] and hasattr(agents["LENS"], "attribute"):
        try:
            agents["LENS"].attribute()
            agents_run += 1
        except Exception as e:
            logger.warning("[LENS] failed: %s", e)

    # ── Step 12: KARMA off-hours training ─────────────────────────────────────
    now_hour = datetime.now(IST).hour
    if (not market_hours and
        agents["KARMA"] and
        now_hour == settings.TRAINING_HOUR and
        settings.TRAINING_ENABLED and
        hasattr(agents["KARMA"], "train")):
        try:
            agents["KARMA"].train()
            logger.info("🎓 KARMA training cycle complete")
            agents_run += 1
        except Exception as e:
            logger.warning("[KARMA] training failed: %s", e)

    # ── Step 13: Write state ──────────────────────────────────────────────────
    if AP:
        _state["active_portfolio"] = AP.get_summary()
    _write_state()

    logger.info("Agents run: %d/16 | Signals: %d | Executed: %d | Market hours: %s",
                agents_run, len(final_signals), executed, market_hours)
    logger.info("Sleeping %ds...", settings.ITERATION_SLEEP_SEC)


def _build_sigma_candidates() -> List[Dict]:
    """Build candidate list for SIGMA scoring."""
    universe = [
        {"symbol": s, "sector": "AUTO"} for s in [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "KOTAKBANK",
            "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "WIPRO", "HCLTECH",
            "AXISBANK", "LT", "MARUTI", "BAJFINANCE", "BAJAJFINSV", "TATAMOTORS",
            "TATASTEEL", "SUNPHARMA", "NTPC", "POWERGRID", "TECHM", "ULTRACEMCO",
            "ASIANPAINT", "HINDALCO", "JSWSTEEL", "ONGC", "COALINDIA", "GRASIM",
            "DRREDDY", "CIPLA", "DIVISLAB", "ADANIPORTS", "SIEMENS", "NESTLEIND",
        ]
    ]
    return universe


# ── Signal handler ────────────────────────────────────────────────────────────

def _shutdown(sig, frame):
    logger.info("Shutdown signal received")
    _state["running"] = False
    _write_state()
    sys.exit(0)

signal.signal(signal.SIGINT,  _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


# ── HTTP State Server (for dashboard) ────────────────────────────────────────

def _start_state_server():
    """Serve state JSON + portfolio data on a simple HTTP endpoint."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import json

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # silence access logs

        def do_GET(self):
            path = self.path.split("?")[0]
            cors = {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json",
            }

            if path == "/state":
                body = json.dumps(_state, default=str).encode()
            elif path == "/portfolio":
                body = json.dumps(AP.get_summary() if AP else {}, default=str).encode()
            elif path == "/portfolio/positions":
                body = json.dumps(list(AP.open_positions.values()) if AP else [], default=str).encode()
            elif path == "/portfolio/history":
                body = json.dumps(AP.history[-50:] if AP else [], default=str).encode()
            elif path.startswith("/candles/"):
                sym  = path.split("/candles/")[1]
                bars = _get_candles(sym, period="60d", interval="1d")
                body = json.dumps({"candles": bars}, default=str).encode()
            elif path.startswith("/quote/"):
                sym  = path.split("/quote/")[1]
                q    = MSD.get_quote(sym) if MSD else {}
                body = json.dumps(q, default=str).encode()
            elif path == "/sources":
                body = json.dumps(MSD.get_source_status() if MSD else {}, default=str).encode()
            elif path == "/health":
                body = json.dumps({
                    "status": "ok",
                    "agents_online": len(active_agents),
                    "mode": settings.MODE,
                    "iteration": _state["iteration"],
                    "open_positions": len(AP.open_positions) if AP else 0,
                }).encode()
            else:
                self.send_response(404)
                for k, v in cors.items():
                    self.send_header(k, v)
                self.end_headers()
                return

            self.send_response(200)
            for k, v in cors.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            """Handle portfolio override commands."""
            from urllib.parse import urlparse, parse_qs
            path = self.path.split("?")[0]
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length)) if length else {}
            cors = {"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"}

            resp = {"status": "ok"}
            if path == "/portfolio/close" and AP:
                sym   = payload.get("symbol", "")
                price = payload.get("price", 0)
                AP.force_close(sym, price, reason="Dashboard manual close")
                resp["message"] = f"Force closed {sym}"
            elif path == "/portfolio/adjust_target" and AP:
                AP.adjust_target(payload.get("symbol"), payload.get("target"))
                resp["message"] = "Target adjusted"
            elif path == "/portfolio/adjust_sl" and AP:
                AP.adjust_stop_loss(payload.get("symbol"), payload.get("stop_loss"))
                resp["message"] = "Stop-loss adjusted"

            body = json.dumps(resp).encode()
            self.send_response(200)
            for k, v in cors.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    port = settings.BACKEND_PORT
    server = HTTPServer((settings.BACKEND_HOST, port), Handler)
    logger.info("State server running on http://localhost:%d", port)
    threading.Thread(target=server.serve_forever, daemon=True).start()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    logger.info("═" * 60)
    logger.info("AlphaZero Capital v3.0")
    logger.info("MODE: %s | Capital: ₹%s", settings.MODE, f"{settings.INITIAL_CAPITAL:,.0f}")
    logger.info("Agents: %d/16 | Data sources: %s",
                len(active_agents),
                ", ".join(k for k, v in (MSD.get_source_status() if MSD else {}).items() if v))
    if AP:
        summary = AP.get_summary()
        logger.info("Portfolio: %d/%d positions open | Hold-until-target: %s",
                    summary["total_open"], settings.MAX_POSITIONS, settings.HOLD_UNTIL_TARGET)
    logger.info("═" * 60)

    # Start state server for dashboard
    _start_state_server()

    # Main loop
    while _state["running"]:
        try:
            _run_iteration()
        except Exception as e:
            logger.exception("Iteration error: %s", e)
        time.sleep(settings.ITERATION_SLEEP_SEC)


if __name__ == "__main__":
    main()
