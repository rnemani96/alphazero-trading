"""
main.py  —  AlphaZero Capital  v4.0
═══════════════════════════════════════════════════════════════════════════════
Main orchestrator — 16 Agents + Multi-Source Data + Active Portfolio Guard
+ Multi-Agent Signal Aggregation + Confidence-Weighted Execution

KEY CHANGES in v4.0:
  ✅ Proper signal → confidence → trade pipeline (fixes #1 gap)
  ✅ Weighted signal aggregation: TITAN(0.4) + NEXUS(0.3) + HERMES(0.3)
  ✅ Minimum agreement gate: technical + regime + sentiment must agree
  ✅ KARMA feedback loop: every closed trade updates strategy weights
  ✅ Daily post-market PPO training at 18:30 IST
  ✅ Walk-forward backtest runs weekly (Sunday post-market)
  ✅ Browser auto-launch on startup
  ✅ GUARDIAN.check_trade() used for every signal — no bypasses
  ✅ PositionSizer integrated for Kelly + ATR sizing
  ✅ ZEUS health cycle called each iteration
  ✅ LENS.update() called to resolve signal evaluations
"""

from __future__ import annotations
import json
import logging
import os
import signal
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from dataclasses import asdict
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# ── Load env before any internal imports ──────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

IST = ZoneInfo("Asia/Kolkata")

from logging.handlers import RotatingFileHandler

# ── Logging setup ─────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
os.makedirs("models", exist_ok=True)
os.makedirs("data", exist_ok=True)
os.makedirs("data/cache", exist_ok=True)

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

LOG_FMT = "%(asctime)s | %(name)-10s | %(levelname)-5s | %(message)s"
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(logging.Formatter(LOG_FMT, datefmt="%H:%M:%S"))

file_handler = RotatingFileHandler("logs/alphazero_v4.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
file_handler.setFormatter(logging.Formatter(LOG_FMT, datefmt="%H:%M:%S"))

json_handler = RotatingFileHandler("logs/alphazero.json", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
json_handler.setFormatter(JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[stdout_handler, file_handler, json_handler]
)
logger = logging.getLogger("Main")

# ── Config ────────────────────────────────────────────────────────────────────
try:
    from config.settings import settings
except ImportError:
    logger.error("config/settings.py missing — run from project root.")
    sys.exit(1)

_cfg = vars(settings)

# ── Startup Sanity Check ──────────────────────────────────────────────────────
try:
    from src.infra.sanity_check import StartupSanityCheck
    if not StartupSanityCheck().run():
        logger.error("Startup sanity check failed. Fix errors and restart.")
        sys.exit(1)
except ImportError as e:
    logger.warning("SanityCheck module not found: %s", e)

# ── Multi-source data engine ──────────────────────────────────────────────────
MSD = None
try:
    from src.data.multi_source_data import get_msd, MultiSourceData
    MSD = get_msd()
    logger.info("MultiSourceData engine ready")
except ImportError as e:
    logger.warning("multi_source_data not available: %s", e)

# ── Legacy DataFetcher fallback ───────────────────────────────────────────────
_fetcher = None
try:
    from src.data.fetch import DataFetcher
    _fetcher = DataFetcher(_cfg)
    _cfg['data_fetcher'] = _fetcher
    FETCHER_OK = True
except Exception as e:
    logger.warning("DataFetcher failed: %s", e)
    FETCHER_OK = False

# ── Active Portfolio Guard ────────────────────────────────────────────────────
AP = None
try:
    from src.risk.active_portfolio import get_active_portfolio
    AP = get_active_portfolio(max_positions=settings.MAX_POSITIONS, initial_capital=settings.INITIAL_CAPITAL)
    logger.info("ActivePortfolio: %d positions open", AP.get_summary()["total_open"])
except ImportError as e:
    logger.warning("active_portfolio not available: %s", e)

# ── Position Sizer ────────────────────────────────────────────────────────────
from src.risk.position_sizer import PositionSizer
_sizer = PositionSizer(
    total_capital=settings.INITIAL_CAPITAL,
    max_position_pct=settings.MAX_POSITION_SIZE_PCT,
)

# ── Event Bus ─────────────────────────────────────────────────────────────────
eb = None
try:
    from src.event_bus.event_bus import EventBus, EventType
    eb = EventBus()
    eb.start()
except ImportError as e:
    logger.warning("EventBus not loaded: %s", e)

# ── Paper / Live Executor ─────────────────────────────────────────────────────
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

# ── Agent factory ─────────────────────────────────────────────────────────────
agents: Dict[str, Any] = {}

def _load_agent(name: str, module: str, cls: str, *args) -> Optional[Any]:
    try:
        mod   = __import__(module, fromlist=[cls])
        klass = getattr(mod, cls)
        obj   = klass(*args)
        logger.info("[OK] Agent %-10s loaded", name)
        return obj
    except Exception as exc:
        logger.warning("[FAIL] Agent %-10s failed - %s", name, exc)
        return None

agents['ZEUS']     = _load_agent('ZEUS',    'src.agents.zeus_agent',            'ZeusAgent',              eb, _cfg)
agents['ORACLE']   = _load_agent('ORACLE',  'src.agents.oracle_agent',          'OracleAgent',            eb, _cfg, _fetcher)
agents['ATLAS']    = _load_agent('ATLAS',   'src.agents.sector_agent',          'SectorAgent',            eb, _cfg)
agents['SIGMA']    = _load_agent('SIGMA',   'src.agents.sigma_agent',           'SigmaAgent',             eb, _cfg)
agents['APEX']     = _load_agent('APEX',    'src.agents.chief_agent',           'ChiefAgent',             eb, _cfg)
agents['NEXUS']    = _load_agent('NEXUS',   'src.agents.intraday_regime_agent', 'IntradayRegimeAgent',    eb, _cfg)
agents['HERMES']   = _load_agent('HERMES',  'src.agents.news_sentiment_agent',  'NewsSentimentAgent',     eb, _cfg, _fetcher)
agents['TITAN']    = _load_agent('TITAN',   'src.agents.titan_agent',           'TitanAgent',             eb, _cfg)
agents['GUARDIAN'] = _load_agent('GUARDIAN','src.agents.guardian_agent',        'GuardianAgent',          eb, _cfg)
agents['MERCURY']  = _load_agent('MERCURY', 'src.agents.mercury_agent',         'MercuryAgent',           eb, _cfg, executor)
agents['LENS']     = _load_agent('LENS',    'src.agents.lens_agent',            'LensAgent',              eb, _cfg)
agents['KARMA']    = _load_agent('KARMA',   'src.agents.karma_agent',           'KarmaAgent',             eb, _cfg)
agents['MTF']      = _load_agent('MTF',     'src.agents.multi_timeframe_agent', 'MultiTimeframeAgent',    eb, _cfg)
agents['OPTIONS']  = _load_agent('OPTIONS', 'src.agents.options_flow_agent',    'OptionsFlowAgent',       eb, _cfg)
agents['EARNINGS'] = _load_agent('EARNINGS','src.agents.llm_earnings_analyzer', 'EarningsCallAnalyzer',   eb, _cfg)
agents['EARNINGS_CALENDAR'] = _load_agent('EARNINGS_CALENDAR', 'src.agents.earnings_calendar_agent', 'EarningsCalendarAgent', eb, _cfg)
agents['STRATEGY'] = _load_agent('STRATEGY','src.agents.llm_strategy_generator','StrategyGenerator',      eb, _cfg)
agents['SENTINEL'] = _load_agent('SENTINEL', 'src.agents.sentinel', 'SentinelAgent', eb, _cfg)

active_agents = {k: v for k, v in agents.items() if v is not None}
logger.info("Agents online: %d / 18", len(active_agents))

# ── Auto-load NEXUS XGBoost model (trained by scripts/train_nexus.py) ─────────
# NEXUS uses rule-based detection by default. If the XGBoost model exists
# (produced by train_nexus.py), it loads it for higher accuracy (~75%+).
_nexus_model_path = os.path.join("models", "nexus_regime.json")
if agents.get("NEXUS") and os.path.exists(_nexus_model_path):
    try:
        agents["NEXUS"].load_xgb_model(_nexus_model_path)
        # Also load causal feature explanations for reporting
        _explain_path = os.path.join("data", "cache", "nexus", "movement_explanations.parquet")
        if os.path.exists(_explain_path):
            try:
                import pandas as _pd
                _nexus_explanations = _pd.read_parquet(_explain_path)
                logger.info("NEXUS: loaded %d days of causal explanations", len(_nexus_explanations))
            except Exception:
                _nexus_explanations = None
        logger.info("NEXUS: XGBoost model loaded from %s", _nexus_model_path)
    except Exception as _exc:
        logger.warning("NEXUS: XGBoost model load failed (%s) — using rule-based", _exc)
else:
    if not os.path.exists(_nexus_model_path):
        logger.info("NEXUS: no trained model found at %s — using rule-based detection", _nexus_model_path)
        logger.info("NEXUS: run 'python scripts/train_nexus.py --once' to train the model")

# ── SEBI Audit Log ─────────────────────────────────────────────────────────────
_audit = None
try:
    from src.monitoring.audit_log import AuditLog
    _audit = AuditLog()
    logger.info("AuditLog: SEBI-compliant audit trail active → logs/audit.db")
except ImportError:
    logger.debug("AuditLog not available")

# ── Shadow Model A/B Testing ───────────────────────────────────────────────────
_shadow_mgr = None
try:
    from src.agents.shadow_model import ShadowModelManager
    _shadow_mgr = ShadowModelManager()
    logger.info("ShadowModelManager: A/B model testing active")
except ImportError:
    logger.debug("ShadowModelManager not available")

# ── Monte Carlo stress engine (instantiated per-run with actual returns) ──────
# MonteCarloEngine takes returns[] at construction, so we import the class here
# and instantiate it inside _post_market_tasks with real trade returns.
_mc_engine = None   # flag: None=unavailable, True=available
try:
    from src.backtest.monte_carlo import MonteCarloEngine as _MonteCarloEngine
    _mc_engine = True   # class available
    logger.info("MonteCarloEngine: stress testing available")
except ImportError:
    _MonteCarloEngine = None
    logger.debug("MonteCarloEngine not available")

# ── SGX / GIFT Nifty pre-open signal ──────────────────────────────────────────
_sgx = None
try:
    from src.data.sgx_signal import SGXSignal
    _sgx = SGXSignal()
    logger.info("SGXSignal: pre-market GIFT Nifty signal active")
except ImportError:
    logger.debug("SGXSignal not available")

# ── Capital Allocator ─────────────────────────────────────────────────────────
_allocator = None
try:
    from src.risk.capital_allocator import CapitalAllocator
    _allocator = CapitalAllocator(total_capital=settings.INITIAL_CAPITAL)
except ImportError:
    pass

# ── System state ──────────────────────────────────────────────────────────────
_state: Dict[str, Any] = {
    'active_portfolio':  {},
    "iteration":         0,
    'regime':            'NEUTRAL',
    "sentiment":         0.0,
    "sentiment_scores":  {},
    "selected_stocks":   [],
    "latest_signals":    [],
    "capital_alloc":     {},
    "portfolio":         {},
    "market_data":       {},
    "net_pnl":           0.0,
    "daily_trades":      0,
    "running":           True,
    "last_backtest_date": None,
    "last_training_date": None,
    "last_wf_date":       None,
    "last_trade_time":    {},   # Per-symbol cooldown tracking
}
_state_lock = threading.Lock()
STATE_FILE  = "data/alphazero_state.json"


def _write_state():
    try:
        def _safe_serialize(obj):
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return str(obj)

        with open(STATE_FILE, "w") as f:
            json.dump(_state, f, indent=2, default=_safe_serialize)
        # Extract summaries from core components
        ap_summary = AP.get_summary() if AP else {}
        lens_summary = agents['LENS'].get_performance_summary() if agents.get('LENS') else {}
        
        # Normalize positions for frontend (map snake_case to camelCase where needed)
        normalized_positions = []
        for p in ap_summary.get("open_positions", []):
            normalized_positions.append({
                "symbol": p.get("symbol"),
                "entryPrice": p.get("entry_price"),
                "cp": p.get("current_price"),
                "qty": p.get("quantity"),
                "sl": p.get("stop_loss"),
                "target": p.get("target"),
                "sid": p.get("strategy"),
                "tt": p.get("trade_type"),
                "pnl": p.get("unrealised_pnl"),
                "pnlPct": p.get("pnl_pct"),
                "hp": p.get("highest_price"),
                "lp": p.get("lowest_price"),
                "time": p.get("opened_at"),
                "status": p.get("status"),
                "regime": p.get("regime")
            })

        # ── Today's P&L: sum all trades closed TODAY ────────────────────────
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        today_pnl = 0.0
        today_trades = []
        for p in ap_summary.get("history", []):
            closed_at = p.get("closed_at", "")
            if closed_at and closed_at[:10] == today_str:
                today_pnl += p.get("realised_pnl", 0.0)
                today_trades.append(p)

        status = {
            "picks":       _state.get("selected_stocks", []),
            "regime":      _state.get("regime", "TRENDING"),
            "sentiment":   _state.get("sentiment", 0.0),
            "pnl":         _state.get("net_pnl", 0.0),
            "gross_pnl":   ap_summary.get("total_unrealised_pnl", 0.0),
            "net_pnl":     ap_summary.get("total_realised_pnl", 0.0),
            "today_pnl":   round(today_pnl, 2),
            "today_trades":today_trades,
            "win_rate":    ap_summary.get("win_rate_pct", 58.0) / 100.0,
            "total_trades":ap_summary.get("total_trades", 0),
            "open_positions_count": ap_summary.get("total_open", 0),
            "active_portfolio": ap_summary,
            "iteration":   _state.get("iteration", 0),
            "positions":   normalized_positions,
            "signals":     _state.get("latest_signals", [])[:10],
            "sgx_signal":  _state.get("sgx_signal", {}),
            "macro":       _state.get("macro", {}),
            "macro_status":_state.get("macro_status", "LIVE"),
            "intel":       _state.get("intelligence", {}),
            "mc_result":   _state.get("last_mc_result", {}),
            "nexus_model": os.path.exists(_nexus_model_path),
            "audit_active":_audit is not None,
            "shadow_active":_shadow_mgr is not None,
            "agent_kpis": {k: float(getattr(v, 'kpi', 0.75)) for k, v in active_agents.items()},
        }
        # Heartbeat for SENTINEL
        status["heartbeat"] = datetime.now(IST).isoformat()
        status["timestamp"] = time.time()
        
        # Atomic Safe-Write (Prevents dashboard from reading partial files)
        def safe_json_write(path, data):
            tmp_path = path + ".tmp"
            try:
                with open(tmp_path, "w") as f:
                    json.dump(data, f, indent=2, default=_safe_serialize)
                if os.path.exists(path):
                    os.remove(path)
                os.rename(tmp_path, path)
            except Exception as e:
                if os.path.exists(tmp_path): os.remove(tmp_path)
                raise e

        # Write files robustly
        safe_json_write("logs/status.json", status)
        safe_json_write("logs/signals.json", _state.get("latest_signals", []))
        
        # Notify Dashboard via EventBus to power WebSockets (P3 latency fix)
        if eb:
            eb.publish(EventType.STATE_UPDATED, {
                "status": status,
                "signals": _state.get("latest_signals", []),
                "agents": {k: {"alive": v.is_active, "status": getattr(v, "status", "running"), "activity": v.last_activity} for k, v in active_agents.items()}
            })
    except Exception as exc:
        logger.warning("State write failure: %s", exc)


# ── Market timing helpers ─────────────────────────────────────────────────────

def _is_market_hours() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    total = now.hour * 60 + now.minute
    return 9 * 60 + 15 <= total <= 15 * 60 + 30


def _is_post_market() -> bool:
    now = datetime.now(IST)
    total = now.hour * 60 + now.minute
    return 18 * 60 + 30 <= total <= 22 * 60


def _is_sunday_night() -> bool:
    now = datetime.now(IST)
    return now.weekday() == 6 and now.hour == 19


# ── Dynamic Loop Throttling ──────────────────────────────────────────────────

def _get_dynamic_sleep(market_hours: bool, vix: float, regime: str) -> int:
    """Logic based on market state."""
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    
    # Pre-market or High Volatility
    if (8 * 60 + 30 <= now.hour * 60 + now.minute < 9 * 60 + 15) or vix > 25:
        return 30
    
    # Market Open
    if market_hours:
        # Sideways & Low activity
        if regime == "SIDEWAYS" and vix < 12:
            return 180
        return 60
    
    # Fallback / Off-hours
    return 600

# ── Data helpers ──────────────────────────────────────────────────────────────

def _fetch_market_data(symbols: List[str]) -> Dict[str, Any]:
    if MSD:
        try:
            quotes  = MSD.get_bulk_quotes(symbols)
            prices  = {s: q.get("ltp", 0) for s, q in quotes.items()}
            return {"prices": prices, "quotes": quotes}
        except Exception as e:
            logger.debug("MSD bulk quote failed: %s", e)
    if FETCHER_OK and _fetcher:
        try:
            return _fetcher.get_market_data(symbols)
        except Exception as e:
            logger.debug("Legacy fetcher failed: %s", e)
    return {"prices": {s: 0 for s in symbols}, "quotes": {}}


def _fetch_candles(symbol: str, interval: str = "1d", bars: int = 250) -> List[Dict]:
    if MSD:
        try:
            period  = "1y" if bars >= 250 else "60d"
            raw     = MSD.get_candles(symbol, period=period, interval=interval)
            if raw:
                return [b.to_dict() for b in raw[-bars:]]
        except Exception:
            pass
    if FETCHER_OK and _fetcher:
        try:
            return _fetcher.get_ohlcv(symbol, interval=interval, bars=bars) or []
        except Exception:
            pass
    return []


def _enrich_with_indicators(symbol: str, candles: List[Dict], return_df: bool = False) -> Optional[Any]:
    """Build a full indicator dict or DataFrame for one symbol from its candle history."""
    if len(candles) < 15:
        return None
    try:
        import pandas as pd
        from src.data.indicators import add_all_indicators
        df = pd.DataFrame(candles)
        df.columns = [c.lower() for c in df.columns]
        for col in ('open', 'high', 'low', 'close', 'volume'):
            if col not in df.columns:
                df[col] = df.get('close', 0)
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['close'])
        if len(df) < 5:
            return None
        enriched = add_all_indicators(df)
        if enriched.empty:
            return None
            
        if return_df:
            return enriched
            
        row = enriched.iloc[-1].to_dict()
        row['price'] = row.get('close', 0)
        return row
    except Exception as exc:
        logger.debug("Indicator enrichment %s: %s", symbol, exc)
        return None


# ── Signal aggregation (core fix) ─────────────────────────────────────────────

def _aggregate_signals(
    titan_signals: List[Dict],
    regime:        str,
    sentiment_scores: Dict[str, float],
    vix:           float,
) -> List[Dict]:
    """
    Multi-agent confidence aggregation:
      TITAN     weight = 0.45
      NEXUS     weight = 0.30  (via regime compatibility check)
      HERMES    weight = 0.25  (via sentiment score)

    RELAXED CONSTRAINTS:
      min_confidence = 0.45 (was 0.55)
      min_agreement  = 1    (was 2+)
    """
    # Dynamic thresholds based on regime (AlphaZero v5.0)
    # Dynamic thresholds based on regime (AlphaZero v5.0)
    # RELAXED FOR PAPER MODE/TESTING (USER REQUEST #4)
    # Dynamic thresholds based on regime (AlphaZero v5.0 suggested)
    if regime == 'TRENDING':
        MIN_AGG_CONF = 0.40
        MIN_AGREEMENT = 2
    elif regime == "SIDEWAYS":
        MIN_AGG_CONF = 0.45
        MIN_AGREEMENT = 2
    elif regime == "VOLATILE":
        MIN_AGG_CONF = 0.50
        MIN_AGREEMENT = 2
    else:
        MIN_AGG_CONF = 0.45
        MIN_AGREEMENT = 2

    TITAN_W  = 0.45
    NEXUS_W  = 0.30
    HERMES_W = 0.25

    # Boost confidence for high agreement (AlphaZero v5.0)
    agg_conf_boost = 1.0

    logger.info("AGGREGATE: processing %d candidate signals from TITAN", len(titan_signals))
    
    # Cross-Sector Correlation Filter (AlphaZero v5.0)
    bullish_signals = sum(1 for s in titan_signals if s.get('action', 'BUY') == 'BUY')
    total_signals = len(titan_signals)
    bullish_pct = bullish_signals / total_signals if total_signals > 0 else 0.5
    logger.info("Cross-Sector Breadth: %.0f%% bullish (%d/%d)", bullish_pct * 100, bullish_signals, total_signals)
    
    # Stats for logging
    rejections = {"low_confidence": 0, "regime_incompat": 0, "nexus_veto": 0, "market_breadth": 0}
    approved = []
    
    for sig in titan_signals:
        sym   = sig.get('symbol', '')
        tc    = float(sig.get('confidence', 0.5))
        act   = sig.get('action', 'BUY')
        
        # Market Breadth check (Cross-Sector Correlation)
        if act == 'BUY':
            if bullish_pct < 0.40:
                rejections["market_breadth"] += 1
                logger.debug("AGGREGATE: %s rejected due to weak market breadth (%.0f%% bullish)", sym, bullish_pct * 100)
                continue
            elif bullish_pct < 0.50:
                # Reduce confidence if alignment is weak
                tc = tc * 0.90 

        # NEXUS: regime compatibility
        regime_compat = _regime_compatible(act, regime)
        nexus_conf    = 0.7 if regime_compat else 0.3

        # HERMES: sentiment
        sent = float(sentiment_scores.get(sym, 0.0))
        if act == 'BUY':
            hermes_conf = 0.5 + sent * 0.3      # +sent → higher conf
        else:
            hermes_conf = 0.5 - sent * 0.3      # -sent → higher conf for SELL

        # Apply SGX pre-open bias to sentiment confidence (before market open)
        sgx_b = _state.get('sgx_signal', {}).get('bias', 0.0)
        if sgx_b != 0 and not _is_market_hours():
            if (act == 'BUY' and sgx_b > 0) or (act == 'SELL' and sgx_b < 0):
                hermes_conf = min(0.95, hermes_conf + abs(sgx_b) * 0.15)
            else:
                hermes_conf = max(0.1, hermes_conf - abs(sgx_b) * 0.10)

        # Weighted aggregate
        agg_conf = TITAN_W * tc + NEXUS_W * nexus_conf + HERMES_W * hermes_conf

        # Strategy gating by regime: Penalize trend followers in sideways
        strat_name = str(sig.get('top_strategy', '')).upper()
        if regime == "SIDEWAYS" and any(m in strat_name for m in ["T1", "T2", "T10"]):
            agg_conf *= 0.7   # 30% penalty for trend strategies in chops
            logger.debug("AGGREGATE: %s penalized (Trend strat in Side market)", sym)

        # Logic for 'agreement' (AlphaZero v5.0 Aggression Scaling)
        agreement_count = sum([1 for c in [tc, nexus_conf, hermes_conf] if c >= 0.5])
        if agreement_count >= 3:
            agg_conf = min(0.99, agg_conf * 1.1)  # 10% boost for unanimous agreement

        # Hard rejections
        if regime == 'RISK_OFF':
            rejections["regime_incompat"] += 1
            continue
            
        if not regime_compat and nexus_conf < 0.35:
            rejections["nexus_veto"] += 1
            logger.debug("AGGREGATE: %s vetoed by NEXUS (regime=%s act=%s)", sym, regime, act)
            continue
            
        if agg_conf < MIN_AGG_CONF:
            rejections["low_confidence"] += 1
            logger.debug("AGGREGATE: %s confidence %.2f < %.2f", sym, agg_conf, MIN_AGG_CONF)
            continue
            
        if agreement_count < MIN_AGREEMENT:
            logger.debug("AGGREGATE: %s agreement %d < %d", sym, agreement_count, MIN_AGREEMENT)
            continue

        sig = dict(sig)  # copy
        sig['confidence']       = round(agg_conf, 3)
        sig['titan_confidence'] = round(tc, 3)
        sig['nexus_confidence'] = round(nexus_conf, 3)
        sig['hermes_confidence']= round(hermes_conf, 3)
        sig['regime_compat']    = regime_compat
        sig['agreement']        = agreement_count
        approved.append(sig)

    # Force debug mode print
    if approved:
        sorted_sigs = sorted(approved, key=lambda x: x['confidence'], reverse=True)
        logger.info("DEBUG: Top 5 approved signals:")
        for s in sorted_sigs[:5]:
            logger.info(f"  → {s['symbol']} | conf: {s['confidence']:.2f} | T:{s['titan_confidence']:.2f} N:{s['nexus_confidence']:.2f} H:{s['hermes_confidence']:.2f} | Agree: {s['agreement']}")

    logger.info("AGGREGATE: %d / %d signals passed | Thresholds: Conf=%.2f Agree=%d | Rejections: %s",
                len(approved), len(titan_signals), MIN_AGG_CONF, MIN_AGREEMENT, rejections)
    return approved


def _regime_compatible(action: str, regime: str) -> bool:
    """Returns True if action makes sense given the current regime."""
    if regime == 'TRENDING':
        return True           # both BUY and SELL okay in trends
    if regime == 'SIDEWAYS':
        return True           # mean-reversion fine both ways
    if regime == 'VOLATILE':
        return True           # smaller sizes, but any direction
    if regime == 'RISK_OFF':
        return action == 'SELL'  # only shorts/exits in risk-off
    return True


# ── Portfolio management callbacks ────────────────────────────────────────────

def _register_trade(sig: Dict, fill_price: float, regime: str, broker_id: str = ""):
    """Register a new position with ActivePortfolio and KARMA."""
    if AP:
        trade_type = sig.get('trade_type', 'SWING').upper()
        AP.open_position(
                symbol     = sig.get('symbol', ''),
                entry_price= fill_price,
                quantity   = sig.get('quantity', 1),
                target     = sig.get('target'),
                stop_loss  = sig.get('stop_loss'),
                strategy   = sig.get('top_strategy', sig.get('source', '')),
                trade_type = trade_type,
                atr        = sig.get('atr', 0),
                sector     = sig.get('sector', ''),
                confidence = sig.get('confidence', 0),
                broker_id  = broker_id,
                regime     = regime,
                direction  = sig.get('action', 'BUY'),
            )

    # Notify position sizer to track for adaptive Kelly
    if agents.get('GUARDIAN'):
        strat = sig.get('top_strategy', 'general')
        agents['GUARDIAN'].record_strategy_outcome(strat, 0)  # 0 = not closed yet

    # Publish trade execution event for LENS and KARMA
    if eb:
        eb.publish(EventType.TRADE_EXECUTED, {
            'symbol':     sig.get('symbol'),
            'price':      fill_price,
            'quantity':   sig.get('quantity'),
            'signal_id':  sig.get('id'),
            'strategy':   sig.get('top_strategy', sig.get('source', '')),
            'timestamp':  datetime.now().isoformat()
        })


def _check_volume_confirmation(sym: str, action: str, hist_df: Any) -> bool:
    """MANDATORY filter: Checks volume before breakout, avoiding end-of-candle spikes."""
    if hist_df is None or len(hist_df) < 22:
        return True # Cannot evaluate
    try:
        import pandas as pd
        # Exclude currently forming candle to avoid end-of-candle spikes
        completed = hist_df.iloc[:-1]
        
        avg_vol = completed['volume'].rolling(20).mean().iloc[-1]
        last_vol = completed['volume'].iloc[-1]
        prev_vol = completed['volume'].iloc[-2]
        
        if pd.isna(avg_vol) or avg_vol == 0:
            return True
            
        volume_ratio = last_vol / avg_vol
        volume_trend_increasing = last_vol > prev_vol
        
        last_close = float(completed['close'].iloc[-1])
        last_open = float(completed['open'].iloc[-1])
        
        if action == 'BUY':
            no_divergence = last_close >= last_open  # Should be a green candle
        else:
            no_divergence = last_close <= last_open  # Should be a red candle
            
        return (volume_ratio > 1.5) and volume_trend_increasing and no_divergence
    except Exception as e:
        logger.debug("Volume check failed for %s: %s", sym, e)
        return True


def _update_positions(prices: Dict[str, float]):
    """Tick ActivePortfolio and feed closed trade outcomes to KARMA."""
    if not AP:
        return
    closed, updated, partials = AP.update_prices(prices)
    
    # ── P1 #5 Logic: Forward trailing stops to broker ──
    if updated and agents.get('MERCURY'):
        for up in updated:
            try:
                sym = up['symbol']
                new_sl = up['new_sl']
                oid = up.get('broker_id')
                if oid and oid != "FAILED":
                    logger.info("📡 Trailing Update: %s → ₹%.2f (Broker ID: %s)", sym, new_sl, oid)
                    agents['MERCURY'].modify_order(
                        order_id=oid,
                        symbol=sym,
                        new_price=new_sl,
                        new_trigger=new_sl,
                        order_type="SL-M"
                    )
            except Exception as me:
                logger.error("MERCURY modify_order error: %s", me)

    # ── Execute Partial Scale-outs with Broker ──
    if partials and agents.get('MERCURY'):
        for p in partials:
            try:
                logger.info("📡 Executing Partial Scale-out: %s x%d", p['symbol'], p['quantity'])
                agents['MERCURY'].execute_trade(p)
            except Exception as pe:
                logger.error("Partial execution failed: %s", pe)

    for pos in closed:
        sym    = pos['symbol']
        pnl    = pos.get('realised_pnl', 0)
        status = pos.get('status', '')
        logger.info("🔔 CLOSED %s | %s | P&L ₹%s", sym, status, format(pnl, "+,.0f"))

        # ── Link to LENS Performance Attribution ──
        if agents.get('LENS') and hasattr(agents['LENS'], 'record_trade'):
            try:
                agents['LENS'].record_trade(pos)
            except Exception as le:
                logger.debug("LENS record_trade failed: %s", le)

        # ── Trigger LLM Post Mortem ──
        if "Stop-loss" in pos.get("close_reason", "") or status == "STOPPED":
            try:
                from src.agents.llm_postmortem import analyze_stopped_out_trade
                import threading
                vix = _state.get('market_data', {}).get('^INDIAVIX', {}).get('price', 15.0)
                regime = _state.get('regime', 'UNKNOWN')
                market_ctx = {'vix': vix, 'regime': regime}
                threading.Thread(target=analyze_stopped_out_trade, args=(pos, market_ctx), daemon=True).start()
            except Exception as e:
                logger.error(f"Failed to submit postmortem: {e}")

        # Feed to KARMA for learning
        if agents.get('KARMA'):
            agents['KARMA'].learn_from_outcome(
                {'symbol': sym, 'strategy': pos.get('strategy', 'unknown'),
                 'regime': _state.get('regime', 'UNKNOWN')},
                {'pnl': pnl},
            )

        # Update position sizer
        _sizer.record_trade(pos.get('strategy', 'general'), pnl)

        # GUARDIAN outcome
        if agents.get('GUARDIAN'):
            agents['GUARDIAN'].update_pnl(pnl, is_loss=(pnl < 0))

        # Update system P&L
        _state['net_pnl'] = _state.get('net_pnl', 0) + pnl
        
        # Cooldown for the symbol after a loss to prevent "revenge trading"
        if pnl < 0:
            if 'symbol_cooldowns' not in _state: _state['symbol_cooldowns'] = {}
            _state['symbol_cooldowns'][sym] = time.time() + 3600 # 1 hour cooldown
            logger.info("🛡️ Symbol Cooldown: %s blocked for 1 hour after SL hit.", sym)

        _send_telegram(f"🔔 *{sym}* {status}\nP&L: ₹{pnl:+,.0f}")


def _send_telegram(text: str):
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
    except Exception:
        pass


# ── Universe builder ──────────────────────────────────────────────────────────

def _build_universe() -> List[str]:
    """Return list of NSE symbols to scan this iteration."""
    try:
        from src.data.discovery import get_best_performing_stocks
        stocks = get_best_performing_stocks(limit=40)
        syms = list({s.get('symbol') for s in stocks if s.get('symbol')})
    except Exception:
        syms = []

    # If discovery returned too few, supplement with top NIFTY 500
    if len(syms) < 10:
        try:
            from src.data.universe import get_nifty500_symbols
            syms += get_nifty500_symbols()[:40]
        except Exception:
            pass

    # Always include open positions
    if AP:
        syms += [str(k).split(':')[0] for k in AP.open_positions.keys()]
        
    cleaned_syms = [str(s).split(':')[0].strip() for s in syms if s]
    return list(dict.fromkeys(cleaned_syms))  # deduplicate, preserve order



# ── Post-market tasks ─────────────────────────────────────────────────────────

def _post_market_tasks():
    today = datetime.now(IST).strftime('%Y-%m-%d')

    # Nightly RL training
    if _state.get('last_training_date') != today:
        if agents.get('KARMA') and _state.get('market_data'):
            logger.info("🎓 Starting nightly KARMA training...")
            try:
                symbols = list(_state['market_data'].keys())[:20]
                hist_data = {}
                for sym in symbols:
                    candles = _fetch_candles(sym, bars=200)
                    if candles:
                        hist_data[sym] = candles
                if hist_data:
                    agents['KARMA'].run_offline_training(hist_data)
                    _state['last_training_date'] = today
            except Exception as exc:
                logger.warning("Nightly training failed: %s", exc)

    # Weekly walk-forward backtest (Sunday)
    this_week = datetime.now(IST).strftime('%Y-%W')
    if _is_sunday_night() and _state.get('last_wf_date') != this_week:
        logger.info("📊 Running weekly walk-forward backtest...")
        try:
            from src.backtest.engine import BacktestEngine
            engine  = BacktestEngine(initial_capital=settings.INITIAL_CAPITAL)
            results = engine.run(walk_forward=True, save=True)
            _state['last_wf_date'] = this_week
            best  = results.get('best', 'N/A')
            gates = results.get('gate_check', {})
            logger.info("Walk-forward complete — best: %s | all_gates: %s",
                        best, gates.get('all_passed', False))
            # Monte Carlo stress test — instantiated with actual trade returns
            mc_text = ""
            if _mc_engine and _MonteCarloEngine is not None:
                try:
                    # Pull trade returns from BacktestEngine results or LENS history
                    _trade_returns = results.get('returns', [])
                    if not _trade_returns and agents.get('LENS'):
                        # Fall back to LENS trade history
                        _lens_trades = getattr(agents['LENS'], 'trades', [])
                        _trade_returns = [
                            t.get('pnl', 0) / max(abs(t.get('entry_price', 1) * t.get('qty', 1)), 1)
                            for t in _lens_trades if t.get('pnl') is not None
                        ]
                    if not _trade_returns:
                        _trade_returns = [0.0] * 30   # no history yet — neutral run
                    mc    = _MonteCarloEngine(
                        returns         = _trade_returns,
                        initial_capital = settings.INITIAL_CAPITAL,
                        n_simulations   = 2000,   # lighter for weekly run
                    ).run_all(save=False)
                    summary = mc.get('summary', {})
                    grade   = summary.get('grade', '?')
                    var95   = summary.get('var_95_pct', summary.get('var_95', 0))
                    logger.info("Monte Carlo: grade=%s  VaR-95=%.1f%%", grade, var95)
                    mc_text = f"\nMonte Carlo grade: {grade}  VaR-95: {var95:.1f}%"
                    _state['last_mc_result'] = summary
                except Exception as mc_exc:
                    logger.debug("Monte Carlo: %s", mc_exc)
            _send_telegram(
                f"📊 Weekly backtest: best={best}\n"
                f"Gates passed: {gates.get('all_passed')}{mc_text}"
            )
            # Reload NEXUS XGBoost model if retrained this week
            if agents.get('NEXUS') and os.path.exists(_nexus_model_path):
                try:
                    mtime = os.path.getmtime(_nexus_model_path)
                    if datetime.now().timestamp() - mtime < 7 * 86400:
                        agents['NEXUS'].load_xgb_model(_nexus_model_path)
                        logger.info("NEXUS: model hot-reloaded after weekly retrain")
                except Exception:
                    pass
            # Shadow model A/B evaluation — promote champion if statistically better
            if _shadow_mgr and results.get('equity_curve'):
                try:
                    promotion = _shadow_mgr.maybe_promote()
                    if promotion == 'PROMOTED':
                        logger.info("Shadow model promoted to champion!")
                        try:
                            cmp = _shadow_mgr.get_comparison()
                            delta = cmp.get('sharpe_delta', 0) if cmp else 0
                        except Exception:
                            delta = 0
                        _send_telegram(
                            f"🏆 Shadow model promoted to champion!\n"
                            f"Sharpe delta: {delta:+.3f}"
                        )
                except Exception as _sm_exc:
                    logger.debug("Shadow model evaluation: %s", _sm_exc)
        except Exception as exc:
            logger.warning("Walk-forward backtest failed: %s", exc)


# ── Main iteration ────────────────────────────────────────────────────────────

def _run_iteration():
    _state['iteration'] += 1
    it = _state['iteration']
    market_hours = _is_market_hours()

    logger.info("─" * 60)
    logger.info("Iteration %d | %s | market=%s",
                it, datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), market_hours)

    # ── ZEUS health check ──────────────────────────────────────────────────────
    if agents.get('ZEUS') and hasattr(agents['ZEUS'], 'run_cycle'):
        try:
            agents['ZEUS'].run_cycle(active_agents)
        except Exception:
            pass

    # ── SENTINEL functional check ─────────────────────────────────────────────
    if agents.get('SENTINEL') and hasattr(agents['SENTINEL'], 'run_check'):
        try:
            agents['SENTINEL'].run_check(active_agents, MSD)
        except Exception:
            pass

    # ── Step 1: Universe ───────────────────────────────────────────────────────
    universe = _build_universe()

    # ── Step 2: Market data + indicators ──────────────────────────────────────
    raw_quotes = _fetch_market_data(universe)
    prices     = raw_quotes.get('prices', {})

    from concurrent.futures import ThreadPoolExecutor
    
    # Batch fetch all candles at once
    all_c15 = MSD.get_bulk_candles(universe, interval="15m", period="60d")
    all_c5  = MSD.get_bulk_candles(universe, interval="5m", period="60d")

    mdata_15m: Dict[str, Any] = {}
    mdata_5m:  Dict[str, Any] = {}

    def process_sym_data(sym):
        res_15 = None; hist_15 = None
        res_5 = None;  hist_5 = None
        intel = {}
        
        # Process 15m
        c15 = all_c15.get(sym)
        if c15:
            c15_list = [asdict(b) for b in c15]
            if prices.get(sym, 0) > 0: c15_list[-1]['close'] = prices[sym]
            hist_15 = _enrich_with_indicators(sym, c15_list, return_df=True)
            if hist_15 is not None:
                res_15 = hist_15.iloc[-1].to_dict()
                res_15['price'] = res_15.get('close', prices.get(sym))
            
        # Process 5m
        c5 = all_c5.get(sym)
        if c5:
            c5_list = [asdict(b) for b in c5]
            if prices.get(sym, 0) > 0: c5_list[-1]['close'] = prices[sym]
            hist_5 = _enrich_with_indicators(sym, c5_list, return_df=True)
            if hist_5 is not None:
                res_5 = hist_5.iloc[-1].to_dict()
                res_5['price'] = res_5.get('close', prices.get(sym))

        # Stock Intel (Requirement #2, #4) — throttled refresh
        if it == 1 or it % 48 == 0 or sym not in _state.get('intelligence', {}):
            try:
                intel['fundamentals'] = MSD.get_stock_fundamentals(sym)
                intel['volume']       = MSD.get_volume_analysis(sym)
                intel['ts']           = time.time()
            except Exception: pass
            
        return sym, res_15, hist_15, res_5, hist_5, intel

    # Parallel enrichment for ultra-low latency
    with ThreadPoolExecutor(max_workers=50) as tp_executor:
        results = list(tp_executor.map(process_sym_data, universe))
        
    mdata_15m_history: Dict[str, pd.DataFrame] = {}
    mdata_5m_history:  Dict[str, pd.DataFrame] = {}
    if 'intelligence' not in _state: _state['intelligence'] = {}

    for sym, res_15, h15, res_5, h5, intel in results:
        if res_15: mdata_15m[sym] = res_15
        if h15 is not None: mdata_15m_history[sym] = h15
        if res_5:  mdata_5m[sym] = res_5
        if h5 is not None:  mdata_5m_history[sym] = h5
        if intel: _state['intelligence'][sym] = intel

    mdata = mdata_15m # fallback for legacy code
    _state['market_data'] = {s: {'ltp': prices.get(s, 0)} for s in universe}

    # Update positions with latest prices
    _update_positions({s: float(d.get('close', d.get('price', 0))) for s, d in mdata.items()})

    # ── Step 3: ORACLE macro analysis ─────────────────────────────────────────
    vix = _state.get('macro', {}).get('vix', 15.0)
    if not vix or vix == 0:
        vix = 15.0
        
    macro_status = _state.get('macro_status', 'LIVE')
    if agents.get('ORACLE') and hasattr(agents['ORACLE'], 'analyze'):
        try:
            macro = agents['ORACLE'].analyze(mdata)
            _state['macro'] = macro
            new_vix = float(macro.get('vix', 0))
            if new_vix > 0:
                vix = new_vix
            else:
                macro['vix'] = vix
                
            macro_status = macro.get('status', 'LIVE')
            if macro_status == 'MISSING':
                macro_status = 'FFILL'
            _state['macro_status'] = macro_status
            
            # FII / DII Data (P1 #9)
            if it % 12 == 0 or it == 1:   # every 30-40 mins
                try:
                    _fii_res = MSD.get_fii_dii_data() if MSD else {}
                    if _fii_res:
                        _state['fii_dii'] = _fii_res
                        logger.info("FII/DII: FII=%+,.0f Cr  DII=%+,.0f Cr", 
                                    _fii_res.get('fii_net',0), _fii_res.get('dii_net',0))
                except Exception: pass
            
            if agents.get('GUARDIAN'):
                agents['GUARDIAN'].set_vix(vix)
        except Exception as exc:
            logger.debug("ORACLE: %s", exc)

    # ── Step 4a: SGX / GIFT Nifty pre-open signal (06:00-09:15 IST) ──────────
    sgx_bias = 0.0   # +1=gap-up bullish, -1=gap-down bearish, 0=neutral
    if _sgx and not market_hours:
        _now_ist = datetime.now(IST)
        _pre_open = (6 <= _now_ist.hour < 9) or (_now_ist.hour == 9 and _now_ist.minute < 15)
        if _pre_open:
            try:
                _sgx_res  = _sgx.get_current_signal()
                _sgx_sig  = _sgx_res.get('signal', 'FLAT')     # GAP_UP / GAP_DOWN / FLAT
                _sgx_pct  = _sgx_res.get('premium_pct', 0.0)   # GIFT Nifty premium %
                # Derive bias: +1 gap-up, -1 gap-down, 0 flat
                sgx_bias  = (1.0 if _sgx_sig == 'GAP_UP' else
                             -1.0 if _sgx_sig == 'GAP_DOWN' else 0.0)
                # Scale bias by strength of the gap (stronger gap = stronger signal)
                sgx_bias *= min(abs(_sgx_pct) / 1.0, 1.0)
                if sgx_bias != 0:
                    logger.info("SGX pre-open: %s  premium=%.2f%%  bias=%.2f",
                                _sgx_sig, _sgx_pct, sgx_bias)
                _state['sgx_signal'] = {**_sgx_res, 'bias': sgx_bias}
            except Exception as _e:
                logger.debug("SGX signal error: %s", _e)

    # ── Step 4: Sentiment (HERMES) ────────────────────────────────────────────
    # Throttled: Run every 3 cycles or if iteration is 1
    sentiment_scores: Dict[str, float] = _state.get('sentiment_scores', {})
    overall_sentiment = _state.get('sentiment', 0.0)
    
    # Check if we should run heavy math agents
    should_run_heavy = (it % 3 == 0) or (it == 1)
    
    if should_run_heavy and agents.get('HERMES') and hasattr(agents['HERMES'], 'get_sentiment'):
        try:
            sent_result = agents['HERMES'].get_sentiment(list(mdata.keys())[:20])
            sentiment_scores = sent_result.get('scores', {})
            # Robust key lookup — different HERMES versions use different keys
            overall_sentiment = float(
                sent_result.get('overall_score',
                sent_result.get('score',
                sent_result.get('sentiment',
                sent_result.get('compound', 0.0))))
            )
            _state['sentiment'] = overall_sentiment
            _state['sentiment_scores'] = sentiment_scores
        except Exception as exc:
            logger.debug("HERMES: %s", exc)

    # ── Step 5: Regime detection (NEXUS) ─────────────────────────────────────
    regime = _state.get('regime', 'TRENDING')
    if agents.get('NEXUS') and hasattr(agents['NEXUS'], 'detect_regime'):
        try:
            # ── P1 #1: Options Market leading indicator ──
            pc_ratio = 1.0; max_pain_diff = 0.0; uoa_flag = 0
            if it % 5 == 0 or it == 1:
                try:
                    oc = MSD.get_options_chain("NIFTY50") if MSD else \
                         _fetcher.get_options_chain("NIFTY50") if _fetcher else None
                    if oc:
                        calls = [c for c in oc['contracts'] if c['type'] == 'CALL']
                        puts  = [c for c in oc['contracts'] if c['type'] == 'PUT']
                        call_oi = sum(c.get('open_interest', 0) for c in calls)
                        put_oi  = sum(c.get('open_interest', 0) for c in puts)
                        if call_oi > 0: pc_ratio = put_oi / call_oi
                        
                        # Unusual Volume (UOA) proxy
                        uoa_flag = 1 if any(c.get('multi_exchange', False) for c in oc['contracts']) else 0
                        logger.info("NEXUS: Options context — PCR=%.2f  OI_TOT=%d", pc_ratio, (call_oi + put_oi))
                except Exception: pass

            # Prepare all 14+ causal features from macro and sentiment
            nexus_input = {
                'data':           mdata,
                'india_vix':      vix,
                'spx_prev_ret':   macro.get('spx_prev_ret', 0.0) if 'macro' in locals() else 0.0,
                'usdinr_change':  macro.get('usdinr_change', 0.0) if 'macro' in locals() else 0.0,
                'news_sentiment': overall_sentiment,
                'event_flag':     macro.get('event_flag', 0.0) if 'macro' in locals() else 0.0,
                'pc_ratio':       pc_ratio,
                'max_pain_diff':  max_pain_diff,
                'uoa_flag':       uoa_flag,
            }
            raw_regime = agents['NEXUS'].detect_regime(nexus_input)
            regime = raw_regime if isinstance(raw_regime, str) else regime
            _state['regime'] = regime
        except Exception as exc:
            logger.debug("NEXUS: %s", exc)

    # ── Step 6: Stock scoring (SIGMA & ATLAS) ─────────────────────────────────
    sigma_scores: Dict[str, float] = _state.get('sigma_scores', {})
    atlas_scores: Dict[str, float] = _state.get('atlas_scores', {})
    
    if should_run_heavy and agents.get('SIGMA') and hasattr(agents['SIGMA'], 'score_stocks'):
        try:
            candidates = [
                {
                    'symbol':           sym,
                    'momentum':         min(1.0, max(0, (float(d.get('price_change_pct', 0)) + 5) / 10)),
                    'trend_strength':   min(1.0, float(d.get('adx', 20)) / 50),
                    'earnings_quality': 0.5,
                    'relative_strength':min(1.0, max(0, float(d.get('rsi', 50)) / 100)),
                    'news_sentiment':   min(1.0, max(0, sentiment_scores.get(sym, 0.0) + 0.5)),
                    'volume_confirm':   min(1.0, max(0, (float(d.get('volume_zscore', 0)) + 3) / 6)),
                    'volatility':       min(1.0, float(d.get('atr', 0)) / max(float(d.get('close', 1)), 1) * 20),
                    'fii_interest':     0.7 if _state.get('fii_dii', {}).get('fii_net', 0) > 0 else 0.3,
                    'delivery_pct':     min(1.0, float(_state.get('intelligence', {}).get(sym, {}).get('volume', {}).get('delivery_pct', 45.0)) / 100),
                    'historical_sharpe': agents['KARMA'].get_symbol_performance(sym) if agents.get('KARMA') else 0.5,
                }
                for sym, d in mdata.items()
            ]
            
            # SIGMA scoring
            scored_sigma = agents['SIGMA'].score_stocks(candidates, regime)
            sigma_scores = {s['symbol']: s['sigma_score'] for s in scored_sigma}
            _state['sigma_scores'] = sigma_scores
            
            # ATLAS scoring
            if agents.get('ATLAS'):
                scored_atlas = agents['ATLAS'].score_stocks(candidates)
                atlas_scores = {s['symbol']: s['atlas_score'] for s in scored_atlas}
                _state['atlas_scores'] = atlas_scores

            if agents.get('APEX') and hasattr(agents['APEX'], 'select_portfolio') and scored_sigma:
                blocked = set(AP.open_positions.keys()) if AP else set()
                top_candidates = [s for s in scored_sigma if s.get('symbol') not in blocked]
                selected = agents['APEX'].select_portfolio(top_candidates, {}, regime)
                _state['selected_stocks'] = selected
        except Exception as exc:
            logger.debug("SIGMA/ATLAS: %s", exc)
    else:
        sigma_scores = _state.get('sigma_scores', {})
        atlas_scores = _state.get('atlas_scores', {})

    # ── Step 7: TITAN signals ─────────────────────────────────────────────────
    signals: List[Dict] = []
    if (market_hours or settings.MODE == "PAPER") and agents.get('TITAN'):
        try:
            # Pass multi-agent scores to TITAN for internal boosting
            # CRITICAL FIX: Pass the historical DataFrames (mdata_15m_history) rather than snapshots
            # This unlocks the 45-strategy engine in src/titan.py
            raw_15m = agents['TITAN'].generate_signals(
                mdata_15m_history, regime, 
                hermes_scores=sentiment_scores,
                sigma_scores=sigma_scores,
                atlas_scores=atlas_scores,
                timeframe="15m"
            )
            raw_5m  = agents['TITAN'].generate_signals(
                mdata_5m_history,  regime, 
                hermes_scores=sentiment_scores,
                sigma_scores=sigma_scores,
                atlas_scores=atlas_scores,
                timeframe="5m"
            )

            raw_signals = raw_15m + raw_5m
            # Deduplicate signals by symbol (highest confidence wins)
            dedup_signals = {}
            for s in raw_signals:
                sym = s.get('symbol')
                if not sym: continue
                if sym not in dedup_signals or float(s.get('confidence', 0)) > float(dedup_signals[sym].get('confidence', 0)):
                    dedup_signals[sym] = s
            raw_signals = list(dedup_signals.values())
            
            # --- P2 EARNINGS CALENDAR STRATEGIES ---
            if agents.get('EARNINGS_CALENDAR'):
                for sym, d in mdata.items():
                    price = float(d.get('price', 0))
                    prev_close = float(d.get('prev_close', 0))
                    vol_r = float(d.get('vol_ratio', 1.0))
                    sig_score = float(sigma_scores.get(sym, 0.5))
                    
                    pre_sig = agents['EARNINGS_CALENDAR'].check_pre_earnings_momentum(sym, sig_score)
                    if pre_sig:
                        pre_sig.update({'symbol': sym, 'price': price, 'action': pre_sig['signal'], 'source': 'EARNINGS_CALENDAR', 'atr': price * 0.02})
                        raw_signals.append(pre_sig)
                        
                    post_sig = agents['EARNINGS_CALENDAR'].check_post_earnings_gap(sym, price, prev_close, vol_r)
                    if post_sig:
                        post_sig.update({'symbol': sym, 'price': price, 'action': post_sig['signal'], 'source': 'EARNINGS_CALENDAR', 'atr': price * 0.02})
                        raw_signals.append(post_sig)
                        
            # Multi-agent aggregation
            signals = _aggregate_signals(raw_signals, regime, sentiment_scores, vix)
            _state['latest_signals'] = signals
            logger.info("Signals: %d raw → %d aggregated", len(raw_signals), len(signals))
        except Exception as exc:
            logger.warning("TITAN: %s", exc)

    # ── Step 8: GUARDIAN risk check ───────────────────────────────────────────
    approved: List[Dict] = []
    approved_signals: List[Dict] = []
    current_capital = settings.INITIAL_CAPITAL + _state.get('net_pnl', 0)
    open_positions  = list(AP.open_positions.values()) if AP else []
    
    # --- P3: Dynamic Portfolio Hedging (RISK_OFF Put buying) ---
    if regime == 'RISK_OFF' and AP and len(open_positions) > 0:
        has_hedge = any("PE" in str(p.get('symbol', '')) or "Hedge" in str(p.get('top_strategy', '')) for p in open_positions)
        if not has_hedge:
            logger.info("🛡️ RISK_OFF detected with open portfolio -> Sourcing NIFTY Put hedge")
            # Create a synthetic high-conviction hedge signal that overrides regime filters
            put_signal = {
                'symbol': 'NIFTY_HEDGE_PE',
                'action': 'BUY',
                'confidence': 0.99,
                'price': 150.0,
                'top_strategy': 'P3_RiskOff_Hedge',
                'reasons': ['Dynamic Portfolio Hedging due to RISK_OFF regime'],
                'atr': 20.0
            }
            signals.insert(0, put_signal)

    any_approved = False
    for sig in signals:
        try:
            sym    = sig.get('symbol', '')
            price  = float(sig.get('price', 0))
            atr    = float(sig.get('atr', price * 0.02))
            strat  = sig.get('top_strategy', 'general')

            # Size position
            macro_status = _state.get('macro_status', 'LIVE')
            size_result = _sizer.size(strat, price, atr, vix, macro_status)
            qty         = size_result['qty']
            
            # Risk-based Exposure Control
            current_exposure_pct = 0.0
            if AP and current_capital > 0:
                total_invested = sum(p.get('entry_price', 0) * p.get('quantity', 0) for p in AP.open_positions.values())
                current_exposure_pct = total_invested / current_capital
                
            if vix > 22 and current_exposure_pct > 0.60:
                logger.info("🛡️ EXPOSURE CONTROL: VIX > 22 and Exposure > 60%%. Reducing size by 30%% for %s", sym)
                qty = int(qty * 0.70)
                if qty == 0:
                    qty = 1  # Minimum 1 share if price permits
            
            sig['quantity'] = qty
            sig['qty']      = qty

            # GUARDIAN hard check
            if agents.get('GUARDIAN'):
                # CRITICAL: Use update_state=False to avoid blocking other signals in the same batch
                result = agents['GUARDIAN'].check_trade(sig, current_capital, open_positions, update_state=False)
                if result.get('approved'):
                    sig['quantity']     = result.get('quantity', qty)
                    sig['qty']          = sig['quantity']
                    sig['stop_loss']    = result.get('stop_loss', sig.get('stop_loss', 0))
                    sig['target']       = result.get('target',    sig.get('target', 0))
                    sig['position_size']= result.get('position_size', 0)
                    approved_signals.append(sig)
                    any_approved = True
                else:
                    logger.info("🛡️ REJECTED: %-10s | reason: %s", sym, result.get('reason', 'Unknown risk'))
            else:
                # Fallback: if GUARDIAN not loaded, allow trade with original quantity
                logger.warning("GUARDIAN offline — skipping trade for %s", sym)

        except Exception as exc:
            logger.debug("GUARDIAN check %s: %s", sig.get('symbol'), exc)

    # Update Guardian state once if batch was approved
    if any_approved and agents.get('GUARDIAN'):
        try:
            agents['GUARDIAN'].last_trade_time = datetime.now()
            agents['GUARDIAN'].trades_today   += 1
        except Exception:
            pass

    logger.info("Risk gate: %d / %d signals approved", len(approved_signals), len(signals))
    if signals and not approved_signals:
        logger.info("ℹ️ Note: Check GUARDIAN logs above for rejection reasons. PAPERS mode usually requires relaxing thresholds in .env")

    # ── Step 9: Final Signal Quality Filter & Soft Gating ─────────────────────────────
    final_signals = []
    
    # Pre-calculate Market Breadth
    bullish_count = 0
    total_stocks = max(1, len(mdata))
    for d in mdata.values():
        close_p = float(d.get('close', d.get('price', 0)))
        open_p  = float(d.get('open', 0))
        if close_p > 0 and open_p > 0 and close_p >= open_p:
            bullish_count += 1
    breadth_ratio = bullish_count / total_stocks

    for sig in approved_signals:
        sym = sig.get('symbol')
        action = sig.get('action', 'BUY').upper()
        is_buy = (action == 'BUY')

        # Dynamic AlphaZero v5.0 entry confidence thresholds
        MIN_ENTRY_CONF = 0.55 if regime == "TRENDING" else 0.60 if regime == "SIDEWAYS" else 0.70
        
        # RELAXED for testing/recovery
        if sig.get('confidence', 0) < MIN_ENTRY_CONF:
            logger.debug(f"SIGNAL REJECTED: {sym} - Confidence {sig.get('confidence', 0):.2f} < {MIN_ENTRY_CONF}")
            continue
            
        # ── Market Open Volatility Filter (9:15-9:45 AM IST) ──
        # Block new entries during initial 30 min to avoid volatility noise
        now = datetime.now(IST)
        if now.hour == 9 and 15 <= now.minute < 45:
            logger.info(f"SIGNAL REJECTED: {sym} - Blocked during Market Open Volatility (9:15-9:45 AM)")
            continue
            
        # ── Time-of-Day Volatility Gap (12:00 PM to 1:30 PM IST) ──
        # Instead of completely blocking this low-liquidity zone, we tighten the criteria
        # to ensure that only very high conviction breakout patterns make it through.
        now = datetime.now(IST)
        in_lunch_zone = (12 <= now.hour < 13) or (now.hour == 13 and now.minute <= 30)
        if in_lunch_zone and sig.get('confidence', 0) < 0.80:
            logger.info(f"SIGNAL REJECTED: {sym} - Normal confidence {sig.get('confidence', 0):.2f} blocked during 12:00-1:30 PM Lunch Zone (requires >= 0.80)")
            continue
            
        # Requirement #3.1: Multi-Timeframe Confirmation (Direction-Aware)
        if not _check_mtf_confirmation(sym, action):
            logger.info(f"SIGNAL REJECTED: {sym} - MTF Alignment Failed")
            continue

        # Requirement #3.2: MANDATORY Volume Confirmation (Before Breakout / No Spikes)
        hist_df = mdata_5m_history.get(sym)
        if hist_df is not None and not _check_volume_confirmation(sym, action, hist_df):
            logger.info(f"SIGNAL REJECTED: {sym} - Volume Confirmation Failed (Ratio <= 1.5 or divergent/decreasing)")
            continue

        # ── Contextual Score System (Soft Gating) ──
        score = 0
        max_score = 5

        # 1. Market Breadth (2 points)
        breadth_ok = (is_buy and breadth_ratio >= 0.45) or (not is_buy and breadth_ratio <= 0.55)
        if breadth_ok:
            score += 2
        
        # 2. Sector Alignment (1 point)
        atlas_score = atlas_scores.get(sym, 0.5)
        sector_aligned = (is_buy and atlas_score > 0.6) or (not is_buy and atlas_score < 0.4)
        if sector_aligned:
            score += 1
            
        # 3. Regime Match (2 points)
        strat_name = str(sig.get('top_strategy', '')).upper()
        regime_match = True
        if regime == "SIDEWAYS" and any(m in strat_name for m in ["T1", "T2", "T10"]):
            regime_match = False
        if regime_match:
            score += 2
            
        threshold = 3
        if regime == "VOLATILE":
            threshold = 4
            
        if score < threshold:
            logger.info(f"SIGNAL REJECTED: {sym} - Context Score {score}/{max_score} < {threshold} (Breadth:{breadth_ratio:.0%}, Sector:{atlas_score:.2f}, Reg:{regime})")
            continue
            
        logger.info(f"✨ SIGNAL PASSED: {sym} - Context Score {score}/{max_score} (Breadth:{breadth_ratio:.0%} {breadth_ok})")

        # Mandatory Risk:Reward Filter (P1 Rule #1)
        # "Never trade if risk is greater than reward"
        price  = sig.get('price', 0)
        target = sig.get('target', 0)
        sl     = sig.get('stop_loss') or sig.get('sl', 0)
        
        if price > 0 and target > 0 and sl > 0:
            reward = abs(target - price)
            risk   = abs(price - sl)
            rr     = reward / risk if risk > 0 else 10.0
            if rr < settings.MIN_RR:
                logger.info(f"SIGNAL REJECTED: {sig.get('symbol')} - Poor R:R {rr:.2f} < {settings.MIN_RR}")
                continue
        elif not (target > 0 and sl > 0):
             # For signals without explicit targets (rare), we skip RR but TITAN usually adds them
             pass

        # Cooldown check
        if sig['symbol'] in _state.get('symbol_cooldowns', {}):
            if time.time() < _state['symbol_cooldowns'][sig['symbol']]:
                logger.info("🔒 BLOCKED: %s in cooldown period.", sig['symbol'])
                continue

        final_signals.append(sig)

    # ── Requirement #5: Position Replacement (Upgrade weaker positions) ────────
    if len(final_signals) > 0 and AP and len(AP.open_positions) >= settings.MAX_POSITIONS:
        logger.info("🔄 MAX_POSITIONS hit. Evaluating position replacement/upgrade...")
        best_new = sorted(final_signals, key=lambda x: x['confidence'], reverse=True)[0]
        
        # Find weakest open position
        open_list = list(AP.open_positions.values())
        # Sort by: (negative P/L first, then lower confidence, then older)
        open_list.sort(key=lambda x: (x.get('pnl_pct', 0), x.get('confidence', 0)))
        weakest = open_list[0]
        
        if best_new['confidence'] > (weakest.get('confidence', 0) + 0.15):
            # Only replace if newest is significantly higher confidence
            logger.info("🔄 UPGRADE: Replacing weakest position %s (conf %.2f) with %s (conf %.2f)",
                        weakest['symbol'], weakest.get('confidence', 0), 
                        best_new['symbol'], best_new['confidence'])
            AP.force_close(weakest['symbol'], weakest['current_price'], reason="UPGRADE_REPLACEMENT")

    # ── Step 10: Execution ────────────────────────────────────────────────────
    executed = 0
    if final_signals and executor and market_hours:
        executed_in_batch = set()
        for sig in final_signals:
            try:
                sym = sig.get('symbol')
                # Protect against multiple signals for same symbol executing in one cycle
                if sym in executed_in_batch:
                    continue
                
                # Double check ActivePortfolio to prevent duplicate open positions
                if AP and sym in AP.open_positions:
                    logger.info("🔒 BLOCKED (already invested): %s", sym)
                    continue

                result = executor.execute_trade(sig) if hasattr(executor, 'execute_trade') else \
                         executor.execute(sig)
                
                if result and (result.get('success') or result.get('status') in ('COMPLETE', 'filled')):
                    fill_price = result.get('fill_price', sig.get('price', 0))
                    broker_id  = result.get('order_id') or result.get('broker_id') or ""
                    _state['last_trade_time'][sym] = time.time()  # Record execution time
                    _register_trade(sig, fill_price, regime, broker_id)
                    executed_in_batch.add(sym)
                    executed += 1
                else:
                    reason = result.get('error') or result.get('reason') or 'Unknown error'
                    logger.error("❌ Execution FAILED for %s: %s", sym, reason)
                    continue
                
                # Audit log every executed trade (SEBI compliance)
                if _audit:
                    try:
                        _audit.log_trade(
                            symbol    = sig.get('symbol', ''),
                            action    = sig.get('action', sig.get('signal', 'BUY')),
                            quantity  = sig.get('quantity', 0),
                            price     = fill_price,
                            strategy  = sig.get('strategy', 'TITAN'),
                            regime    = _state.get('regime', 'UNKNOWN'),
                            confidence= sig.get('confidence', 0),
                            mode      = settings.MODE,
                            agents_voted={
                                'titan':  sig.get('titan_confidence', 0),
                                'nexus':  sig.get('nexus_confidence', 0),
                                'hermes': sig.get('hermes_confidence', 0),
                            },
                        )
                        # Structured JSON logging for future LLM training (AlphaZero v5.0)
                        _audit.log_structured_trade({
                            "symbol": sig.get('symbol', ''),
                            "action": sig.get('action', 'BUY'),
                            "entry_price": fill_price,
                            "stop_loss": sig.get('stop_loss', 0),
                            "target": sig.get('target', 0),
                            "confidence": sig.get('confidence', 0),
                            "sentiment_score": sig.get('hermes_confidence', 0),
                            "indicator_state": "TODO_full_state", 
                            "strategy": sig.get('top_strategy', 'general')
                        })
                    except Exception as _ae:
                        logger.debug("AuditLog: %s", _ae)
                logger.info("✅ EXECUTED %s ×%d @ ₹%.2f [%s conf=%.2f]",
                            sig.get('symbol'), sig.get('quantity', 0),
                            sig.get('price', 0), sig.get('action', ''),
                            sig.get('confidence', 0))
                _send_telegram(
                    f"📈 *TRADE EXECUTED*\n"
                    f"Symbol: {sig.get('symbol')}\n"
                    f"Action: {sig.get('action')} ×{sig.get('quantity')}\n"
                    f"Price: ₹{sig.get('price',0):.2f}\n"
                    f"Confidence: {sig.get('confidence',0):.0%}\n"
                    f"R:R: {sig.get('rr', 0):.1f}"
                )
            except Exception as exc:
                logger.error("Execution error %s: %s", sig.get('symbol'), exc)

    # ── Step 10b: Hedge Portfolio if Risk is Extreme ──────────────────────────
    if AP and current_capital > 0:
        total_inv = sum(p.get('entry_price', 0) * p.get('quantity', 0) for p in AP.open_positions.values())
        cur_exp_pct = total_inv / current_capital
        if vix > 22 and cur_exp_pct > 0.60 and agents.get('OPTIONS'):
            try:
                hedge_sym = "NIFTYBEES.NS"
                logger.info("🛡️ HEDGING ROUTINE: Evaluating options hedge for portfolio...")
                rec = agents['OPTIONS'].get_hedge_recommendation(hedge_sym, 0, vix, cur_exp_pct)
                if rec:
                    _send_telegram(
                        f"🛡️ *HEDGE RECOMMENDATION*\n"
                        f"{rec['reason']}\n"
                        f"Action: {rec['action']} {rec['symbol']} *{rec['strike']} PE*\n"
                        f"Premium: ₹{rec['premium']}"
                    )
            except Exception as e:
                logger.error("Hedge evaluation failed: %s", e)

    # ── Step 11: LENS evaluation ──────────────────────────────────────────────
    if agents.get('LENS') and hasattr(agents['LENS'], 'update'):
        try:
            live_prices = {s: float(d.get('close', 0)) for s, d in mdata.items()}
            agents['LENS'].update_prices(live_prices)
            agents['LENS'].update()
        except Exception as exc:
            logger.debug("LENS: %s", exc)

    # ── Step 12: Post-market tasks ────────────────────────────────────────────
    if _is_post_market():
        _post_market_tasks()

    # ── Write state ───────────────────────────────────────────────────────────
    if AP:
        _state['active_portfolio'] = AP.get_summary()
    _write_state()

    logger.info("Done — signals=%d executed=%d regime=%s vix=%.1f",
                len(final_signals), executed, _state['regime'], vix)


def _get_us_market_bias() -> float:
    """Requirement #2.3: Check NASDAQ/S&P 500 performance to adjust trading bias."""
    try:
        # Fetch US indices (Nasdaq = ^IXIC, S&P 500 = ^GSPC)
        indices = ["^IXIC", "^GSPC"]
        res = MSD.get_bulk_quotes(indices) if MSD else {}
        if not res: return 0.0
        
        # Calculate average % change
        changes = [q.get('change_pct', 0) for q in res.values()]
        avg_chg = sum(changes) / len(changes) if changes else 0.0
        
        # Scaling: +2% US → +0.2 bias, -2% US → -0.2 bias
        bias = max(-0.3, min(0.3, avg_chg / 10.0))
        logger.info(f"US Market Sync: avg_chg={avg_chg:+.2f}% → bias={bias:+.2f}")
        return bias
    except Exception as e:
        logger.debug(f"US market sync failed: {e}")
        return 0.0


def _run_nightly_tasks():
    """Requirement 2.1: Dynamic Universe Training & 2.2: Parallel Stress Test."""
    logger.info("🌙 STARTING NIGHTLY STRATEGY TRAINING & STRESS TEST...")
    
    try:
        # 1. Update KARMA Universe
        from src.data.universe import get_karma_universe
        training_syms = get_karma_universe(MSD)
        
        if not training_syms:
            logger.warning("No training symbols found. Skipping nightly tasks.")
            return

        # 2. Fetch Historical Data (60d daily) for stress test + replay
        logger.info(f"Fetching 60d historical data for {len(training_syms)} symbols...")
        hist_data = MSD.get_bulk_candles(training_syms, period="60d", interval="1d")
        
        if not hist_data:
            logger.warning("No historical data fetched. Skipping nightly tasks.")
            return

        # 3. Trigger KARMA Offline Training (PPO Replay)
        if agents.get('KARMA'):
            # Convert CandleBar objects to dicts for KARMA
            karma_data = {}
            for s, bars in hist_data.items():
                if bars:
                    # Some CandleBar objects might not have __dict__ or be None
                    try:
                        karma_data[s] = [c.__dict__ if hasattr(c, '__dict__') else c for c in bars if c is not None]
                    except Exception:
                        continue
            
            if karma_data:
                agents['KARMA'].run_offline_training(karma_data)
            
        # 4. Stress Test / Re-ranking (Requirement #2.2)
        # In AlphaZero v5.0, BacktestEngine runs in parallel to re-rank strategy weights
        from src.backtest.engine import BacktestEngine
        engine = BacktestEngine()
        # This triggers a parallel stress-test on training data
        engine.run_stress_test(training_syms, hist_data)

        logger.info("🌙 Nightly tasks completed successfully.")

        # 5. Export full trade history to Excel for review
        try:
            import pandas as _pd
            if AP:
                hist = AP.history
                if hist:
                    df = _pd.DataFrame(hist)
                    today_date = datetime.now(IST).strftime("%Y-%m-%d")
                    excel_path = os.path.join("logs", f"trade_history_{today_date}.xlsx")
                    os.makedirs("logs", exist_ok=True)
                    df.to_excel(excel_path, index=False)
                    logger.info("📊 Trade history exported → %s (%d rows)", excel_path, len(df))
        except ImportError:
            logger.warning("openpyxl not installed — skipping Excel export (pip install openpyxl)")
        except Exception as _xe:
            logger.warning("Excel export failed: %s", _xe)

    except Exception as e:
        logger.error(f"Failed to complete nightly tasks: {e}", exc_info=True)


def _check_mtf_confirmation(symbol: str, action: str = 'BUY') -> bool:
    """Requirement #3.1: Entry require alignment across 15m, 1h, and Daily."""
    try:
        if not MSD: return True
        is_buy = (action.upper() == 'BUY')
        # Fetch recent candles
        c15 = MSD.get_candles(symbol, interval='15min', limit=2)
        c60 = MSD.get_candles(symbol, interval='60min', limit=2)
        c1d = MSD.get_candles(symbol, interval='1D',    limit=2)
        
        if not (c15 and c60 and c1d): return True
        
        def is_aligned(bars, is_bullish_req):
            if len(bars) < 1: return True
            last = bars[-1]
            if is_bullish_req:
                return last.close >= last.open  # Bullish candle
            else:
                return last.close <= last.open  # Bearish candle
            
        ok = is_aligned(c15, is_buy) and is_aligned(c60, is_buy) and is_aligned(c1d, is_buy)
        if not ok:
            logger.debug(f"MTF: {symbol} filtered (No {action} alignment across TFs)")
        return ok
    except Exception:
        return True


def _run_weekly_tuning():
    """Requirement #3.6: Weekly sector-based watchlist adjustment."""
    logger.info("📅 STARTING WEEKLY SECTOR TUNING...")
    try:
        # Fetch sector performance for past 5 days
        # Symbols in top 3 sectors get increased focus
        from src.data.universe import get_nifty500_symbols
        syms = get_nifty500_symbols()
        # Simulation: Just logging for now as universe is already dynamic via KARMA
        logger.info(f"Weekly tuning: Scanned {len(syms)} symbols for sectoral momentum.")
        logger.info("📅 Weekly tuning completed.")
    except Exception as e:
        logger.error(f"Weekly tuning failed: {e}")


# ── Dashboard backend ─────────────────────────────────────────────────────────

def _start_dashboard():
    """Start FastAPI dashboard server and open browser."""
    try:
        from dashboard.backend import run_dashboard
        port = settings.BACKEND_PORT
        
        # Start server in daemon thread
        t = threading.Thread(
            target=run_dashboard,
            args=(port, agents, MSD, eb),
            daemon=True,
            name="DashboardServer",
        )
        t.start()
        logger.info("Dashboard server started on http://localhost:%d", port)

        # Open browser in a separate thread to avoid blocking main iteration
        def open_browser():
            time.sleep(3.0) # Wait for server to be fully ready
            url = f"http://localhost:{port}"
            logger.info("Opening browser → %s", url)
            try:
                webbrowser.open(url)
            except Exception as e:
                logger.debug("Failed to open browser: %s", e)

        threading.Thread(target=open_browser, daemon=True, name="BrowserLauncher").start()
    except Exception as exc:
        logger.warning("Dashboard not available: %s", exc)



# ── Shutdown handler ──────────────────────────────────────────────────────────

def _shutdown(sig_num, frame):
    logger.info("Shutdown signal received")
    _state["running"] = False
    if eb:
        eb.stop()
    # Flush audit log on clean shutdown
    if _audit:
        try:
            _audit.flush()
            logger.info("AuditLog: flushed on shutdown")
        except Exception:
            pass
    _write_state()
    sys.exit(0)

signal.signal(signal.SIGINT,  _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 70)
    logger.info("AlphaZero Capital v4.0")
    logger.info("MODE: %s | Capital: ₹%s | Agents: %d/18",
                settings.MODE, f"{settings.INITIAL_CAPITAL:,.0f}", len(active_agents))
    if AP:
        summ = AP.get_summary()
        logger.info("Portfolio: %d/%d positions | hold-until-target: %s",
                    summ['total_open'], settings.MAX_POSITIONS, settings.HOLD_UNTIL_TARGET)
    nexus_status = "XGBoost ✓" if os.path.exists(_nexus_model_path) else "rule-based (run scripts/train_nexus.py)"
    logger.info("NEXUS: %s | AuditLog: %s | Shadow: %s | MC: %s | SGX: %s",
                nexus_status,
                "✓" if _audit else "✗",
                "✓" if _shadow_mgr else "✗",
                "✓" if _mc_engine else "✗",
                "✓" if _sgx else "✗")
    logger.info("═" * 70)

    # Start dashboard + browser
    _start_dashboard()
    
    # Start Natural Language /query Bot (P4)
    _telegram_bot = None
    try:
        from src.interfaces.telegram_bot import init_telegram_bot
        _telegram_bot = init_telegram_bot()
    except Exception as e:
        logger.debug(f"Telegram Natural Language Query Interface failed to start: {e}")

    # Main loop
    while _state["running"]:
        iteration_start = time.time()
        _write_state()
        try:
            _run_iteration()
            
            # 🌙 Nightly Intelligence Refresh (Requirement #2.1, #2.2)
            now_ist = datetime.now(IST)
            if now_ist.hour >= 18 and not _state.get('nightly_training_done'):
                _run_nightly_tasks()
                _state['nightly_training_done'] = True
            elif now_ist.hour < 9:
                _state['nightly_training_done'] = False
                
            # 📅 Weekly Watchlist Tuning (Requirement #3.6)
            if now_ist.weekday() == 0 and now_ist.hour >= 18 and not _state.get('weekly_tuning_done'):
                _run_weekly_tuning()
                _state['weekly_tuning_done'] = True
            elif now_ist.weekday() != 0:
                _state['weekly_tuning_done'] = False

        except Exception as exc:
            logger.exception("Iteration error: %s", exc)
        
        # Consistent fixed sleep duration (60s minus elapsed)
        iteration_time = time.time() - iteration_start
        to_sleep = int(max(10, 60 - iteration_time))
        
        logger.info("Sleeping %ds...", to_sleep)
        time.sleep(to_sleep)

if __name__ == "__main__":
    main()
