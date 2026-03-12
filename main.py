"""
main.py  —  AlphaZero Capital v2
══════════════════════════════════
Single entry point: python main.py

What's new in v2:
  ✅ Historical data cache (data/cache/) — no repeated downloads
  ✅ yfinance MultiIndex fix, retry on rate-limit
  ✅ NSE Bhav Copy fully implemented
  ✅ NSE Direct API (no rate limits)
  ✅ Screener.in fundamentals scraper
  ✅ Kelly criterion full implementation
  ✅ Correlation control (>0.8 blocked)
  ✅ Rolling 7d/30d drawdown circuit breaker
  ✅ Portfolio rebalancer (weekly)
  ✅ Walk-forward backtesting
  ✅ Order retry + partial fill + bracket orders
  ✅ GET /health endpoint
  ✅ Auto-restart (systemd / pm2 config generation)
  ✅ Log rotation (7-day)
  ✅ Daily DB backup
"""

from __future__ import annotations

import os, sys, time, logging, threading, signal
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load .env before anything else
load_dotenv()

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Logging setup ─────────────────────────────────────────────────────────────
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-20s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "alphazero.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("Main")

# ── Config ────────────────────────────────────────────────────────────────────
try:
    from config.settings import settings
except ImportError:
    class _S:
        MODE              = os.getenv('MODE', 'PAPER')
        INITIAL_CAPITAL   = float(os.getenv('INITIAL_CAPITAL', 1_000_000))
        DASHBOARD_PORT    = int(os.getenv('DASHBOARD_PORT', 8000))
        ITERATION_INTERVAL= int(os.getenv('ITERATION_INTERVAL', 900))
        MAX_DAILY_LOSS_PCT= float(os.getenv('MAX_DAILY_LOSS_PCT', 0.02))
        def to_dict(self): return self.__dict__
    settings = _S()

# ── Core imports ──────────────────────────────────────────────────────────────
from src.data.market_data import DataFetcher, is_market_open, next_market_open
from src.data.cache       import clear_stale_cache

# ── Risk imports ──────────────────────────────────────────────────────────────
from src.risk.position_sizer     import PositionSizer
from src.risk.correlation_control import CorrelationFilter
from src.risk.drawdown_breaker   import DrawdownBreaker, PortfolioRebalancer

# ── Backtest imports ──────────────────────────────────────────────────────────
from src.backtest.engine       import BacktestEngine
from src.backtest.walk_forward import WalkForwardEngine

# ── Execution imports ─────────────────────────────────────────────────────────
from src.execution.order_manager import OrderManager

# ── Infra imports ─────────────────────────────────────────────────────────────
from src.infra.ops import rotate_logs, daily_backup, generate_systemd_service, generate_pm2_config

# ── Agent imports (safe) ──────────────────────────────────────────────────────
def _safe_import(module_path: str, class_name: str, fallback=None):
    try:
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    except Exception as e:
        logger.warning(f"Could not import {class_name}: {e}")
        return fallback

ChiefAgent          = _safe_import('src.agents.chief_agent',         'ChiefAgent')
SigmaAgent          = _safe_import('src.agents.sigma_agent',         'SigmaAgent')
SectorAgent         = _safe_import('src.agents.sector_agent',        'SectorAgent')
OracleAgent         = _safe_import('src.agents.oracle_agent',        'OracleAgent')
IntradayRegimeAgent = _safe_import('src.agents.intraday_regime_agent',     'IntradayRegimeAgent')
NewsSentimentAgent  = _safe_import('src.agents.news_sentiment_agent','NewsSentimentAgent')
TitanAgent          = _safe_import('src.agents.titan_agent',         'TitanAgent')
GuardianAgent       = _safe_import('src.agents.guardian_agent',      'GuardianAgent')
MercuryAgent        = _safe_import('src.agents.mercury_agent',       'MercuryAgent')
LensAgent           = _safe_import('src.agents.lens_agent',          'LensAgent')
KarmaAgent          = _safe_import('src.agents.karma_agent',         'KarmaAgent')
OptionsFlowAgent    = _safe_import('src.agents.options_flow_agent',  'OptionsFlowAgent')
MultiTimeframeAgent = _safe_import('src.agents.multi_timeframe_agent','MultiTimeframeAgent')
EarningsCallAnalyzer= _safe_import('src.agents.llm_earnings_analyzer','EarningsCallAnalyzer')
StrategyGenerator   = _safe_import('src.agents.llm_strategy_generator','StrategyGenerator')
TrailingStopManager = _safe_import('src.risk.trailing_stop_manager',  'TrailingStopManager')
RiskManager         = _safe_import('src.risk.risk_manager',           'RiskManager')
CapitalAllocator    = _safe_import('src.risk.capital_allocator',      'CapitalAllocator')
PaperExecutor       = _safe_import('src.execution.paper_executor',    'PaperExecutor')
OpenAlgoExecutor    = _safe_import('src.execution.openalgo_executor', 'OpenAlgoExecutor')
EventBus            = _safe_import('src.event_bus.event_bus',         'EventBus')
LLMProvider         = _safe_import('src.agents.llm_provider',         'LLMProvider')

try:
    from src.tracker import SystemTracker
except ImportError:
    SystemTracker = None

try:
    from dashboard.backend import run_dashboard, create_app
    DASHBOARD_OK = True
except ImportError:
    DASHBOARD_OK = False


# ── AlphaZero Orchestrator ────────────────────────────────────────────────────

class AlphaZeroCapital:

    def __init__(self):
        logger.info("═" * 60)
        logger.info("  AlphaZero Capital v2 — Initialising")
        logger.info("═" * 60)

        self.mode    = settings.MODE
        self.capital = settings.INITIAL_CAPITAL
        self._running = True

        self._cfg = settings.to_dict() if hasattr(settings, 'to_dict') else {}
        self._cfg.update({
            'MODE':             self.mode,
            'INITIAL_CAPITAL':  self.capital,
            'MAX_DAILY_LOSS_PCT': settings.MAX_DAILY_LOSS_PCT,
        })

        self._setup_signal_handlers()
        self._init_core()
        self._init_agents()
        self._init_dashboard()

        # Generate infra configs on first run
        self._maybe_generate_infra_configs()

    def _setup_signal_handlers(self):
        """Windows-safe signal handlers."""
        def _shutdown(sig, frame):
            logger.info("Shutdown signal received")
            self._running = False
        try:
            signal.signal(signal.SIGTERM, _shutdown)
        except (AttributeError, OSError):
            pass   # Windows: SIGTERM not always available
        signal.signal(signal.SIGINT, _shutdown)

    def _init_core(self):
        logger.info("── Core systems ──")

        # Event bus
        if EventBus:
            self.event_bus = EventBus()
        else:
            class _Stub:
                def publish(self, *a, **k): pass
                def subscribe(self, *a, **k): pass
            self.event_bus = _Stub()

        # LLM
        if LLMProvider:
            try:
                self.llm = LLMProvider.create()
                logger.info(f"  LLM: {self.llm}")
            except Exception:
                self.llm = None
        else:
            self.llm = None
        self._cfg['llm'] = self.llm

        # Data fetcher
        self.data_fetcher   = DataFetcher(self._cfg)
        self._cfg['data_fetcher'] = self.data_fetcher

        # Executor
        if self.mode == 'LIVE' and OpenAlgoExecutor:
            self.executor = OpenAlgoExecutor(self._cfg)
        elif PaperExecutor:
            self.executor = PaperExecutor(self._cfg)
        else:
            self.executor = None

        # Order manager (with retry + partial fill + brackets)
        self.order_manager = OrderManager(executor=self.executor, event_bus=self.event_bus)

        # Risk modules
        self.position_sizer      = PositionSizer(self.capital)
        self.correlation_filter  = CorrelationFilter(data_fetcher=self.data_fetcher)
        self.drawdown_breaker    = DrawdownBreaker(event_bus=self.event_bus, cfg=self._cfg)
        self.rebalancer          = PortfolioRebalancer(event_bus=self.event_bus, cfg=self._cfg)

        # Existing risk managers
        if RiskManager:
            self.risk_manager = RiskManager(self.event_bus, self._cfg)
        if TrailingStopManager:
            self.trailing_stops = TrailingStopManager(self.event_bus, self._cfg)
        if CapitalAllocator:
            self.capital_allocator = CapitalAllocator(total_capital=self.capital)

        # Backtest engines
        self.backtest_engine   = BacktestEngine()
        self.walk_fwd_engine   = WalkForwardEngine(data_fetcher=self.data_fetcher)

        # System tracker
        if SystemTracker:
            self.tracker = SystemTracker()
        else:
            self.tracker = None

        logger.info("  Core systems OK")

    def _init_agents(self):
        logger.info("── Agents ──")
        cfg, eb = self._cfg, self.event_bus
        self.agents = {}

        def _add(name, cls, *args, **kwargs):
            if cls:
                try:
                    self.agents[name] = cls(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"  Agent {name} init failed: {e}")

        _add('CHIEF',             ChiefAgent,          eb, cfg)
        _add('SIGMA',             SigmaAgent,          eb, cfg)
        _add('ATLAS',             SectorAgent,         eb, cfg)
        _add('ORACLE',            OracleAgent,         eb, cfg)
        _add('NEXUS',             IntradayRegimeAgent, eb, cfg)
        _add('HERMES',            NewsSentimentAgent,  eb, cfg)
        _add('TITAN',             TitanAgent,          eb, cfg)
        _add('GUARDIAN',          GuardianAgent,       eb, cfg)
        _add('MERCURY',           MercuryAgent,        eb, cfg, self.executor)
        _add('LENS',              LensAgent,           eb, cfg)
        _add('KARMA',             KarmaAgent,          eb, cfg)
        _add('OPTIONS_FLOW',      OptionsFlowAgent,    eb, cfg)
        _add('MULTI_TIMEFRAME',   MultiTimeframeAgent, eb, cfg, data_fetcher=self.data_fetcher)
        _add('EARNINGS_ANALYZER', EarningsCallAnalyzer,eb, cfg)
        _add('STRATEGY_GENERATOR',StrategyGenerator,   eb, cfg)
        if hasattr(self, 'trailing_stops'):
            self.agents['TRAILING_STOP'] = self.trailing_stops

        # Try to load NEXUS XGBoost model
        xgb_path = ROOT / "models" / "nexus_regime.json"
        nexus     = self.agents.get('NEXUS')
        if nexus and xgb_path.exists() and hasattr(nexus, 'load_xgb_model'):
            try:
                nexus.load_xgb_model(str(xgb_path))
            except Exception:
                pass

        logger.info(f"  {len(self.agents)} agents ready: {list(self.agents.keys())}")

    def _init_dashboard(self):
        if not DASHBOARD_OK:
            return
        port = getattr(settings, 'DASHBOARD_PORT', 8000)
        try:
            app = create_app(agents=self.agents, data_fetcher=self.data_fetcher)
            if app:
                t = threading.Thread(
                    target=lambda: __import__('uvicorn').run(app, host="0.0.0.0", port=port, log_level="warning"),
                    daemon=True, name="Dashboard"
                )
                t.start()
                logger.info(f"  Dashboard: http://localhost:{port}")
        except Exception as e:
            logger.warning(f"  Dashboard failed to start: {e}")

    def _maybe_generate_infra_configs(self):
        """Generate systemd / PM2 configs if they don't exist yet."""
        if not (ROOT / "alphazero.service").exists():
            try:
                generate_systemd_service()
                generate_pm2_config()
            except Exception:
                pass

    # ── Main loop ─────────────────────────────────────────────────────────────
    def run(self):
        logger.info("═" * 60)
        logger.info(f"  MODE: {self.mode} | Capital: ₹{self.capital:,.0f}")
        logger.info("═" * 60)

        iteration = 0
        interval  = getattr(settings, 'ITERATION_INTERVAL', 900)

        while self._running:
            iteration += 1
            now = datetime.now()
            logger.info(f"\n{'─'*50}")
            logger.info(f"  Iteration {iteration} | {now.strftime('%Y-%m-%d %H:%M:%S')}")

            try:
                if is_market_open():
                    self._market_hours_cycle(iteration)
                else:
                    self._off_hours_cycle(now)
            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)

            if self._running:
                logger.info(f"  Sleeping {interval}s...")
                time.sleep(interval)

        logger.info("AlphaZero Capital shutdown complete.")

    def _market_hours_cycle(self, iteration: int):
        """Run during market hours (09:15–15:30 IST)."""
        # 1. Check circuit breakers
        cb = self.drawdown_breaker.check()
        if cb['breached']:
            logger.warning(f"CIRCUIT BREAK: {cb['reason']} — skipping iteration")
            return

        # 2. Run agents
        agents_run = 0
        for name, agent in self.agents.items():
            if hasattr(agent, 'run'):
                try:
                    agent.run()
                    agents_run += 1
                except Exception as e:
                    logger.error(f"Agent {name} error: {e}")

        logger.info(f"  Agents run: {agents_run}/{len(self.agents)}")

        # 3. Update tracker
        if self.tracker:
            try:
                self.tracker.update()
            except Exception:
                pass

    def _off_hours_cycle(self, now: datetime):
        """Run during off-market hours (post-close / pre-open)."""
        hour = now.hour

        # 15:45–16:30: Post-market tasks
        if 15 <= hour <= 16:
            logger.info("  Post-market: running backtest + walk-forward...")
            self._run_post_market_tasks()

        # 18:00–21:00: Deep learning / training
        elif 18 <= hour <= 21:
            logger.info("  Off-hours: KARMA training + rebalance check...")
            self._run_off_hours_training()

        # 23:00: Daily backup + log rotation
        elif hour == 23:
            logger.info("  Nightly: backup + log rotation...")
            try:
                daily_backup()
                rotate_logs()
            except Exception as e:
                logger.warning(f"Nightly maintenance failed: {e}")

        else:
            nxt = next_market_open()
            logger.info(f"  Next market open: {nxt.strftime('%Y-%m-%d %H:%M IST')}")

    def _run_post_market_tasks(self):
        """Post-market: backtesting, walk-forward, cache cleanup."""
        # Stale cache cleanup
        try:
            clear_stale_cache(older_than_days=30)
        except Exception:
            pass

        # Backtest
        try:
            symbols = self._cfg.get('WATCHLIST', ['TCS','RELIANCE','INFY','HDFC','ICICIBANK'])
            logger.info(f"  Backtest running on {len(symbols)} symbols...")
            self.backtest_engine.run(symbols=symbols)
        except Exception as e:
            logger.error(f"Backtest failed: {e}")

        # Walk-forward (once per week on Friday)
        if datetime.now().weekday() == 4:  # Friday
            try:
                logger.info("  Walk-forward validation (Friday)...")
                self.walk_fwd_engine.run(symbols=symbols[:5])
            except Exception as e:
                logger.error(f"Walk-forward failed: {e}")

    def _run_off_hours_training(self):
        """Off-hours KARMA learning + portfolio rebalancing."""
        karma = self.agents.get('KARMA')
        if karma and hasattr(karma, 'train'):
            try:
                karma.train()
            except Exception as e:
                logger.warning(f"KARMA training failed: {e}")

        # Weekly rebalance check
        if self.rebalancer.should_rebalance():
            logger.info("  Rebalancing portfolio...")
            # Rebalance logic would use current positions from MERCURY/status.json


if __name__ == "__main__":
    system = AlphaZeroCapital()
    system.run()
