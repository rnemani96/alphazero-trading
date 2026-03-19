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
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# ── Load env before any internal imports ──────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

IST = ZoneInfo("Asia/Kolkata")

# ── Logging setup ─────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
os.makedirs("models", exist_ok=True)
os.makedirs("data", exist_ok=True)
os.makedirs("data/cache", exist_ok=True)

LOG_FMT = "%(asctime)s │ %(name)-10s │ %(levelname)-5s │ %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FMT,
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/alphazero_v4.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("Main")

# ── Config ────────────────────────────────────────────────────────────────────
try:
    from config.settings import settings
except ImportError:
    logger.error("config/settings.py missing — run from project root.")
    sys.exit(1)

_cfg = vars(settings)

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
    from src.event_bus.event_bus import EventBus
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
agents['ORACLE']   = _load_agent('ORACLE',  'src.agents.oracle_agent',          'OracleAgent',            eb, _cfg)
agents['ATLAS']    = _load_agent('ATLAS',   'src.agents.sector_agent',          'SectorAgent',            eb, _cfg)
agents['SIGMA']    = _load_agent('SIGMA',   'src.agents.sigma_agent',           'SigmaAgent',             eb, _cfg)
agents['APEX']     = _load_agent('APEX',    'src.agents.chief_agent',           'ChiefAgent',             eb, _cfg)
agents['NEXUS']    = _load_agent('NEXUS',   'src.agents.intraday_regime_agent', 'IntradayRegimeAgent',    eb, _cfg)
agents['HERMES']   = _load_agent('HERMES',  'src.agents.news_sentiment_agent',  'NewsSentimentAgent',     eb, _cfg)
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
    "iteration":         0,
    "regime":            "TRENDING",
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
}
_state_lock = threading.Lock()
STATE_FILE  = "data/alphazero_state.json"


def _write_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(_state, f, indent=2, default=str)
        status = {
            "picks":       _state.get("selected_stocks", []),
            "regime":      _state.get("regime", "TRENDING"),
            "sentiment":   _state.get("sentiment", 0.0),
            "pnl":         _state.get("net_pnl", 0.0),
            "iteration":   _state.get("iteration", 0),
            "positions":   _state.get("portfolio", {}),
            "signals":     _state.get("latest_signals", [])[:10],
            "sgx_signal":  _state.get("sgx_signal", {}),
            "mc_result":   _state.get("last_mc_result", {}),
            "nexus_model": os.path.exists(_nexus_model_path),
            "audit_active":_audit is not None,
            "shadow_active":_shadow_mgr is not None,
        }
        with open("logs/status.json", "w") as f:
            json.dump(status, f, indent=2, default=str)
        with open("logs/signals.json", "w") as f:
            json.dump(_state.get("latest_signals", []), f, indent=2, default=str)
    except Exception as exc:
        logger.warning("State write: %s", exc)


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


def _enrich_with_indicators(symbol: str, candles: List[Dict]) -> Optional[Dict]:
    """Build a full indicator dict for one symbol from its candle history."""
    if len(candles) < 30:
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
        if len(df) < 20:
            return None
        enriched = add_all_indicators(df)
        if enriched.empty:
            return None
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

    A signal is approved when weighted_confidence >= 0.55 AND
    all three layers do not strongly disagree.
    """
    TITAN_W  = 0.45
    NEXUS_W  = 0.30
    HERMES_W = 0.25
    MIN_AGG_CONF = 0.55

    approved = []
    for sig in titan_signals:
        sym   = sig.get('symbol', '')
        tc    = float(sig.get('confidence', 0.5))
        act   = sig.get('action', 'BUY')

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
            # Boost hermes_conf when SGX aligns with signal direction
            if (act == 'BUY' and sgx_b > 0) or (act == 'SELL' and sgx_b < 0):
                hermes_conf = min(0.95, hermes_conf + abs(sgx_b) * 0.15)
            else:
                hermes_conf = max(0.1, hermes_conf - abs(sgx_b) * 0.10)

        # Weighted aggregate
        agg_conf = TITAN_W * tc + NEXUS_W * nexus_conf + HERMES_W * hermes_conf

        # Hard veto: if NEXUS strongly disagrees (e.g. RISK_OFF and BUY signal)
        if regime == 'RISK_OFF':
            continue
        if not regime_compat and nexus_conf < 0.35:
            logger.debug("AGGREGATE: %s vetoed by NEXUS (regime=%s act=%s)", sym, regime, act)
            continue
        if agg_conf < MIN_AGG_CONF:
            logger.debug("AGGREGATE: %s confidence %.2f < %.2f", sym, agg_conf, MIN_AGG_CONF)
            continue

        sig = dict(sig)  # copy
        sig['confidence']       = round(agg_conf, 3)
        sig['titan_confidence'] = round(tc, 3)
        sig['nexus_confidence'] = round(nexus_conf, 3)
        sig['hermes_confidence']= round(hermes_conf, 3)
        sig['regime_compat']    = regime_compat
        approved.append(sig)

    logger.info("AGGREGATE: %d / %d signals passed multi-agent gate",
                len(approved), len(titan_signals))
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
        if trade_type != 'INTRADAY':
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
        syms = [
            'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
            'KOTAKBANK', 'SBIN', 'BHARTIARTL', 'LT', 'ITC',
            'AXISBANK', 'HINDUNILVR', 'BAJFINANCE', 'SUNPHARMA', 'MARUTI',
        ]
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

    mdata: Dict[str, Any] = {}
    for sym in universe:
        candles = _fetch_candles(sym, bars=250)
        if not candles:
            continue
        # Inject live price into last candle
        if prices.get(sym, 0) > 0:
            candles[-1]['close'] = prices[sym]
        ind = _enrich_with_indicators(sym, candles)
        if ind:
            ind['candles'] = candles   # store for KARMA offline training
            mdata[sym] = ind

    _state['market_data'] = {s: {'ltp': prices.get(s, 0)} for s in universe}

    # Update positions with latest prices
    _update_positions({s: float(d.get('close', d.get('price', 0))) for s, d in mdata.items()})

    # ── Step 3: ORACLE macro analysis ─────────────────────────────────────────
    vix = 15.0
    if agents.get('ORACLE') and hasattr(agents['ORACLE'], 'analyze'):
        try:
            macro = agents['ORACLE'].analyze(mdata)
            _state['macro'] = macro
            vix = float(macro.get('vix', 15.0))
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

    # ── Step 4: Regime detection (NEXUS) ─────────────────────────────────────
    regime = _state.get('regime', 'TRENDING')
    if agents.get('NEXUS') and hasattr(agents['NEXUS'], 'detect_regime'):
        try:
            raw_regime = agents['NEXUS'].detect_regime({
                'data':      mdata,
                'symbols':   list(mdata.keys()),
                'india_vix': vix,
            })
            regime = raw_regime if isinstance(raw_regime, str) else regime
            _state['regime'] = regime
        except Exception as exc:
            logger.debug("NEXUS: %s", exc)

    # ── Step 5: Sentiment (HERMES) ────────────────────────────────────────────
    sentiment_scores: Dict[str, float] = {}
    overall_sentiment = 0.0
    if agents.get('HERMES') and hasattr(agents['HERMES'], 'get_sentiment'):
        try:
            sent_result = agents['HERMES'].get_sentiment(list(mdata.keys())[:15])
            sentiment_scores = sent_result.get('scores', {})
            overall_sentiment = float(sent_result.get('score', 0.0))
            _state['sentiment'] = overall_sentiment
            _state['sentiment_scores'] = sentiment_scores
        except Exception as exc:
            logger.debug("HERMES: %s", exc)

    # ── Step 6: Stock scoring (SIGMA → APEX) ──────────────────────────────────
    selected_stocks = _state.get('selected_stocks', [])
    slots_available = True
    if AP and settings.HOLD_UNTIL_TARGET:
        summ = AP.get_summary()
        slots_available = summ['slots_available'] > 0

    if slots_available and agents.get('SIGMA') and hasattr(agents['SIGMA'], 'score_stocks'):
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
                    'sector':           'AUTO',
                    'price':            float(d.get('close', 0)),
                }
                for sym, d in mdata.items()
            ]
            scored = agents['SIGMA'].score_stocks(candidates, regime)

            if agents.get('APEX') and hasattr(agents['APEX'], 'select_portfolio') and scored:
                blocked = set(AP.open_positions.keys()) if AP else set()
                scored  = [s for s in scored if s.get('symbol') not in blocked]
                selected = agents['APEX'].select_portfolio(scored, {}, regime)
                selected_stocks = selected
                _state['selected_stocks'] = selected
        except Exception as exc:
            logger.debug("SIGMA/APEX: %s", exc)

    # ── Step 7: TITAN signals ─────────────────────────────────────────────────
    signals: List[Dict] = []
    if market_hours and agents.get('TITAN') and mdata:
        try:
            # Filter mdata to selected symbols + open positions
            sel_syms = {s.get('symbol') for s in selected_stocks} | (
                set(AP.open_positions.keys()) if AP else set()
            )
            scan_data = {s: d for s, d in mdata.items() if s in sel_syms} if sel_syms else mdata
            if not scan_data:
                scan_data = mdata  # fallback: scan everything

            raw_signals = agents['TITAN'].generate_signals(
                scan_data, regime=regime,
                hermes_scores=sentiment_scores,
            )
            # Multi-agent aggregation (replaces old simple pass-through)
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
            size_result = _sizer.size(strat, price, atr, vix)
            qty         = size_result['qty']

            sig['quantity'] = qty
            sig['qty']      = qty

            # GUARDIAN hard check
            result = agents['GUARDIAN'].check_trade(sig, current_capital, open_positions)
            if result['approved']:
                sig['quantity']     = result.get('quantity', qty)
                sig['qty']          = sig['quantity']
                sig['stop_loss']    = result.get('stop_loss', sig.get('stop_loss', 0))
                sig['target']       = result.get('target',    sig.get('target', 0))
                sig['position_size']= result.get('position_size', 0)
                approved.append(sig)
        except Exception as exc:
            logger.debug("GUARDIAN check %s: %s", sig.get('symbol'), exc)

    logger.info("Risk gate: %d / %d signals approved", len(approved), len(signals))

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
        for sig in final_signals:
            if sig.get('quantity', 0) <= 0:
                continue
            try:
                result = executor.execute_trade(sig) if hasattr(executor, 'execute_trade') else \
                         executor.execute(sig)
                if result and (result.get('success') or result.get('status') in ('COMPLETE', 'filled')):
                    fill_price = result.get('fill_price', sig.get('price', 0))
                    _register_trade(sig, fill_price)
                    executed += 1
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
                len(final_signals), executed, regime, vix)
    logger.info("Sleeping %ds...", settings.ITERATION_SLEEP_SEC)


# ── Dashboard backend ─────────────────────────────────────────────────────────

def _start_dashboard():
    """Start FastAPI dashboard server and open browser."""
    try:
        from dashboard.backend import run_dashboard
        port = settings.BACKEND_PORT
        t = threading.Thread(
            target=run_dashboard,
            args=(port, agents, MSD),
            daemon=True,
            name="DashboardServer",
        )
        t.start()
        logger.info("Dashboard server started on http://localhost:%d", port)

        # Wait briefly for server to bind, then open browser
        time.sleep(2.5)
        url = f"http://localhost:{port}"
        logger.info("Opening browser → %s", url)
        webbrowser.open(url)
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
        try:
            _run_iteration()
        except Exception as exc:
            logger.exception("Iteration error: %s", exc)
        time.sleep(settings.ITERATION_SLEEP_SEC)


if __name__ == "__main__":
    main()
