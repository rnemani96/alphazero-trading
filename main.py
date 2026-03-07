"""
AlphaZero Capital v17 - Complete Main Orchestration
Integrates ALL agents: v15 base + v16 enhancements + v17 LLM

AGENT COUNT: 16 agents working together!

FIXES:
1. _initialize_agents() used self.executor before it was created.
   Fixed by splitting initialisation: executor is created first inside
   _initialize_managers(), which is now called BEFORE _initialize_agents().

2. self.event_bus.start() / .stop() called but methods didn't exist in EventBus.
   Fixed by adding start() / stop() to EventBus (see event_bus.py).

3. Duplicate / conflicting stdout reconfiguration (reconfigure() then
   TextIOWrapper) — removed the TextIOWrapper lines; reconfigure() is enough.

4. Market data format mismatch: _fetch_market_data() returned a flat 'prices'
   dict but TrailingStopManager expected per-symbol nested dicts with 'price'
   and 'atr' keys.  Fixed by using DataFetcher which returns both formats.

5. _generate_trading_signals() never called TITAN for technical signals.
   Fixed — TITAN.generate_signals() is now called and its signals are merged.

6. Import of DataFetcher pointed to a non-existent file src/data/fetch.py.
   Fixed by creating that file.

7. SigmaAgent was imported but the file sigma_agent.py was missing.
   Fixed by creating the file.
"""

import os
import sys
import logging
from datetime import datetime
from typing import Dict, List

# Fix stdout encoding once, cleanly
sys.stdout.reconfigure(encoding='utf-8')

# Core infrastructure
from src.event_bus.event_bus import EventBus, EventType

# v15 Base Agents
from src.agents.chief_agent import ChiefAgent
from src.agents.sigma_agent import SigmaAgent          # FIX: file now exists
from src.agents.sector_agent import SectorAgent
from src.agents.intraday_regime_agent import IntradayRegimeAgent
from src.agents.news_sentiment_agent import NewsSentimentAgent
from src.agents.titan_agent import TitanAgent
from src.agents.guardian_agent import GuardianAgent
from src.agents.mercury_agent import MercuryAgent
from src.agents.lens_agent import LensAgent
from src.agents.karma_agent import KarmaAgent

# v16 Enhanced Agents
from src.agents.options_flow_agent import OptionsFlowAgent
from src.agents.multi_timeframe_agent import MultiTimeframeAgent

# v17 LLM Agents
from src.agents.llm_earnings_analyzer import EarningsCallAnalyzer
from src.agents.llm_strategy_generator import StrategyGenerator

# Risk Management
from src.risk.risk_manager import RiskManager
from src.risk.trailing_stop_manager import TrailingStopManager

# Execution
from src.execution.openalgo_executor import OpenAlgoExecutor
from src.execution.paper_executor import PaperExecutor

# Monitoring
from src.monitoring.logger import TradeLogger
from src.monitoring.monitor import SystemMonitor

# Data
from src.data.fetch import DataFetcher          # FIX: file now exists


# Configure logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/alphazero.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class AlphaZeroOrchestrator:
    """
    Main Orchestrator for AlphaZero Capital v17

    Coordinates 16 agents:

    BASE LAYER (v15):
    - CHIEF: Portfolio selection
    - SIGMA: Stock scoring
    - ATLAS: Sector allocation
    - NEXUS: Regime detection
    - TITAN: Strategy execution
    - GUARDIAN: Risk management
    - MERCURY: Order execution
    - LENS: Performance tracking
    - HERMES: News sentiment
    - KARMA: RL learning

    ENHANCED LAYER (v16):
    - OPTIONS_FLOW: Unusual activity detection
    - MULTI_TIMEFRAME: Cross-timeframe confirmation

    INTELLIGENCE LAYER (v17):
    - EARNINGS_ANALYZER: LLM-powered earnings calls
    - STRATEGY_GENERATOR: Auto-discovers new strategies

    MANAGERS:
    - TRAILING_STOP: Profit locking
    - SYSTEM_MONITOR: Health tracking
    """

    def __init__(self, config: Dict):
        self.config = config
        self.mode = config.get('MODE', 'PAPER')

        logger.info("=" * 80)
        logger.info("🚀 AlphaZero Capital v17 Initializing...")
        logger.info("=" * 80)

        # Initialize Event Bus (central nervous system)
        self.event_bus = EventBus()

        # FIX: Initialize managers FIRST so self.executor exists before agents need it
        self._initialize_managers()

        # Then initialize agents (MERCURY needs self.executor)
        self.agents: Dict = {}
        self._initialize_agents()

        # Tracking
        self.positions: List[Dict] = []
        self.daily_pnl = 0.0
        self.total_trades = 0
        self.running = False

        logger.info(f"✅ AlphaZero v17 Ready - {len(self.agents)} agents active!")
        logger.info(f"Mode: {self.mode}")
        logger.info("=" * 80)

    # ── Initialization ───────────────────────────────────────────────────────

    def _initialize_managers(self):
        """
        Initialize risk, execution, and monitoring managers.

        FIX: Called BEFORE _initialize_agents() so self.executor is available
        when MercuryAgent is constructed.
        """
        logger.info("\n🛡️ Initializing Managers...")

        # Risk management
        self.risk_manager = RiskManager(self.config)
        self.trailing_stop_manager = TrailingStopManager(self.config)

        # FIX: Executor created here so _initialize_agents() can reference it
        if self.mode == 'LIVE':
            self.executor = OpenAlgoExecutor(self.config)
            logger.warning("  🔴 LIVE MODE - Real money trading!")
        else:
            self.executor = PaperExecutor(self.config)
            logger.info("  📄 PAPER MODE - Safe simulation")

        # Data fetcher
        self.data_fetcher = DataFetcher(self.config)

        # Monitoring (system monitor created after agents exist — set later)
        self.trade_logger = TradeLogger()
        self.system_monitor = None   # set at end of _initialize_agents

        logger.info("  ✅ Managers initialized")

    def _initialize_agents(self):
        """Initialize all 16 agents."""
        logger.info("\n📦 Initializing Agents...")

        # Base agents (v15)
        self.agents['CHIEF'] = ChiefAgent(self.event_bus, self.config)
        self.agents['SIGMA'] = SigmaAgent(self.event_bus, self.config)
        self.agents['ATLAS'] = SectorAgent(self.event_bus, self.config)
        self.agents['NEXUS'] = IntradayRegimeAgent(self.event_bus, self.config)
        self.agents['HERMES'] = NewsSentimentAgent(self.event_bus, self.config)
        self.agents['TITAN'] = TitanAgent(self.event_bus, self.config)
        self.agents['GUARDIAN'] = GuardianAgent(self.event_bus, self.config)
        # FIX: self.executor now exists because _initialize_managers ran first
        self.agents['MERCURY'] = MercuryAgent(self.event_bus, self.config, self.executor)
        self.agents['LENS'] = LensAgent(self.event_bus, self.config)
        self.agents['KARMA'] = KarmaAgent(self.event_bus, self.config)

        # v16 Enhanced agents
        logger.info("  🔥 Loading v16 enhancements...")
        self.agents['OPTIONS_FLOW'] = OptionsFlowAgent(self.event_bus, self.config)
        self.agents['MULTI_TIMEFRAME'] = MultiTimeframeAgent(self.event_bus, self.config)

        # v17 LLM agents (if API key available)
        anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        if anthropic_key:
            logger.info("  🧠 Loading v17 LLM agents...")
            self.agents['EARNINGS_ANALYZER'] = EarningsCallAnalyzer(anthropic_key)
            self.agents['STRATEGY_GENERATOR'] = StrategyGenerator(anthropic_key, None)
        else:
            logger.warning("  ⚠️ ANTHROPIC_API_KEY not found - LLM agents disabled")

        # Now wire up system monitor with full agent dict
        self.system_monitor = SystemMonitor(self.agents)

        logger.info(f"  ✅ {len(self.agents)} agents initialized")

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        """Start the trading system."""
        logger.info("\n🚀 Starting AlphaZero Capital v17...")

        # FIX: start() now exists in EventBus
        self.event_bus.start()

        # Start all agents that support it
        for name, agent in self.agents.items():
            if hasattr(agent, 'start'):
                agent.start()
                logger.info(f"  ✅ {name} started")

        self.running = True
        self._main_loop()

    def stop(self):
        """Stop the trading system."""
        logger.info("\n⏹️ Stopping AlphaZero Capital...")

        self.running = False

        for name, agent in self.agents.items():
            if hasattr(agent, 'stop'):
                agent.stop()
                logger.info(f"  ✅ {name} stopped")

        # FIX: stop() now exists in EventBus
        self.event_bus.stop()

        logger.info("\n📊 Final Report:")
        logger.info(f"  Total Trades:    {self.total_trades}")
        logger.info(f"  Open Positions:  {len(self.positions)}")
        logger.info(f"  Daily P&L:       ₹{self.daily_pnl:,.2f}")
        logger.info("\n✅ AlphaZero Capital stopped successfully")

    # ── Main Loop ────────────────────────────────────────────────────────────

    def _main_loop(self):
        """
        Main trading loop.

        Flow:
        1.  Fetch market data
        2.  OPTIONS_FLOW checks for unusual activity
        3.  NEXUS determines market regime
        4.  HERMES provides news sentiment
        5.  EARNINGS_ANALYZER processes any new earnings calls
        6.  CHIEF selects portfolio (long-term)
        7.  TITAN generates trading signals (intraday)
        8.  MULTI_TIMEFRAME confirms signals
        9.  GUARDIAN checks risk limits
        10. TRAILING_STOP manages stops
        11. MERCURY executes approved trades
        12. LENS tracks performance
        13. STRATEGY_GENERATOR discovers new patterns (nightly)
        """
        import time

        logger.info("\n▶️ Main Loop Started")
        logger.info("=" * 80)

        iteration = 0

        while self.running:
            try:
                iteration += 1
                current_time = datetime.now()
                logger.info(f"\n🔄 Iteration {iteration} - {current_time.strftime('%H:%M:%S')}")

                # ── STEP 1: Market Data ────────────────────────────────────
                # FIX: use DataFetcher which returns both 'prices' (flat) and
                # 'data' (nested with price/atr per symbol) for all consumers
                market_data = self._fetch_market_data()

                # ── STEP 2: OPTIONS FLOW ───────────────────────────────────
                if 'OPTIONS_FLOW' in self.agents:
                    options_signals = self._check_options_flow(market_data)
                    logger.info(f"  💰 Options Flow: {len(options_signals)} signals")
                else:
                    options_signals = []

                # ── STEP 3: REGIME DETECTION ───────────────────────────────
                # FIX: pass the per-symbol data dict (with adx/vix keys)
                regime_input = {**market_data, **market_data.get('data', {}).get(
                    market_data['symbols'][0], {}
                )} if market_data['symbols'] else market_data
                regime = self.agents['NEXUS'].detect_regime(regime_input)
                logger.info(f"  🌊 Market Regime: {regime}")

                # ── STEP 4: NEWS SENTIMENT ─────────────────────────────────
                news_sentiment = self.agents['HERMES'].get_sentiment(market_data['symbols'])
                logger.info(f"  📰 News Sentiment: {news_sentiment.get('overall', 'NEUTRAL')}")

                # ── STEP 5: EARNINGS ANALYSIS ──────────────────────────────
                if 'EARNINGS_ANALYZER' in self.agents:
                    earnings_signals = self._check_earnings(market_data)
                    logger.info(f"  📊 Earnings Signals: {len(earnings_signals)}")
                else:
                    earnings_signals = []

                # ── STEP 6: GENERATE SIGNALS ───────────────────────────────
                signals = self._generate_trading_signals(
                    market_data, regime, news_sentiment,
                    options_signals, earnings_signals
                )

                # ── STEP 7: MULTI-TIMEFRAME FILTER ─────────────────────────
                if 'MULTI_TIMEFRAME' in self.agents:
                    signals = self._apply_multi_timeframe_filter(signals)
                    logger.info(f"  ⏱️ Multi-Timeframe: {len(signals)} signals passed")

                # ── STEP 8: RISK CHECK ─────────────────────────────────────
                approved_signals = self._check_risk_limits(signals)
                logger.info(f"  🛡️ Risk Check: {len(approved_signals)} approved")

                # ── STEP 9: UPDATE TRAILING STOPS ─────────────────────────
                self._update_trailing_stops(market_data)

                # ── STEP 10: EXECUTE TRADES ────────────────────────────────
                if approved_signals:
                    self._execute_trades(approved_signals)

                # ── STEP 11: MONITOR POSITIONS ─────────────────────────────
                self._monitor_positions(market_data)

                # ── STEP 12: SYSTEM HEALTH ─────────────────────────────────
                if self.system_monitor:
                    health = self.system_monitor.check_health()
                    if health['status'] != 'HEALTHY':
                        logger.warning(f"  ⚠️ System Health: {health['status']}")

                # ── STEP 13: STRATEGY DISCOVERY (nightly at 20:00) ─────────
                if current_time.hour == 20 and 'STRATEGY_GENERATOR' in self.agents:
                    self._discover_new_strategies(market_data)

                time.sleep(self.config.get('ITERATION_INTERVAL', 900))

            except KeyboardInterrupt:
                logger.info("\n⏸️ Shutdown signal received...")
                self.stop()
                break

            except Exception as e:
                logger.error(f"❌ Error in main loop: {e}", exc_info=True)
                time.sleep(60)

    # ── Step Implementations ─────────────────────────────────────────────────

    def _fetch_market_data(self) -> Dict:
        """
        Fetch latest market data via DataFetcher.

        FIX: Previously returned a hand-coded dict with only flat 'prices'.
        Now returns DataFetcher output which has both 'prices' (flat) and
        'data' (nested per-symbol with price/atr) so all consumers are happy.
        """
        symbols = self.config.get(
            'SYMBOLS',
            ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK']
        )
        return self.data_fetcher.get_market_data(symbols)

    def _check_options_flow(self, market_data: Dict) -> List[Dict]:
        """Check for unusual options activity."""
        signals = []
        for symbol in market_data['symbols']:
            result = self.agents['OPTIONS_FLOW'].analyze_unusual_options_activity(symbol)
            if result.get('has_unusual_activity'):
                strength = result.get('signal_strength', 0)
                if strength > 0.6:
                    signals.append({
                        'symbol': symbol,
                        'signal': result.get('signal'),
                        'strength': strength,
                        'source': 'OPTIONS_FLOW',
                        'details': result
                    })
                    logger.info(
                        f"    🔥 {symbol}: {result.get('signal')} "
                        f"(Strength: {strength:.1%}, Sweeps: {len(result.get('sweeps', []))})"
                    )
        return signals

    def _check_earnings(self, market_data: Dict) -> List[Dict]:
        """Check for earnings call signals (stub; extend for live use)."""
        return []

    def _generate_trading_signals(
        self,
        market_data: Dict,
        regime: str,
        news_sentiment: Dict,
        options_signals: List[Dict],
        earnings_signals: List[Dict]
    ) -> List[Dict]:
        """
        Generate trading signals from all sources.

        FIX: Previously never called TITAN — technical signals were always empty.
        Now calls TITAN.generate_signals() and merges with options/earnings signals.
        """
        all_signals = []

        # Options flow signals (highest conviction)
        all_signals.extend(options_signals)

        # Earnings-driven signals
        all_signals.extend(earnings_signals)

        # FIX: Generate TITAN technical signals
        # TITAN expects {symbol: {indicator_data}} — use the 'data' sub-dict
        titan_input = market_data.get('data', {})
        if titan_input and 'TITAN' in self.agents:
            try:
                titan_signals = self.agents['TITAN'].generate_signals(titan_input, regime)
                for sig in titan_signals:
                    # Standardise key: TITAN uses 'action', rest of system uses 'signal'
                    sig.setdefault('signal', sig.get('action', 'BUY'))
                    sig.setdefault('source', 'TITAN')
                all_signals.extend(titan_signals)
                logger.info(f"  📈 TITAN: {len(titan_signals)} technical signals")
            except Exception as e:
                logger.warning(f"  ⚠️ TITAN signal generation failed: {e}")

        # Apply news sentiment bias
        if news_sentiment.get('overall') == 'BEARISH':
            all_signals = [s for s in all_signals if s.get('signal') != 'BUY']
        elif news_sentiment.get('overall') == 'BULLISH':
            all_signals = [s for s in all_signals if s.get('signal') != 'SELL']

        return all_signals

    def _apply_multi_timeframe_filter(self, signals: List[Dict]) -> List[Dict]:
        """Apply multi-timeframe confirmation (require 4/5 timeframes aligned)."""
        confirmed = []
        for signal in signals:
            mtf = self.agents['MULTI_TIMEFRAME'].check_timeframe_alignment(signal['symbol'])
            if mtf['buy_votes'] >= 4 or mtf['sell_votes'] >= 4:
                signal['mtf_confirmed'] = True
                signal['mtf_confidence'] = mtf['confidence']
                signal['mtf_quality'] = mtf['alignment_quality']
                confirmed.append(signal)
                logger.info(
                    f"    ✅ {signal['symbol']} CONFIRMED: "
                    f"{mtf['buy_votes']}/5 timeframes agree"
                )
            else:
                logger.info(
                    f"    ❌ {signal['symbol']} BLOCKED: "
                    f"Only {max(mtf['buy_votes'], mtf['sell_votes'])}/5 agree"
                )
        return confirmed

    def _check_risk_limits(self, signals: List[Dict]) -> List[Dict]:
        """Check signals against risk limits via RiskManager."""
        approved = []
        for signal in signals:
            check = self.risk_manager.check_trade(signal, self.positions)
            if check['approved']:
                approved.append(signal)
                logger.info(f"    ✅ {signal['symbol']} APPROVED")
            else:
                logger.info(f"    🛑 {signal['symbol']} BLOCKED: {check['reason']}")
        return approved

    def _update_trailing_stops(self, market_data: Dict):
        """
        Update trailing stops for open positions.

        FIX: TrailingStopManager.update_trailing_stops() expects
        market_data[symbol] = {'price': ..., 'atr': ...}.
        Pass the 'data' sub-dict (nested per-symbol format) not the flat 'prices' dict.
        """
        if not self.positions:
            return

        # FIX: use nested per-symbol data dict
        nested_data = market_data.get('data', {})
        updated = self.trailing_stop_manager.update_trailing_stops(
            self.positions, nested_data
        )

        for symbol, update in updated.items():
            logger.info(
                f"    🔒 {symbol} trailing stop → ₹{update['new_stop']:.2f} "
                f"(Locked: {update['locked_profit_pct']:.1%})"
            )
            for pos in self.positions:
                if pos['symbol'] == symbol:
                    pos['stop_loss'] = update['new_stop']

    def _execute_trades(self, signals: List[Dict]):
        """Execute approved trades via the executor."""
        for signal in signals:
            try:
                result = self.executor.execute_trade(signal)
                if result['success']:
                    self.total_trades += 1
                    new_pos = {
                        'symbol': signal['symbol'],
                        'side': 'LONG' if 'BUY' in str(signal.get('signal', '')) else 'SHORT',
                        'entry_price': result['fill_price'],
                        'quantity': result['quantity'],
                        'entry_time': datetime.now(),
                        'stop_loss': result.get('stop_loss'),
                        'source': signal.get('source', 'UNKNOWN'),
                        'value': result['fill_price'] * result['quantity']
                    }
                    self.positions.append(new_pos)
                    self.trade_logger.log_trade(signal, result)
                    logger.info(
                        f"  ✅ EXECUTED: {signal['symbol']} "
                        f"{signal.get('signal')} @ ₹{result['fill_price']}"
                    )
                else:
                    logger.error(f"  ❌ FAILED: {signal['symbol']} - {result.get('error')}")
            except Exception as e:
                logger.error(f"  ❌ Execution error for {signal['symbol']}: {e}")

    def _monitor_positions(self, market_data: Dict):
        """Monitor open positions and check stops."""
        if not self.positions:
            return

        # FIX: pass nested data format to check_stop_hit
        nested_data = market_data.get('data', {})
        stops_hit = self.trailing_stop_manager.check_stop_hit(self.positions, nested_data)

        for symbol in stops_hit:
            logger.warning(f"  🛑 STOP HIT: {symbol} - Closing position")
            self._close_position(symbol)

        # Calculate current unrealised P&L using flat prices dict
        flat_prices = market_data.get('prices', {})
        total_pnl = 0.0
        for pos in self.positions:
            current_price = flat_prices.get(pos['symbol'], pos['entry_price'])
            if pos['side'] == 'LONG':
                pnl = (current_price - pos['entry_price']) * pos['quantity']
            else:
                pnl = (pos['entry_price'] - current_price) * pos['quantity']
            total_pnl += pnl

        self.daily_pnl = total_pnl
        # Keep RiskManager in sync
        self.risk_manager.daily_pnl = total_pnl

        logger.info(
            f"  💰 Open Positions: {len(self.positions)}, "
            f"Unrealised P&L: ₹{total_pnl:,.2f}"
        )

    def _close_position(self, symbol: str):
        """Close a position and update tracking."""
        position = next((p for p in self.positions if p['symbol'] == symbol), None)
        if position:
            result = self.executor.close_position(position)
            pnl = result.get('pnl', 0)
            self.risk_manager.update_pnl(pnl)
            self.positions.remove(position)
            logger.info(f"  ✅ CLOSED: {symbol} - P&L: ₹{pnl:,.2f}")

    def _discover_new_strategies(self, market_data: Dict):
        """Run strategy discovery (nightly at 8 PM)."""
        logger.info("\n🧠 Running Strategy Discovery...")
        context = {
            'winning_strategies': ['EMA Cross', 'Options Flow'],
            'losing_strategies':  ['RSI Reversion'],
            'observations': {'trend': 'Strong momentum', 'regime': 'TRENDING'}
        }
        strategy = self.agents['STRATEGY_GENERATOR'].discover_strategy(
            market_context=market_data,
            recent_performance=context,
            regime='TRENDING'
        )
        if strategy.get('successful'):
            logger.info(
                f"  🎉 NEW STRATEGY: {strategy['name']} "
                f"(Sharpe: {strategy['backtest_results']['sharpe']:.2f})"
            )
        else:
            logger.info("  📝 Strategy didn't meet criteria - continuing research")


# ── Entry Point ──────────────────────────────────────────────────────────────

def main():
    """Main entry point."""
    config = {
        'MODE':                   os.getenv('MODE', 'PAPER'),
        'ITERATION_INTERVAL':     int(os.getenv('ITERATION_INTERVAL', '900')),  # 15 min
        'MAX_DAILY_LOSS_PCT':     float(os.getenv('MAX_DAILY_LOSS_PCT', '0.02')),
        'MAX_POSITION_SIZE_PCT':  float(os.getenv('MAX_POSITION_SIZE_PCT', '0.05')),
        'MAX_POSITIONS':          int(os.getenv('MAX_POSITIONS', '10')),
        'INITIAL_CAPITAL':        float(os.getenv('INITIAL_CAPITAL', '1000000')),
        'ACTIVATION_PROFIT_PCT':  float(os.getenv('ACTIVATION_PROFIT_PCT', '0.02')),
        'TRAIL_ATR_MULTIPLIER':   float(os.getenv('TRAIL_ATR_MULTIPLIER', '1.5')),
        'TRAIL_PCT':              float(os.getenv('TRAIL_PCT', '0.03')),
        'SYMBOLS': [
            'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
            'KOTAKBANK', 'SBIN', 'BHARTIARTL', 'ITC', 'HINDUNILVR'
        ]
    }

    orchestrator = AlphaZeroOrchestrator(config)

    try:
        orchestrator.start()
    except KeyboardInterrupt:
        orchestrator.stop()


if __name__ == "__main__":
    main()
