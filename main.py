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

LOG_FMT = "%(asctime)s │ %(name)-10s │ %(levelname)-5s │ %(message)s"
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
    AP = get_active_portfolio(max_positions=settings.MAX_POSITIONS)
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
        logger.info("✓ Agent %-10s loaded", name)
        return obj
    except Exception as exc:
        logger.warning("✗ Agent %-10s failed — %s", name, exc)
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
agents['STRATEGY'] = _load_agent('STRATEGY','src.agents.llm_strategy_generator','StrategyGenerator',      eb, _cfg)
agents['SENTINEL'] = _load_agent('SENTINEL', 'src.agents.sentinel', 'SentinelAgent', eb, _cfg)

active_agents = {k: v for k, v in agents.items() if v is not None}
logger.info("Agents online: %d / 16", len(active_agents))

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
        status = {
            "picks":       _state.get("selected_stocks", []),
            "regime":      _state.get("regime", "TRENDING"),
            "sentiment":   _state.get("sentiment", 0.0),
            "pnl":         _state.get("net_pnl", 0.0),
            "iteration":   _state.get("iteration", 0),
            "positions":   list(_state.get("portfolio", {}).values()) if isinstance(_state.get("portfolio"), dict) else _state.get("portfolio", []),
            "signals":     _state.get("latest_signals", [])[:10],
            "sgx_signal":  _state.get("sgx_signal", {}),
            "macro":       _state.get("macro", {}),
            "mc_result":   _state.get("last_mc_result", {}),
            "nexus_model": os.path.exists(_nexus_model_path),
            "audit_active":_audit is not None,
            "shadow_active":_shadow_mgr is not None,
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
        
        # Notify Dashboard via EventBus
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
    if regime == 'TRENDING':
        MIN_AGG_CONF = 0.60   # Be more aggressive in strong trends
        MIN_AGREEMENT = 2
    elif regime == "SIDEWAYS":
        MIN_AGG_CONF = 0.75   # High conviction required to trade ranges
        MIN_AGREEMENT = 3
    elif regime == "VOLATILE":
        MIN_AGG_CONF = 0.72   # Safety first in high choppiness
        MIN_AGREEMENT = 2
    else:
        MIN_AGG_CONF = 0.65
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

    logger.info("AGGREGATE: %d / %d signals passed (Rejections: %s)",
                len(approved), len(titan_signals), rejections)
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

def _register_trade(sig: Dict, fill_price: float):
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


def _update_positions(prices: Dict[str, float]):
    """Tick ActivePortfolio and feed closed trade outcomes to KARMA."""
    if not AP:
        return
    closed = AP.update_prices(prices)
    for pos in closed:
        sym    = pos['symbol']
        pnl    = pos.get('realised_pnl', 0)
        status = pos.get('status', '')
        logger.info("🔔 CLOSED %s | %s | P&L ₹%+,.0f", sym, status, pnl)

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
        syms += list(AP.open_positions.keys())
    return list(dict.fromkeys(syms))  # deduplicate, preserve order



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
            
        return sym, res_15, hist_15, res_5, hist_5

    # Parallel enrichment
    with ThreadPoolExecutor(max_workers=10) as tp_executor:
        results = list(tp_executor.map(process_sym_data, universe))
        
    mdata_15m_history: Dict[str, pd.DataFrame] = {}
    mdata_5m_history:  Dict[str, pd.DataFrame] = {}

    for sym, res_15, h15, res_5, h5 in results:
        if res_15: mdata_15m[sym] = res_15
        if h15 is not None: mdata_15m_history[sym] = h15
        if res_5:  mdata_5m[sym] = res_5
        if h5 is not None:  mdata_5m_history[sym] = h5

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
            overall_sentiment = float(sent_result.get('overall_score', sent_result.get('score', 0.0)))
            _state['sentiment'] = overall_sentiment
            _state['sentiment_scores'] = sentiment_scores
        except Exception as exc:
            logger.debug("HERMES: %s", exc)

    # ── Step 5: Regime detection (NEXUS) ─────────────────────────────────────
    regime = _state.get('regime', 'TRENDING')
    if agents.get('NEXUS') and hasattr(agents['NEXUS'], 'detect_regime'):
        try:
            # Prepare all 14 causal features from macro and sentiment
            nexus_input = {
                'data':           mdata,
                'india_vix':      vix,
                'spx_prev_ret':   macro.get('spx_prev_ret', 0.0) if 'macro' in locals() else 0.0,
                'usdinr_change':  macro.get('usdinr_change', 0.0) if 'macro' in locals() else 0.0,
                'news_sentiment': overall_sentiment,
                'event_flag':     macro.get('event_flag', 0.0) if 'macro' in locals() else 0.0,
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
                    'fii_interest':     0.5,
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
    if market_hours and agents.get('TITAN'):
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
            
            # Multi-agent aggregation
            signals = _aggregate_signals(raw_signals, regime, sentiment_scores, vix)
            _state['latest_signals'] = signals
            logger.info("Signals: %d raw → %d aggregated", len(raw_signals), len(signals))
        except Exception as exc:
            logger.warning("TITAN: %s", exc)

    # ── Step 8: GUARDIAN risk check ───────────────────────────────────────────
    approved: List[Dict] = []
    current_capital = settings.INITIAL_CAPITAL + _state.get('net_pnl', 0)
    open_positions  = list(AP.open_positions.values()) if AP else []

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
                result = agents['GUARDIAN'].check_trade(sig, current_capital, open_positions)
                if result.get('approved'):
                    sig['quantity']     = result.get('quantity', qty)
                    sig['qty']          = sig['quantity']
                    sig['stop_loss']    = result.get('stop_loss', sig.get('stop_loss', 0))
                    sig['target']       = result.get('target',    sig.get('target', 0))
                    sig['position_size']= result.get('position_size', 0)
                    approved.append(sig)
                else:
                    logger.info("🛡️ REJECTED: %-10s | reason: %s", sym, result.get('reason', 'Unknown risk'))
            else:
                # Fallback: if GUARDIAN not loaded, allow trade with original quantity (risky but better than crash)
                # Alternatively: skip trade. Let's skip to be safe.
                logger.warning("GUARDIAN offline — skipping trade for %s", sym)

        except Exception as exc:
            logger.debug("GUARDIAN check %s: %s", sig.get('symbol'), exc)

    logger.info("Risk gate: %d / %d signals approved", len(approved), len(signals))
    if signals and not approved:
        logger.info("ℹ️ Note: Check GUARDIAN logs above for rejection reasons. PAPERS mode usually requires relaxing thresholds in .env")

    # ── Step 9: Portfolio guard ───────────────────────────────────────────────
    final_signals: List[Dict] = []
    if AP and settings.HOLD_UNTIL_TARGET:
        blocked = AP.get_summary().get('blocked_symbols', [])
        for sig in approved:
            if sig.get('symbol') in blocked:
                logger.info("🔒 BLOCKED (already invested): %s", sig.get('symbol'))
            else:
                final_signals.append(sig)
    else:
        final_signals = approved

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
                    _state['last_trade_time'][sym] = time.time()  # Record execution time
                    _register_trade(sig, fill_price)
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
    logger.info("═" * 70)
    logger.info("AlphaZero Capital v4.0")
    logger.info("MODE: %s | Capital: ₹%s | Agents: %d/16",
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

    # Main loop
    while _state["running"]:
        iteration_start = time.time()
        try:
            _run_iteration()
        except Exception as exc:
            logger.exception("Iteration error: %s", exc)
        
        # Consistent fixed sleep duration
        sleep_sec = 180
        elapsed = time.time() - iteration_start
        to_sleep = max(10, sleep_sec - elapsed)
        
        logger.info("Sleeping %ds...", int(to_sleep))
        time.sleep(to_sleep)

if __name__ == "__main__":
    main()
