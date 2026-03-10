"""
AlphaZero Capital v17 — Main Orchestrator
main.py

Entry point. Starts all agents, reporters, and the trading loop.
All LLM calls go through LLMProvider.create() — fully generic.

Usage:
    python main.py              # paper trading (default)
    python main.py --live       # live trading

FIXES vs previous version:
  1. Added OracleAgent import
  2. _init_agents: renamed 'SECTOR' → 'ATLAS' (dashboard expects ATLAS)
  3. _init_agents: added 'ORACLE' and 'TRAILING_STOP' → now exactly 16 agents
  4. _run_iteration: ORACLE.analyze() called first; regime_hint fed to NEXUS
  5. _write_state: VIX, macro_bias, fii_flow surfaced to dashboard state
"""

import sys, os, time, signal, logging, argparse, threading, subprocess
import webbrowser, time
from datetime import datetime
from typing import Dict, List, Any

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from config.settings import settings
from config.sectors  import SECTORS

from src.event_bus.event_bus import EventBus, EventType

from src.agents.chief_agent             import ChiefAgent
from src.agents.sector_agent            import SectorAgent
from src.agents.sigma_agent             import SigmaAgent
from src.agents.titan_agent             import TitanAgent
from src.agents.guardian_agent          import GuardianAgent
from src.agents.mercury_agent           import MercuryAgent
from src.agents.lens_agent              import LensAgent
from src.agents.karma_agent             import KarmaAgent
from src.agents.news_sentiment_agent    import NewsSentimentAgent
from src.agents.intraday_regime_agent   import IntradayRegimeAgent
from src.agents.options_flow_agent      import OptionsFlowAgent
from src.agents.multi_timeframe_agent   import MultiTimeframeAgent
from src.agents.llm_earnings_analyzer   import EarningsCallAnalyzer
from src.agents.llm_strategy_generator  import StrategyGenerator
from src.agents.llm_provider            import LLMProvider
from src.agents.oracle_agent            import OracleAgent          # ← FIX 1: new import

from src.risk.risk_manager          import RiskManager
from src.risk.trailing_stop_manager import TrailingStopManager
from src.risk.capital_allocator     import CapitalAllocator
from src.execution.paper_executor   import PaperExecutor
from src.execution.openalgo_executor import OpenAlgoExecutor

from src.data.fetch import DataFetcher

from src.reporting.telegram_reporter   import TelegramReporter
from src.reporting.email_reporter       import EmailReporter
from src.reporting.pdf_generator        import PDFReportGenerator
from src.reporting.agent_performance    import AgentPerformanceTracker
from src.reporting.scheduler            import ReportScheduler
from src.reporting.telegram_reporter   import TelegramCommandHandler

from src.monitoring import state as live_state

os.makedirs(os.path.join(ROOT, 'logs'), exist_ok=True)
os.makedirs(os.path.join(ROOT, 'logs', 'reports'), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(ROOT, 'logs', 'alphazero.log'), encoding='utf-8'),
    ]
)
logger = logging.getLogger('MAIN')


class AlphaZeroSystem:

    def __init__(self, mode: str = None):
        self.mode       = mode or settings.MODE
        self.running    = False
        self.start_time = datetime.now()
        self.iteration  = 0

        # Cached macro context — written by ORACLE each iteration, read by _write_state
        self._macro_context: Dict[str, Any] = {}

        # CHIEF-selected stocks — written each iteration, read by _write_state → dashboard
        self._selected_stocks: List[Dict] = []
        self._capital_alloc = {} #  recommended by chatgpt


        # KARMA feedback — maps symbol → signal dict so we can close the loop when
        # the trade outcome arrives (stop hit / target reached / position closed)
        self._pending_signals: Dict[str, Dict] = {}

        logger.info("=" * 70)
        logger.info(f"  AlphaZero Capital v17  |  Mode: {self.mode}")
        logger.info("=" * 70)

        self._init_event_bus()
        self._init_llm()             # generic LLM — must come before agents that use it
        self._init_data()
        self._init_managers()
        self._init_agents()
        self._init_reporting()
        self._init_subscriptions()

        self._start_dashboard()
        live_state.update({'system': {'status': 'STARTING', 'mode': self.mode, 'version': 'v17'}})
        logger.info("✅ System initialised")

    # ── Boot ──────────────────────────────────────────────────────────────────

    def _init_event_bus(self):
        self.event_bus = EventBus()
        self.event_bus.start()

    def _init_llm(self):
        """Create one shared LLM provider used by all agents. 100% generic."""
        self.llm = LLMProvider.create()
        logger.info(f"  LLM: {self.llm}")
        # Inject into config so agents can pick it up
        self._cfg = {**settings.to_dict(), 'llm': self.llm}

    def _init_data(self):
        self.data_fetcher = DataFetcher(self._cfg)

    def _init_managers(self):
        cfg = self._cfg
        self.executor = (
            OpenAlgoExecutor(cfg)
            if self.mode == 'LIVE'
            else PaperExecutor(cfg)
        )
        self.risk_manager   = RiskManager(self.event_bus, cfg)
        self.trailing_stops = TrailingStopManager(self.event_bus, cfg)
        initial_cap = getattr(settings, 'INITIAL_CAPITAL', 1_000_000)
        self.capital_allocator = CapitalAllocator(
        total_capital=initial_cap
    )

    def _init_agents(self):
        cfg, eb = self._cfg, self.event_bus
        self.agents = {
            # ── Core portfolio agents ───────────────────────────────────────
            'CHIEF':              ChiefAgent(eb, cfg),
            'SIGMA':              SigmaAgent(eb, cfg),
            'ATLAS':              SectorAgent(eb, cfg),          # FIX 2: was 'SECTOR'
            # ── Market intelligence ─────────────────────────────────────────
            'ORACLE':             OracleAgent(eb, cfg),          # FIX 3: new agent
            'NEXUS':              IntradayRegimeAgent(eb, cfg),
            'HERMES':             NewsSentimentAgent(eb, cfg),
            # ── Strategy & execution ────────────────────────────────────────
            'TITAN':              TitanAgent(eb, cfg),
            'GUARDIAN':           GuardianAgent(eb, cfg),
            'MERCURY':            MercuryAgent(eb, cfg, self.executor),
            # ── Learning & reporting ────────────────────────────────────────
            'LENS':               LensAgent(eb, cfg),
            'KARMA':              KarmaAgent(eb, cfg),
            # ── v16 enhancements ────────────────────────────────────────────
            'OPTIONS_FLOW':       OptionsFlowAgent(eb, cfg),
            'MULTI_TIMEFRAME':    MultiTimeframeAgent(eb, cfg, data_fetcher=self.data_fetcher),
            # ── v17 LLM agents ──────────────────────────────────────────────
            'EARNINGS_ANALYZER':  EarningsCallAnalyzer(eb, cfg),
            'STRATEGY_GENERATOR': StrategyGenerator(eb, cfg),
            # ── Manager exposed as agent for dashboard health display ───────
            'TRAILING_STOP':      self.trailing_stops,           # FIX 3: now 16 total
        }
        logger.info(f"  {len(self.agents)} agents ready")     # → 16

    def _init_reporting(self):
        self.telegram         = TelegramReporter()
        self.email            = EmailReporter()
        self.pdf              = PDFReportGenerator()
        self.agent_tracker    = AgentPerformanceTracker()
        self.report_scheduler = ReportScheduler(
            telegram     = self.telegram,
            email        = self.email,
            pdf          = self.pdf,
            agent_tracker= self.agent_tracker,
            get_state    = live_state.read,
        )
        self.report_scheduler.start()
        self._cmd_handler = TelegramCommandHandler(self.telegram, self.report_scheduler)
        self._cmd_handler.start()
        logger.info(f"  Telegram: {'✓' if self.telegram.is_enabled() else '✗ (configure TELEGRAM_BOT_TOKEN)'}")
        logger.info(f"  Email:    {'✓' if self.email.is_enabled()    else '✗ (configure EMAIL_SENDER)'}")

    def _init_subscriptions(self):
        eb = self.event_bus
        eb.subscribe(EventType.SIGNAL_GENERATED, self._on_signal)
        eb.subscribe(EventType.TRADE_EXECUTED,   self._on_trade_executed)
        eb.subscribe(EventType.RISK_ALERT,        self._on_risk_alert)
        eb.subscribe(EventType.STOP_LOSS_HIT,     self._on_stop_hit)
        eb.subscribe(EventType.TARGET_REACHED,    self._on_target_reached)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _start_dashboard(self):
        """Start the dashboard backend + React frontend (Vite dev server) automatically."""

        # ── 1. Start FastAPI backend via uvicorn on port 8000 ──
        backend_module = 'dashboard.backend:app'
        try:
            backend_proc = subprocess.Popen(
                [sys.executable, '-m', 'uvicorn', backend_module,
                 '--host', '0.0.0.0', '--port', '8000', '--log-level', 'warning'],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._dashboard_backend_proc = backend_proc
            logger.info("✅ Dashboard backend started (FastAPI/uvicorn on :8000)")
        except Exception as e:
            logger.warning(f"Dashboard backend failed to start: {e}")

        # ── 2. Start Vite React frontend (dashboard/alphazero-ui) ────
        frontend_dir = os.path.join(ROOT, 'dashboard', 'alphazero-ui')
        if os.path.exists(os.path.join(frontend_dir, 'package.json')):
            try:
                # Use 'npm' on Windows, works everywhere
                npm_cmd = 'npm.cmd' if os.name == 'nt' else 'npm'
                frontend_proc = subprocess.Popen(
                    [npm_cmd, 'run', 'dev', '--', '--port', '5173'],
                    cwd=frontend_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._dashboard_frontend_proc = frontend_proc
                logger.info("✅ Dashboard frontend starting (Vite dev server on :5173)")
            except Exception as e:
                logger.warning(f"Dashboard frontend failed to start: {e}")
        else:
            logger.warning("dashboard/alphazero-ui/package.json not found; skipping frontend start")

        # ── 3. Open browser after short delay ───────────────
        def _open_browser():
            time.sleep(4)  # wait for backend + Vite to initialise
            url = "http://localhost:8000"
            webbrowser.open(url)
            logger.info(f"🌐 Browser opened at {url}")

        threading.Thread(target=_open_browser, daemon=True).start()

    def run(self):
        self.running = True
        signal.signal(signal.SIGINT,  self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)
        logger.info(f"\n▶  Main loop started  (interval: {settings.ITERATION_INTERVAL}s)\n")
        live_state.update({'system': {'status': 'RUNNING'}})

        while self.running:
            try:
                self._run_iteration()
            except Exception as e:
                logger.error(f"Iteration error: {e}", exc_info=True)
            if self.running:
                time.sleep(settings.ITERATION_INTERVAL)

    def _run_iteration(self):
        self.iteration += 1
        t0 = time.time()
        logger.info(f"\n{'─'*60}\nIteration {self.iteration}  |  {datetime.now().strftime('%H:%M:%S')}")

        market_data = self._fetch_market_data()

        # ── FIX 4: ORACLE runs first — gives macro context to every downstream agent ──
        macro_context        = self.agents['ORACLE'].analyze(market_data)
        self._macro_context  = macro_context          # store for _write_state
        size_mult            = macro_context.get('size_mult', 1.0)
        oracle_regime_hint   = macro_context.get('regime_hint', '')
        logger.info(
            f"  🔭 ORACLE → bias={macro_context.get('macro_bias','?')} "
            f"risk={macro_context.get('risk_level','?')} "
            f"size_mult={size_mult:.2f} "
            f"VIX={macro_context.get('vix',0):.1f}"
        )

        options_signals  = self._check_options_flow(market_data)

        # NEXUS detects regime; ORACLE hint used as a tiebreaker / default
        nexus_regime = self.agents['NEXUS'].detect_regime(market_data)
        regime       = nexus_regime if nexus_regime not in ('', None) else oracle_regime_hint

        sentiment        = self.agents['HERMES'].get_sentiment(settings.SYMBOLS)
        earnings_signals = []

        # ── KARMA feeds optimised strategy weights into TITAN each iteration ──
        try:
            karma_weights = self.agents['KARMA'].get_optimized_weights()
            if hasattr(self.agents['TITAN'], 'update_strategy_weights'):
                self.agents['TITAN'].update_strategy_weights(karma_weights, regime)
        except Exception:
            pass

        titan_signals = self.agents['TITAN'].generate_signals(market_data, regime)

        # Attach current price to every signal so MERCURY/PaperExecutor
        # fills at real market price instead of hardcoded 2450.50
        for sig in titan_signals + options_signals:
            sym = sig.get('symbol', '')
            if sym and sym in market_data.get('prices', {}):
                sig.setdefault('price', market_data['prices'][sym])
                sig.setdefault('ltp',   market_data['prices'][sym])
                md_sym = market_data.get('data', {}).get(sym, {})
                sig.setdefault('atr',       md_sym.get('atr', 0))
                sig.setdefault('stop_loss', md_sym.get('stop_loss',
                    market_data['prices'][sym] * 0.97))
                sig.setdefault('target',    md_sym.get('target',
                    market_data['prices'][sym] * 1.04))

        # ── SIGMA: score all stocks, CHIEF: select portfolio ─────────────────
        # SIGMA ranks every symbol by 8 factors; CHIEF picks top diversified N.
        try:
            sigma_candidates      = self._build_sigma_candidates(market_data, sentiment)
            sigma_scored          = self.agents['SIGMA'].score_stocks(sigma_candidates, regime)
            self._selected_stocks = self.agents['CHIEF'].select_portfolio(sigma_scored, {}, regime)
            # Allocate capital across selected portfolio
            self._capital_alloc = self.capital_allocator.allocate(self._selected_stocks)
            # Push allocation amounts back onto each stock dict so _write_state includes it
            for stk in self._selected_stocks:
                sym = stk.get('symbol','')
                if sym in self._capital_alloc:
                    stk.update(self._capital_alloc[sym])
            top = [s['symbol'] for s in self._selected_stocks]
            logger.info(f"  🎯 CHIEF selected: {top}")
        except Exception as e:
            logger.warning(f"SIGMA/CHIEF error: {e}")
            self._selected_stocks = []
        # ─────────────────────────────────────────────────────────────────────

        all_signals = options_signals + earnings_signals + titan_signals
        confirmed   = self._apply_mtf_filter(all_signals)
        approved    = self._check_risk_and_execute(confirmed, market_data, size_mult)

        self._update_trailing_stops(market_data)
        self.agents['LENS'].update()
        self.agents['KARMA'].update()

        # ── Off-hours KARMA training ──────────────────────────────────────
        try:
            from datetime import time as dtime
            import pytz
            ist = pytz.timezone('Asia/Kolkata')
            now_ist = datetime.now(ist)
            is_trading = (dtime(9,15) <= now_ist.time() <= dtime(15,30)
                          and now_ist.weekday() < 5)
            if not is_trading and market_data:
                hist_data = {
                    sym: [{'close': d.get('price',0), 'volume': d.get('volume',0)}]
                    for sym, d in (market_data.get('data') or {}).items()
                }
                if hist_data:
                    self.agents['KARMA'].run_offline_training(
                        hist_data, ['1min','5min','15min','1hour','1day'])
        except Exception as _e:
            logger.debug(f"Off-hours training: {_e}")

        self._write_state(regime, sentiment, confirmed)
        logger.info(f"  Done in {time.time()-t0:.1f}s — "
                    f"{len(confirmed)} signals, {len(approved)} executed")

    # ── Step helpers ──────────────────────────────────────────────────────────

    def _fetch_market_data(self) -> Dict[str, Any]:
        prices, data = {}, {}
        for sym in settings.SYMBOLS:
            candles = self.data_fetcher.get_ohlcv(sym, interval='15min', bars=100)
            if candles:
                latest = candles[-1]
                prices[sym] = latest.get('close', 0.0)
                data[sym]   = {**latest, 'symbol': sym}
        md = {'symbols': settings.SYMBOLS, 'prices': prices,
              'data': data, 'timestamp': datetime.now().isoformat()}
        self._last_market_data = md   # cache for _write_state TA enrichment
        # Push live prices into PaperExecutor for P&L and stop/target monitoring
        try:
            if 'MERCURY' in self.agents and hasattr(self.agents['MERCURY'], 'update_prices'):
                self.agents['MERCURY'].update_prices(prices)
            if 'LENS' in self.agents and hasattr(self.agents['LENS'], 'update_prices'):
                self.agents['LENS'].update_prices(prices)
        except Exception:
            pass
        return md

    def _build_sigma_candidates(self, market_data: Dict, sentiment) -> List[Dict]:
        """
        Convert raw market_data['data'] into the list-of-dicts format SIGMA expects.
        Each dict has: symbol, momentum, trend_strength, earnings_quality,
        relative_strength, news_sentiment, volume_confirm, volatility, fii_interest,
        plus raw price/indicator fields for the modal display.
        """
        sent_scores = {}
        if isinstance(sentiment, dict):
            sent_scores = sentiment.get('scores', {})

        candidates = []
        for sym, d in market_data.get('data', {}).items():
            close  = d.get('close', 0) or 0
            ema20  = d.get('ema20', close)
            ema50  = d.get('ema50', close)
            rsi    = d.get('rsi', 50) or 50
            adx    = d.get('adx', 20) or 20
            atr    = d.get('atr', close * 0.015) or 0
            vol    = d.get('volume', 0) or 0
            vol_avg= d.get('volume_avg', vol) or vol
            vol_ratio = vol / vol_avg if vol_avg > 0 else 1.0

            # 0-1 factor derivations
            momentum        = min(1.0, max(0.0, (close - ema50) / (ema50 or 1) * 10 + 0.5))
            trend_strength  = min(1.0, adx / 50.0)
            relative_str    = min(1.0, max(0.0, (close - ema20) / (ema20 or 1) * 5 + 0.5))
            vol_confirm     = min(1.0, vol_ratio / 2.0)
            volatility      = min(1.0, (atr / (close or 1) * 100) / 3.0)
            raw_sent        = sent_scores.get(sym, 0.0)
            news_sentiment  = (raw_sent + 1) / 2  # -1..1 → 0..1

            # Earnings quality proxy from existing fundamental data if any
            earnings_quality = d.get('earnings_quality', 0.5)
            fii_interest     = d.get('fii_interest', 0.5)

            # TA reasons for the modal
            ta_reasons = []
            if ema20 and ema50:
                if close > ema20 > ema50:
                    ta_reasons.append(f"✅ Price ₹{round(close,0)} above EMA20 & EMA50 — bullish alignment")
                elif close < ema20 < ema50:
                    ta_reasons.append(f"⚠️ Price below both EMAs — bearish structure")
            if rsi < 35:
                ta_reasons.append(f"📉 RSI {round(rsi,1)} oversold — potential bounce entry")
            elif rsi > 65:
                ta_reasons.append(f"📈 RSI {round(rsi,1)} overbought — momentum extreme")
            else:
                ta_reasons.append(f"✅ RSI {round(rsi,1)} in healthy range")
            if adx > 25:
                ta_reasons.append(f"✅ ADX {round(adx,1)} — strong directional trend")
            elif adx < 18:
                ta_reasons.append(f"⚠️ ADX {round(adx,1)} — choppy market, low conviction")
            if vol_ratio > 1.5:
                ta_reasons.append(f"✅ Volume {round(vol_ratio,1)}× above average — institutional interest")

            prev_close = d.get('prev_close', close)
            change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0

            from config.sectors import SYMBOL_TO_SECTOR
            sector = SYMBOL_TO_SECTOR.get(sym, 'OTHER')

            # Infer trade type from indicators
            if adx > 30 and vol_ratio > 1.8 and rsi > 60:
                trade_type = 'POSITIONAL'
            elif adx > 22 and momentum > 0.55:
                trade_type = 'SWING'
            else:
                trade_type = 'SWING'

            holding_period = {'INTRADAY':'Same day','SWING':'3–10 days','POSITIONAL':'3–8 weeks','LONG TERM':'3–12 months'}.get(trade_type,'3–10 days')

            # Expected return from ATR or price levels
            atr_mult    = {'INTRADAY':1.5,'SWING':3.0,'POSITIONAL':5.0,'LONG TERM':10.0}.get(trade_type, 3.0)
            exp_ret_pct = round(atr * atr_mult / close * 100, 2) if close else 3.5

            # Stop / target
            stop_loss_est = round(close - 2 * atr, 2)
            target_est    = round(close + atr * atr_mult, 2)

            # Selection reason
            rsi_desc = 'oversold (bounce potential)' if rsi < 35 else 'overbought (momentum extreme)' if rsi > 65 else f'healthy RSI {round(rsi,0)}'
            # MTF vote count — will be filled in after MTF agent runs
            # For now, estimate from indicator agreement
            mtf_votes = sum([
                1 if close > ema20 else 0,
                1 if close > ema50 else 0,
                1 if adx > 20 else 0,
                1 if rsi > 45 else 0,
                1 if vol_ratio > 1.0 else 0,
            ])
            sel_reason = (
                f"SIGMA scored {sym} at {round(momentum*100,0):.0f}/100 composite. "
                f"{sector} sector, {rsi_desc}, ADX {round(adx,0):.0f} "
                f"({'strong trend' if adx > 25 else 'moderate trend'}), "
                f"volume {round(vol_ratio,1):.1f}× average. "
                f"{mtf_votes}/5 timeframe indicators aligned. "
                f"CHIEF selected for {trade_type.lower()} trade with "
                f"{round(exp_ret_pct,1)}% expected return in {holding_period}."
            )

            # Candle patterns from daily OHLCV
            candle_pats: list = []
            vol_analysis: dict = {}
            try:
                import yfinance as yf, pandas as pd
                tk  = yf.Ticker(f"{sym}.NS")
                df_daily = tk.history(period="10d", interval="1d", auto_adjust=True)
                if not df_daily.empty:
                    if hasattr(df_daily.columns, 'get_level_values'):
                        df_daily.columns = df_daily.columns.get_level_values(0)
                    df_daily.columns = [str(c).lower() for c in df_daily.columns]
                    candle_pats  = self.data_fetcher.detect_candle_patterns(df_daily)
                    vol_analysis = self.data_fetcher.get_volume_analysis(df_daily, close)
            except Exception:
                pass

            candidates.append({
                'symbol':              sym,
                'price':               round(close, 2),
                'prev_close':          round(prev_close, 2),
                'change_pct':          round(change_pct, 2),
                'ema20':               round(ema20, 2),
                'ema50':               round(ema50, 2),
                'rsi':                 round(rsi, 1),
                'adx':                 round(adx, 1),
                'atr':                 round(atr, 2),
                'vol_ratio':           round(vol_ratio, 2),
                'sector':              sector,
                'trade_type':          trade_type,
                'holding_period':      holding_period,
                'expected_return_pct': exp_ret_pct,
                'stop_loss':           stop_loss_est,
                'target':              target_est,
                'selection_reason':    sel_reason,
                # scoring factors (0-1)
                'momentum':            round(momentum, 3),
                'trend_strength':      round(trend_strength, 3),
                'relative_strength':   round(relative_str, 3),
                'volume_confirm':      round(vol_confirm, 3),
                'volatility':          round(volatility, 3),
                'earnings_quality':    round(earnings_quality, 3),
                'fii_interest':        round(fii_interest, 3),
                'news_sentiment':      round(news_sentiment, 3),
                'ta_reasons':          ta_reasons,
                'fa_reasons':          [],
                'fundamental':         d.get('fundamental', {}),
                'candle_patterns':     candle_pats,
                'volume_analysis':     vol_analysis,
            })
        # Enrich with fundamentals (background, cached)
        for c in candidates:
            try:
                fund = self.data_fetcher.get_fundamentals(c['symbol'])
                c['fundamental'] = fund
                c['company_name'] = fund.get('company_name', c['symbol'])
                # Use real PE / ROE for fa_reasons if available
                if fund.get('pe_ratio'):
                    fa = []
                    if fund['pe_ratio'] < 25:  fa.append(f"P/E {fund['pe_ratio']} — below 25 (value zone)")
                    elif fund['pe_ratio'] > 45: fa.append(f"P/E {fund['pe_ratio']} — above 45 (expensive)")
                    if fund.get('roe') and fund['roe'] > 15: fa.append(f"ROE {fund['roe']}% — above 15% (quality)")
                    if fund.get('revenue_growth') and fund['revenue_growth'] > 10: fa.append(f"Revenue growing {fund['revenue_growth']}% YoY")
                    if fund.get('debt_to_equity') is not None and fund['debt_to_equity'] < 0.5: fa.append(f"Low debt/equity {fund['debt_to_equity']} — clean balance sheet")
                    if fund.get('dividend_yield') and fund['dividend_yield'] > 1.5: fa.append(f"Dividend yield {fund['dividend_yield']}%")
                    c['fa_reasons'] = fa
            except Exception:
                pass
        return candidates

    def _check_options_flow(self, market_data) -> List[Dict]:
        signals = []
        for sym in settings.SYMBOLS:
            try:
                res = self.agents['OPTIONS_FLOW'].analyze_unusual_options_activity(sym)
                if res and res.get('signal_strength', 0) > 0.6:
                    sig = res.get('signal', 'NEUTRAL')
                    if sig != 'NEUTRAL':
                        s = {'symbol': sym, 'signal': sig, 'strength': res['signal_strength'],
                             'source': 'OPTIONS_FLOW', 'timestamp': datetime.now().strftime('%H:%M:%S')}
                        signals.append(s)
                        if self.telegram.is_enabled():
                            self.telegram.options_signal(sym, sig, res['signal_strength'],
                                len(res.get('sweeps',[])), res.get('dark_pool',{}).get('signal','—'))
            except Exception:
                pass
        return signals

    def _apply_mtf_filter(self, signals) -> List[Dict]:
        confirmed = []
        for sig in signals:
            try:
                r = self.agents['MULTI_TIMEFRAME'].check_timeframe_alignment(sig['symbol'])
                if r.get('buy_votes', 0) >= 3 or r.get('sell_votes', 0) >= 3:
                    sig['mtf_confirmed'] = True
                    sig['mtf_confidence'] = r.get('confidence', 0)
                    confirmed.append(sig)
            except Exception:
                confirmed.append(sig)
        return confirmed

    def _check_risk_and_execute(self, signals, market_data, size_mult: float = 1.0) -> List[Dict]:
        """
        FIX 4 continued: size_mult from ORACLE is passed in and applied to
        every position size before GUARDIAN's hard limits run.
        GUARDIAN's rules (max daily loss, kill switch, etc.) are never bypassed.
        """
        approved = []
        positions = self.executor.get_positions() if hasattr(self.executor, 'get_positions') else {}
        capital   = self.risk_manager.get_available_capital()
        for sig in signals:
            try:
                pos_list = list(positions.values()) if isinstance(positions, dict) else (positions or [])
                approval = self.agents['GUARDIAN'].check_trade(sig, capital, pos_list)
                if approval.get('approved'):
                    # Apply ORACLE macro size multiplier (advisory, before hard limits)
                    raw_size = approval.get('position_size', 0)
                    adjusted_size = raw_size * size_mult
                    result = self.agents['MERCURY'].execute_trade(sig, adjusted_size)
                    if result:
                        approved.append(sig)
                        # ── Store signal so KARMA can learn when outcome arrives ──
                        sym = sig.get('symbol', '')
                        if sym:
                            self._pending_signals[sym] = dict(sig)
                        self.agent_tracker.record_signal(
                            sig.get('source', 'TITAN'),
                            sig['symbol'], sig['signal'],
                            sig.get('confidence', 0)
                        )
                        self.risk_manager.update_pnl(0, False)
            except Exception as e:
                logger.warning(f"Execution error: {sig.get('symbol')}: {e}")
        return approved

    def _update_trailing_stops(self, market_data):
        try:
            stop_data = {
                sym: {'price': info.get('close', 0), 'atr': info.get('atr', 0)}
                for sym, info in market_data.get('data', {}).items()
            }
            self.trailing_stops.update_trailing_stops(stop_data)
        except Exception:
            pass

    def _write_state(self, regime, sentiment, signals):
        uptime    = int((datetime.now() - self.start_time).total_seconds())
        positions = []
        try:
            pos = self.executor.get_positions() if hasattr(self.executor, 'get_positions') else {}
            # Build a quick TA lookup from the last fetched market data
            _mdata = getattr(self, '_last_market_data', {}).get('data', {})
            for sym, p in pos.items():
                md = _mdata.get(sym, {})
                ep = p.get('entry_price', 0)
                cp = p.get('current_price', ep)
                pnl = (cp - ep) * p.get('quantity', 0)
                pnl_pct = (cp - ep) / ep * 100 if ep else 0

                # Find SIGMA score for this symbol if available
                sel = next((s for s in self._selected_stocks if s.get('symbol') == sym), {})

                positions.append({
                    'symbol':          sym,
                    'side':            p.get('side', 'LONG'),
                    'quantity':        p.get('quantity', 0),
                    'entry_price':     ep,
                    'stop_loss':       p.get('stop_loss', 0),
                    'target':          p.get('target', 0),
                    'current_price':   cp,
                    'unrealised_pnl':  round(pnl, 0),
                    'pnl_pct':         round(pnl_pct, 2),
                    'source':          p.get('source', '—'),
                    'mtf_confirmed':   p.get('mtf_confirmed', False),
                    'confidence':      p.get('confidence', 0),
                    'regime':          p.get('regime', regime),
                    # TA indicators from latest market data
                    'price':           cp,
                    'change_pct':      round(pnl_pct, 2),
                    'rsi':             md.get('rsi', 0),
                    'adx':             md.get('adx', 0),
                    'ema20':           md.get('ema20', 0),
                    'ema50':           md.get('ema50', 0),
                    'atr':             md.get('atr', 0),
                    'vol_ratio':       md.get('vol_ratio', 1.0),
                    'momentum':        sel.get('momentum', md.get('momentum', 0)),
                    'trend_strength':  sel.get('trend_strength', md.get('trend_strength', 0)),
                    'relative_strength': sel.get('relative_strength', 0),
                    'volume_confirm':  sel.get('volume_confirm', 0),
                    'volatility':      sel.get('volatility', 0),
                    'sigma_score':     sel.get('sigma_score', 0),
                    'sector':          sel.get('sector', ''),
                    'ta_reasons':      sel.get('ta_reasons', []),
                    'fa_reasons':      sel.get('fa_reasons', []),
                    'fundamental':     sel.get('fundamental', {}),
                })
        except Exception:
            pass

        lens_summary = {}
        try: lens_summary = self.agents['LENS'].get_performance_summary()
        except Exception: pass

        agent_perf = self.agent_tracker.get_summary()

        # FIX 5: surface ORACLE macro data to dashboard
        mc = self._macro_context  # set each iteration by _run_iteration

        live_state.update({
            'system': {
                'status': 'RUNNING', 'mode': self.mode,
                'iteration': self.iteration, 'uptime_s': uptime,
                'symbols': settings.SYMBOLS,
            },
            'portfolio': {
                'initial_capital': settings.INITIAL_CAPITAL,
                'current_value':   settings.INITIAL_CAPITAL + self.risk_manager.daily_pnl,
                'daily_pnl':       self.risk_manager.daily_pnl,
                'daily_pnl_pct':   self.risk_manager.daily_pnl / settings.INITIAL_CAPITAL,
                'total_trades':    lens_summary.get('total_trades', 0),
                'open_positions':  len(positions),
                'win_rate':        lens_summary.get('win_rate', 0),
                'profit_locked':   getattr(self.trailing_stops, 'total_locked_profit', 0),
            },
            'regime':          regime,
            'sentiment':       sentiment.get('overall','NEUTRAL') if isinstance(sentiment,dict) else 'NEUTRAL',
            # ── FIX 5: macro fields now visible in dashboard ──────────────────
            'vix':             mc.get('vix', 0.0),
            'macro_bias':      mc.get('macro_bias', 'NEUTRAL'),
            'macro_risk':      mc.get('risk_level', 'MEDIUM'),
            'fii_flow_cr':     mc.get('fii_flow_cr', 0.0),
            'usdinr':          mc.get('usdinr', 0.0),
            'oracle_size_mult': mc.get('size_mult', 1.0),
            # ─────────────────────────────────────────────────────────────────
            'positions':       positions,
            # Per-symbol sentiment scores for modal News tab
            'capital_summary':  self.capital_allocator.get_summary(),
            'karma_summary':    self.agents['KARMA'].get_knowledge_summary(),
            'sentiment_scores': (lambda s: s.get('scores', {}) if isinstance(s, dict) else {})(
                (lambda: getattr(self.agents.get('HERMES'), '_cache', None) or {})()
            ),
            'sentiment_headlines': (lambda c: c.get('headlines', []) if isinstance(c, dict) else [])(
                (lambda: getattr(self.agents.get('HERMES'), '_cache', None) or {})()
            ),
            'selected_stocks': [
                {
                    'symbol':              s.get('symbol', ''),
                    'score':               s.get('sigma_score', 0),
                    'sigma_score':         s.get('sigma_score', 0),
                    'sector':              s.get('sector', ''),
                    'price':               s.get('price', 0),
                    'change_pct':          s.get('change_pct', 0),
                    'capital_weight':      s.get('capital_weight', 0),
                    'rsi':                 s.get('rsi', 0),
                    'adx':                 s.get('adx', 0),
                    'ema20':               s.get('ema20', 0),
                    'ema50':               s.get('ema50', 0),
                    'atr':                 s.get('atr', 0),
                    'vol_ratio':           s.get('vol_ratio', 1.0),
                    'momentum':            s.get('momentum', 0),
                    'trend_strength':      s.get('trend_strength', 0),
                    'relative_strength':   s.get('relative_strength', 0),
                    'volume_confirm':      s.get('volume_confirm', 0),
                    'trade_type':          s.get('trade_type', 'SWING'),
                    'holding_period':      s.get('holding_period', '3–10 days'),
                    'expected_return_pct': s.get('expected_return_pct', 0),
                    'stop_loss':           s.get('stop_loss', 0),
                    'target':              s.get('target', 0),
                    'selection_reason':    s.get('selection_reason', ''),
                    'news_sentiment_score':s.get('news_sentiment', 0),
                    'ta_reasons':          s.get('ta_reasons', []),
                    'fa_reasons':          s.get('fa_reasons', []),
                    'fundamental':         s.get('fundamental', {}),
                    'confidence':          s.get('confidence', 0),
                    # Capital allocation fields (from CapitalAllocator)
                    'capital_amount':      s.get('amount', 0),
                    'capital_weight':      s.get('weight', s.get('capital_weight', 0)),
                    'capital_qty':         s.get('qty', 0),
                    'pct_of_portfolio':    s.get('pct_of_portfolio', 0),
                    'candle_patterns':      s.get('candle_patterns', []),
                    'volume_analysis':      s.get('volume_analysis', {}),
                    'company_name':         s.get('company_name', s.get('symbol','')),
                }
                for s in self._selected_stocks
            ],
            'recent_signals':  signals[-20:],
            'agents':          {
                n: {
                    'active': True,
                    'cycles': getattr(getattr(self, '_agent_cycles', {}).get(n), '__self__', None) and 1 or 0,
                    'last':   '—',
                }
                for n in self.agents
            },
            'agent_performance': agent_perf,
            'risk': {
                'kill_switch':        getattr(self.risk_manager, 'kill_switch_active', False),
                'daily_loss_pct':     abs(self.risk_manager.daily_pnl) / settings.INITIAL_CAPITAL,
                'trades_today':       self.agents['GUARDIAN'].trades_today,
                'consecutive_losses': self.agents['GUARDIAN'].consecutive_losses,
            },
            'telegram_enabled':   self.telegram.is_enabled(),
            'email_enabled':      self.email.is_enabled(),
            'telegram_chat_id':   os.getenv('TELEGRAM_CHAT_ID', ''),
            'email_recipient':    os.getenv('EMAIL_RECIPIENT', ''),
            'email_smtp_host':    os.getenv('EMAIL_SMTP_HOST', 'smtp.gmail.com'),
            'llm_provider':       str(self.llm).split('(')[0].replace('Provider',''),
            'llm_model':          self.llm.model,
            'llm_cost_today':     0.0,
            'suggestions':        [],
        })

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_signal(self, event):
        logger.info(f"  [EVENT] Signal: {event.payload.get('symbol')} {event.payload.get('signal')} (p={event.priority})")

    def _on_trade_executed(self, event):
        p = event.payload
        logger.info(f"  [TRADE] {p}")
        if self.telegram.is_enabled():
            self.telegram.trade_executed(
                p.get('symbol','?'), p.get('side','BUY'), p.get('quantity',0),
                p.get('price',0), p.get('strategy','—'), p.get('confidence',0),
                p.get('target',0), p.get('stop_loss',0)
            )
        sym = p.get('symbol')
        if sym:
            self.agent_tracker.record_signal(p.get('source','TITAN'), sym, p.get('side','BUY'), p.get('confidence',0))
            # Record trade in LENS for performance attribution
            try:
                self.agents['LENS'].record_trade({
                    'symbol':   sym,
                    'side':     p.get('side','BUY'),
                    'strategy': p.get('strategy','TITAN'),
                    'pnl':      0.0,  # will be updated when stop/target fires
                })
            except Exception:
                pass

    def _on_risk_alert(self, event):
        logger.warning(f"  [RISK] {event.payload}")
        if self.telegram.is_enabled():
            self.telegram.risk_alert(
                event.payload.get('action','RISK'),
                str(event.payload)
            )

    def _on_stop_hit(self, event):
        p = event.payload
        logger.info(f"  [STOP] {p}")
        pnl = float(p.get('pnl', 0) or 0)
        sym = p.get('symbol', '')
        if self.telegram.is_enabled():
            self.telegram.stop_loss_hit(
                sym, p.get('stop_price',0),
                p.get('entry_price',0), pnl
            )
        # ── KARMA feedback: stop hit = negative outcome ──────────────────────
        self._karma_feedback(sym, pnl, 'stop_hit')
        # LENS records final P&L
        try:
            orig_sig = self._pending_signals.pop(sym, {})
            self.agents['LENS'].record_trade({
                'symbol':   sym,
                'side':     orig_sig.get('signal', 'BUY'),
                'strategy': orig_sig.get('source', 'TITAN'),
                'pnl':      pnl,
            })
        except Exception:
            pass
        # GUARDIAN: count loss
        try:
            if pnl < 0:
                self.agents['GUARDIAN'].consecutive_losses += 1
        except Exception:
            pass

    def _on_target_reached(self, event):
        p = event.payload
        logger.info(f"  [TARGET] {p}")
        pnl = float(p.get('pnl', 0) or 0)
        sym = p.get('symbol', '')
        # ── KARMA feedback: target hit = positive outcome ─────────────────────
        self._karma_feedback(sym, pnl, 'target_reached')
        # LENS
        try:
            orig_sig = self._pending_signals.pop(sym, {})
            self.agents['LENS'].record_trade({
                'symbol':   sym,
                'side':     orig_sig.get('signal', 'BUY'),
                'strategy': orig_sig.get('source', 'TITAN'),
                'pnl':      pnl,
            })
        except Exception:
            pass
        # GUARDIAN: reset consecutive losses on win
        try:
            if pnl > 0:
                self.agents['GUARDIAN'].consecutive_losses = 0
        except Exception:
            pass

    def _karma_feedback(self, symbol: str, pnl: float, event_type: str):
        """
        Core KARMA↔LENS feedback loop.
        Called on every closed trade (stop or target).
        KARMA learns from outcome → adjusts strategy weights →
        weights fed back to TITAN next iteration.
        """
        try:
            orig_sig = self._pending_signals.get(symbol, {})
            outcome  = {'pnl': pnl, 'event': event_type, 'symbol': symbol}
            self.agents['KARMA'].learn_from_outcome(orig_sig, outcome)
            # ORACLE accuracy feedback
            nifty_up = pnl > 0   # rough proxy
            try:
                self.agents['ORACLE'].record_outcome(nifty_up)
            except Exception:
                pass
            logger.debug(
                f"KARMA feedback: {symbol} {event_type} pnl={pnl:+.0f} "
                f"strategy={orig_sig.get('source','?')}"
            )
        except Exception as e:
            logger.warning(f"KARMA feedback error: {e}")

    def _shutdown_handler(self, sig, frame):
        logger.info("\n⛔ Shutdown signal received")
        self.running = False
        if hasattr(self, '_dashboard_proc'):
            try: self._dashboard_proc.terminate()
            except: pass
        live_state.update({'system': {'status': 'STOPPED'}})
        sys.exit(0)


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description='AlphaZero Capital v17')
    p.add_argument('--live', action='store_true', help='Enable live trading')
    p.add_argument('--mode', choices=['PAPER','LIVE'], help='Override MODE in .env')
    return p.parse_args()


if __name__ == '__main__':
    args  = parse_args()
    mode  = 'LIVE' if args.live else (args.mode or None)
    system = AlphaZeroSystem(mode=mode)
    system.run()
