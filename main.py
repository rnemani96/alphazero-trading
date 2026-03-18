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
from src.data.discovery import get_best_performing_stocks

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
        logging.FileHandler("logs/alphazero_v3.log", encoding="utf-8"),
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

# ── Event Bus ─────────────────────────────────────────────────────────────────
eb = None
try:
    from src.event_bus.event_bus import EventBus
    eb = EventBus()
except ImportError as e:
    logger.warning("EventBus not loaded: %s", e)

# ── Paper / Live Executor ─────────────────────────────────────────────────────
_cfg = vars(settings)
executor = None
try:
    if settings.MODE == "LIVE":
        from src.execution.openalgo_executor import OpenAlgoExecutor
        executor = OpenAlgoExecutor()
    else:
        from src.execution.paper_executor import PaperExecutor
        executor = PaperExecutor(_cfg)
    logger.info("Executor: %s", type(executor).__name__)
except ImportError as e:
    logger.warning("Executor not loaded: %s", e)

# ── Agent imports (all 16) ───────────────────────────────────────────────────
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

_try_import_agent("ZEUS",      "src.agents.zeus_agent",             "ZeusAgent",     eb, _cfg)
_try_import_agent("ORACLE",    "src.agents.oracle_agent",           "OracleAgent",   eb, _cfg)
_try_import_agent("ATLAS",     "src.agents.sector_agent",           "SectorAgent",   eb, _cfg)
_try_import_agent("SIGMA",     "src.agents.sigma_agent",            "SigmaAgent",    eb, _cfg)
_try_import_agent("APEX",      "src.agents.chief_agent",            "ChiefAgent",    eb, _cfg)
_try_import_agent("NEXUS",     "src.agents.intraday_regime_agent",  "IntradayRegimeAgent", eb, _cfg)
_try_import_agent("HERMES",    "src.agents.news_sentiment_agent",   "NewsSentimentAgent",  eb, _cfg)
_try_import_agent("TITAN",     "src.agents.titan_agent",            "TitanAgent",    eb, _cfg)
_try_import_agent("GUARDIAN",  "src.agents.guardian_agent",         "GuardianAgent", eb, _cfg)
_try_import_agent("MERCURY",   "src.agents.mercury_agent",          "MercuryAgent",  eb, _cfg, executor)
_try_import_agent("LENS",      "src.agents.lens_agent",             "LensAgent",     eb, _cfg)
_try_import_agent("KARMA",     "src.agents.karma_agent",            "KarmaAgent",    eb, _cfg)
_try_import_agent("MTF",       "src.agents.multi_timeframe_agent",  "MultiTimeframeAgent", eb, _cfg)
_try_import_agent("OPTIONS",   "src.agents.options_flow_agent",     "OptionsFlowAgent",    eb, _cfg)
_try_import_agent("EARNINGS",  "src.agents.llm_earnings_analyzer",  "EarningsCallAnalyzer", eb, _cfg)
_try_import_agent("STRATEGY",  "src.agents.llm_strategy_generator", "StrategyGenerator",   eb, _cfg)

active_agents = {k: v for k, v in agents.items() if v is not None}
logger.info("Agents online: %d / %d", len(active_agents), 16)

# ── Capital Allocator ─────────────────────────────────────────────────────────
try:
    from src.risk.capital_allocator import CapitalAllocator
    capital_allocator = CapitalAllocator(total_capital=settings.INITIAL_CAPITAL)
except ImportError:
    capital_allocator = None

# ── State ─────────────────────────────────────────────────────────────────────
_state: Dict[str, Any] = {
    "iteration":       0,
    "regime":          "TRENDING",
    "sentiment":       0.5,
    "selected_stocks": [],
    "candidates":      [],
    "last_training_date": None,
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
        # Internal persistent state
        with open(STATE_FILE, "w") as f:
            json.dump(_state, f, indent=2, default=str)
        
        # Dashboard status.json sync
        status_data = {
            "picks": _state.get("selected_stocks", []),
            "candidates": _state.get("candidates", []),
            "positions": _state.get("portfolio", {}),
            "pnl": _state.get("net_pnl", 0),
            "macro": _state.get("macro", {}),
            "regime": _state.get("regime", "TRENDING"),
            "sentiment": _state.get("sentiment", 0.5),
            "iteration": _state.get("iteration", 0)
        }
        with open("logs/status.json", "w") as f:
            json.dump(status_data, f, indent=2, default=str)
            
        # Dashboard signals.json sync (for the Signals tab)
        with open("logs/signals.json", "w") as f:
            json.dump(_state.get("latest_signals", []), f, indent=2, default=str)
            
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
    
    # ── Step 0: Market Data Global Fetch ──────────────────────────────────────
    universe_symbols = [s.get("symbol") for s in _build_sigma_candidates()]
    if AP:
        universe_symbols += list(AP.open_positions.keys())
    universe_symbols = list(set(universe_symbols))
    
    mdata = {}
    mdata_history = {} # Full candle history for KARMA training
    prices = {}
    
    import pandas as pd
    from src.data.indicators import add_all_indicators

    if universe_symbols:
        raw_quotes = _get_market_data(universe_symbols)
        prices = raw_quotes.get("prices", {})
        
        for sym in universe_symbols:
            try:
                # 250 days ensures indicators like EMA200/MA200 have enough data
                bars = _get_candles(sym, period="250d", interval="1d")
                if not bars:
                    continue
                mdata_history[sym] = bars
                df = pd.DataFrame(bars)
                df.columns = [str(c).lower() for c in df.columns]
                if 'close' not in df.columns:
                    continue
                
                # Update last bar with latest live price
                if prices.get(sym, 0) > 0:
                    df.loc[df.index[-1], 'close'] = prices[sym]
                
                df = add_all_indicators(df)
                if not df.empty:
                    latest = dict(df.iloc[-1])
                    latest['price'] = latest.get('close', prices.get(sym, 0))
                    mdata[sym] = latest
            except Exception as e:
                logger.debug("MData build failed for %s: %s", sym, e)

        # Update global state for dashboard and portfolio
        _state["market_data"] = {sym: {"ltp": prices.get(sym, 0)} for sym in universe_symbols}
        _update_portfolio_prices(prices)

    # ── Step 1: Macro / Regime ───────────────────────────────────────────────
    regime    = _state.get("regime", "TRENDING")
    sentiment = _state.get("sentiment", 0.5)

    if agents["ORACLE"] and hasattr(agents["ORACLE"], "analyze"):
        try:
            agents["ORACLE"].update_activity("Analyzing macro indicators...")
            macro = agents["ORACLE"].analyze(mdata)
            _state["macro"] = macro
            agents["ORACLE"].update_activity(f"Bias: {macro.get('bias', 'NEUTRAL')}")
            agents_run += 1
        except Exception as e:
            logger.warning("[ORACLE] failed: %s", e)

    if agents["NEXUS"] and hasattr(agents["NEXUS"], "detect_regime"):
        try:
            agents["NEXUS"].update_activity("Detecting market regime...")
            r = agents["NEXUS"].detect_regime(mdata)
            regime = r.get("regime", regime) if isinstance(r, dict) else regime
            _state["regime"] = regime
            agents["NEXUS"].update_activity(f"Regime: {regime}")
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
                agents["SIGMA"].update_activity("Scoring discovered stocks...")
                candidates = _build_sigma_candidates()
                _state["candidates"] = candidates
                scored = agents["SIGMA"].score_stocks(candidates, regime)
                if agents["APEX"] and hasattr(agents["APEX"], "select_portfolio"):
                    agents["APEX"].update_activity("Constructing optimal portfolio...")
                    selected = agents["APEX"].select_portfolio(scored, {}, regime)
                    # Filter out symbols already in open positions
                    if AP:
                        blocked = AP.get_summary().get("blocked_symbols", [])
                        selected = [s for s in selected if s.get("symbol") not in blocked]
                    _state["selected_stocks"] = selected
                    selected_stocks = selected
                    agents["APEX"].update_activity(f"Selected {len(selected)} candidates")
                    agents_run += 1
            except Exception as e:
                logger.warning("[SIGMA/APEX] failed: %s", e)

    # ── Step 3: Filtered mdata for TITAN ──────────────────────────────────────
    selected_symbols = list({s.get("symbol") for s in selected_stocks if s.get("symbol")})
    if AP:
        selected_symbols += list(AP.open_positions.keys())
    selected_symbols = list(set(selected_symbols))

    # mdata is already built for the whole universe in step 0. 
    # Just ensure we have what we need for the selected ones.
    mdata_filtered = {s: mdata[s] for s in selected_symbols if s in mdata}


    # ── Step 4: TITAN signals ─────────────────────────────────────────────────
    signals = []
    if market_hours and agents["TITAN"] and hasattr(agents["TITAN"], "generate_signals"):
        try:
            agents["TITAN"].update_activity(f"Generating signals for {len(mdata_filtered)} stocks...")
            signals = agents["TITAN"].generate_signals(mdata_filtered, regime=regime)
            _state["latest_signals"] = signals
            agents["TITAN"].update_activity(f"Generated {len(signals)} signals")
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

    # ── Step 12: Training ─────────────────────────────────────────────────────
    # Post-market training on 8 months of history (as requested)
    now_ist = datetime.now(IST)
    is_training_time = now_ist.hour >= 18 or (now_ist.hour == 18 and now_ist.minute >= 30)
    today_str = now_ist.strftime("%Y-%m-%d")

    if is_training_time and _state.get("last_training_date") != today_str:
        if agents["KARMA"] and hasattr(agents["KARMA"], "run_offline_training"):
            try:
                agents["KARMA"].update_activity("Running deep 8-mo historical training...")
                _run_post_market_training()
                _state["last_training_date"] = today_str
                agents_run += 1
            except Exception as e:
                logger.warning("[KARMA] training failed: %s", e)
    elif market_hours and agents["KARMA"] and hasattr(agents["KARMA"], "train"):
        # Live lighter training during market hours
        try:
            agents["KARMA"].train(mdata_history)
            agents_run += 1
        except Exception as e:
            logger.warning("[KARMA] live training failed: %s", e)

    # ── Step 13: Write state ──────────────────────────────────────────────────
    if AP:
        _state["active_portfolio"] = AP.get_summary()
    _write_state()

    logger.info("Agents run: %d/16 | Signals: %d | Executed: %d | Market hours: %s",
                agents_run, len(final_signals), executed, market_hours)
    logger.info("Sleeping %ds...", settings.ITERATION_SLEEP_SEC)


def _build_sigma_candidates() -> List[Dict]:
    """Build candidate list for SIGMA scoring using dynamic discovery."""
    return get_best_performing_stocks(limit=50)


def _run_post_market_training():
    """Identifies top/bottom movers and trains KARMA on 8 months of '1day' history."""
    from src.data.discovery import get_market_movers
    import yfinance as yf
    
    logger.info("🎓 Starting deep 8-month historical training cycle...")
    movers = get_market_movers(limit=10, index="NIFTY 500")
    training_symbols = [s["symbol"] for s in movers.get("gainers", []) + movers.get("losers", [])]
    
    if not training_symbols:
        logger.warning("No training symbols found.")
        return

    yf_symbols = [f"{s}.NS" for s in training_symbols]
    historical_data = {}
    
    try:
        logger.info(f"Downloading 8 months of data for {len(yf_symbols)} symbols...")
        data = yf.download(yf_symbols, period="8mo", interval="1d", progress=False, group_by='ticker')
        
        for sym_ns in yf_symbols:
            sym = sym_ns.replace(".NS", "")
            if sym_ns in data.columns.get_level_values(0):
                df = data[sym_ns].dropna()
                candles = []
                for ts, row in df.iterrows():
                    candles.append({
                        "timestamp": ts.isoformat(),
                        "open":  row["Open"], "high":  row["High"],
                        "low":   row["Low"],  "close": row["Close"], 
                        "volume": row["Volume"]
                    })
                historical_data[sym] = candles
        
        if historical_data:
            agents["KARMA"].run_offline_training(historical_data)
            logger.info("🎓 Post-market training complete.")
            
    except Exception as e:
        logger.error(f"Post-market training data fetch failed: {e}")


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
    """Start the FastAPI dashboard backend from dashboard/backend.py"""
    try:
        from dashboard.backend import run_dashboard
        import threading
        port = settings.BACKEND_PORT
        logger.info("Starting FastAPI Dashboard server on http://localhost:%d", port)
        threading.Thread(
            target=run_dashboard, 
            args=(port, agents, MSD), 
            daemon=True
        ).start()
    except Exception as e:
        logger.warning("Could not start dashboard backend: %s", e)


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
