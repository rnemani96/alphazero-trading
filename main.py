"""
AlphaZero Capital v17 — Main Orchestrator
main.py

Entry point. Starts all agents, reporters, and the trading loop.
All LLM calls go through LLMProvider.create() — fully generic.

Usage:
    python main.py              # paper trading (default)
    python main.py --live       # live trading
"""

import sys, os, time, signal, logging, argparse, threading, subprocess
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

from src.risk.risk_manager          import RiskManager
from src.risk.trailing_stop_manager import TrailingStopManager
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

    def _init_agents(self):
        cfg, eb = self._cfg, self.event_bus
        self.agents = {
            'CHIEF':              ChiefAgent(eb, cfg),
            'SIGMA':              SigmaAgent(eb, cfg),
            'SECTOR':             SectorAgent(eb, cfg),
            'NEXUS':              IntradayRegimeAgent(eb, cfg),
            'HERMES':             NewsSentimentAgent(eb, cfg),
            'TITAN':              TitanAgent(eb, cfg),
            'GUARDIAN':           GuardianAgent(eb, cfg),
            'MERCURY':            MercuryAgent(eb, cfg, self.executor),
            'LENS':               LensAgent(eb, cfg),
            'KARMA':              KarmaAgent(eb, cfg),
            'OPTIONS_FLOW':       OptionsFlowAgent(eb, cfg),
            'MULTI_TIMEFRAME':    MultiTimeframeAgent(eb, cfg),
            'EARNINGS_ANALYZER':  EarningsCallAnalyzer(eb, cfg),
            'STRATEGY_GENERATOR': StrategyGenerator(eb, cfg),
        }
        logger.info(f"  {len(self.agents)} agents ready")

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
        """Auto-start the Flask dashboard in a background process."""
        import sys, os, time
        server_path = os.path.join(ROOT, 'dashboard', 'server.py')
        if not os.path.exists(server_path):
            logger.warning("Dashboard server not found, skipping auto-start")
            return
        try:
            proc = subprocess.Popen(
                [sys.executable, server_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._dashboard_proc = proc
            time.sleep(1.0)   # give Flask a moment to bind
            port = getattr(settings, 'DASHBOARD_PORT', 8080)
            host = getattr(settings, 'DASHBOARD_HOST', 'localhost')
            url  = f"http://{host}:{port}"
            logger.info(f"✅ Dashboard started → {url}")
            # Open browser automatically
            def _open():
                import webbrowser, time
                time.sleep(1.5)
                webbrowser.open(url)
            threading.Thread(target=_open, daemon=True).start()
        except Exception as e:
            logger.warning(f"Dashboard auto-start failed: {e}")

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

        market_data      = self._fetch_market_data()
        options_signals  = self._check_options_flow(market_data)
        regime           = self.agents['NEXUS'].detect_regime(market_data)
        sentiment        = self.agents['HERMES'].get_sentiment(settings.SYMBOLS)
        earnings_signals = []
        titan_signals    = self.agents['TITAN'].generate_signals(market_data, regime)

        all_signals = options_signals + earnings_signals + titan_signals
        confirmed   = self._apply_mtf_filter(all_signals)
        approved    = self._check_risk_and_execute(confirmed, market_data)

        self._update_trailing_stops(market_data)
        self.agents['LENS'].update()
        self.agents['KARMA'].update()

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
        return {'symbols': settings.SYMBOLS, 'prices': prices,
                'data': data, 'timestamp': datetime.now().isoformat()}

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

    def _check_risk_and_execute(self, signals, market_data) -> List[Dict]:
        approved = []
        positions = self.executor.get_positions() if hasattr(self.executor, 'get_positions') else {}
        capital   = self.risk_manager.get_available_capital()
        for sig in signals:
            try:
                pos_list = list(positions.values()) if isinstance(positions, dict) else (positions or [])
                approval = self.agents['GUARDIAN'].check_trade(sig, capital, pos_list)
                if approval.get('approved'):
                    result = self.agents['MERCURY'].execute_trade(sig, approval.get('position_size', 0))
                    if result:
                        approved.append(sig)
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
            for sym, p in pos.items():
                positions.append({
                    'symbol': sym, 'side': p.get('side','LONG'),
                    'quantity': p.get('quantity',0),
                    'entry_price': p.get('entry_price',0),
                    'stop_loss': p.get('stop_loss',0),
                    'current_price': p.get('current_price',0),
                    'unrealised_pnl': p.get('unrealised_pnl',0),
                    'source': p.get('source','—'),
                    'mtf_confirmed': p.get('mtf_confirmed',False),
                })
        except Exception:
            pass

        lens_summary = {}
        try: lens_summary = self.agents['LENS'].get_performance_summary()
        except Exception: pass

        agent_perf = self.agent_tracker.get_summary()

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
            'positions':       positions,
            'recent_signals':  signals[-20:],
            'agents':          {n: {'active': True} for n in self.agents},
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
        if self.telegram.is_enabled():
            self.telegram.stop_loss_hit(
                p.get('symbol','?'), p.get('entry',0),
                p.get('exit',0), p.get('quantity',0), p.get('pnl',0)
            )
        sym = p.get('symbol')
        if sym:
            self.agent_tracker.record_outcome(p.get('source','TITAN'), sym, p.get('pnl',0), False)

    def _on_target_reached(self, event):
        p = event.payload
        logger.info(f"  [TARGET] {p}")
        if self.telegram.is_enabled():
            self.telegram.target_reached(
                p.get('symbol','?'), p.get('entry',0),
                p.get('exit',0), p.get('quantity',0), p.get('pnl',0)
            )
        sym = p.get('symbol')
        if sym:
            self.agent_tracker.record_outcome(p.get('source','TITAN'), sym, p.get('pnl',0), True)

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def _shutdown_handler(self, sig, frame):
        logger.info("\n🛑  Shutdown signal received"); self.shutdown()

    def shutdown(self):
        self.running = False
        self.report_scheduler.stop()
        if hasattr(self, '_dashboard_proc'):
            try: self._dashboard_proc.terminate()
            except Exception: pass
        self._cmd_handler.stop()
        for agent in self.agents.values():
            try:
                if hasattr(agent, 'shutdown'): agent.shutdown()
            except Exception: pass
        self.event_bus.stop()
        live_state.update({'system': {'status': 'STOPPED'}})
        logger.info("✅ Shut down cleanly")


def main():
    parser = argparse.ArgumentParser(description='AlphaZero Capital v17')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    mode = 'LIVE' if args.live else 'PAPER'
    if mode == 'LIVE' and not settings.OPENALGO_API_KEY:
        logger.error("LIVE mode requires OPENALGO_API_KEY in .env"); sys.exit(1)
    AlphaZeroSystem(mode=mode).run()

if __name__ == '__main__':
    main()
