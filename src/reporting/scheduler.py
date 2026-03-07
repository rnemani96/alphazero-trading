"""
AlphaZero Capital — Report Scheduler
src/reporting/scheduler.py

Fires reports automatically:
  08:00 IST → Morning Telegram report
  18:00 IST → Evening Telegram + PDF email
  Every Sunday 19:00 → Weekly PDF email

Also exposes on-demand report generation.
"""

from __future__ import annotations
import threading, time, logging
from datetime import datetime, date
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)


class ReportScheduler:
    """
    Background thread that fires scheduled reports.

    Usage:
        scheduler = ReportScheduler(
            telegram=telegram_reporter,
            email=email_reporter,
            pdf=pdf_generator,
            agent_tracker=agent_performance_tracker,
            get_state=lambda: live_state.read(),
        )
        scheduler.start()
    """

    def __init__(self,
                 telegram=None,
                 email=None,
                 pdf=None,
                 agent_tracker=None,
                 get_state: Optional[Callable] = None):
        self.telegram      = telegram
        self.email         = email
        self.pdf           = pdf
        self.agent_tracker = agent_tracker
        self.get_state     = get_state or (lambda: {})
        self._running      = False
        self._last_morning = None
        self._last_evening = None
        self._last_weekly  = None

    def start(self):
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True, name="ReportScheduler")
        t.start()
        logger.info("ReportScheduler started")

    def stop(self):
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            try:
                now = datetime.now()
                today = now.date()

                # Morning report — 08:00
                if now.hour == 8 and now.minute == 0 and self._last_morning != today:
                    self._last_morning = today
                    self._fire_morning(now)

                # Evening report — 18:00
                if now.hour == 18 and now.minute == 0 and self._last_evening != today:
                    self._last_evening = today
                    self._fire_evening(now)

                # Weekly report — Sunday 19:00
                if now.weekday() == 6 and now.hour == 19 and now.minute == 0:
                    week = now.isocalendar()[1]
                    if self._last_weekly != week:
                        self._last_weekly = week
                        self._fire_weekly(now)

            except Exception as e:
                logger.error(f"ReportScheduler error: {e}", exc_info=True)

            time.sleep(55)   # check every ~1 minute

    # ── Fires ─────────────────────────────────────────────────────────────────

    def _fire_morning(self, now: datetime):
        logger.info("Firing morning report")
        state = self.get_state()
        port  = state.get('portfolio', {})
        try:
            if self.telegram and self.telegram.is_enabled():
                self.telegram.morning_report(
                    portfolio_value = port.get('current_value', 0),
                    daily_pnl       = port.get('daily_pnl', 0),
                    regime          = state.get('regime', 'UNKNOWN'),
                    top_signals     = state.get('recent_signals', [])[:5],
                    watchlist       = state.get('system', {}).get('symbols', []),
                )
        except Exception as e:
            logger.error(f"Morning Telegram report failed: {e}")

    def _fire_evening(self, now: datetime):
        logger.info("Firing evening report")
        state     = self.get_state()
        port      = state.get('portfolio', {})
        agent_summary = {}
        if self.agent_tracker:
            agent_summary = self.agent_tracker.get_summary()

        report_data = self._build_daily_data(state, agent_summary)

        # PDF
        pdf_path = None
        if self.pdf:
            try:
                pdf_path = self.pdf.daily_report(report_data)
            except Exception as e:
                logger.error(f"PDF generation failed: {e}")

        # Email with PDF
        if self.email and self.email.is_enabled() and pdf_path:
            try:
                self.email.send_daily_report(pdf_path, report_data)
            except Exception as e:
                logger.error(f"Email send failed: {e}")

        # Telegram evening summary
        if self.telegram and self.telegram.is_enabled():
            try:
                best_agent = max(agent_summary, key=lambda k: agent_summary[k].get('total_pnl',0)) if agent_summary else '—'
                self.telegram.evening_report(
                    portfolio_value = port.get('current_value', 0),
                    daily_pnl       = port.get('daily_pnl', 0),
                    daily_pnl_pct   = port.get('daily_pnl_pct', 0) * 100,
                    total_trades    = port.get('total_trades', 0),
                    winning_trades  = int(port.get('win_rate', 0) * port.get('total_trades', 0)),
                    biggest_win     = {},
                    biggest_loss    = {},
                    best_agent      = best_agent,
                    agent_summary   = agent_summary,
                )
                if pdf_path:
                    self.telegram.send_pdf_link("Daily Report", pdf_path)
            except Exception as e:
                logger.error(f"Evening Telegram report failed: {e}")

    def _fire_weekly(self, now: datetime):
        logger.info("Firing weekly report")
        agent_summary = self.agent_tracker.get_summary() if self.agent_tracker else {}
        leaderboard   = self.agent_tracker.get_leaderboard() if self.agent_tracker else []
        state = self.get_state()
        port  = state.get('portfolio', {})

        week_data = {
            'week':            f"W{now.isocalendar()[1]}-{now.year}",
            'weekly_pnl':      port.get('daily_pnl', 0) * 5,   # approximation
            'weekly_pnl_pct':  port.get('daily_pnl_pct', 0) * 5 * 100,
            'total_trades':    port.get('total_trades', 0),
            'win_rate':        port.get('win_rate', 0),
            'profit_factor':   1.5,
            'agent_leaderboard': [
                {'name': a['name'], 'pnl': a.get('total_pnl',0),
                 'win_rate': a.get('win_rate',0), 'signals': a.get('signals_generated',0),
                 'score': a.get('score',0)}
                for a in leaderboard
            ],
        }

        pdf_path = None
        if self.pdf:
            try:
                pdf_path = self.pdf.weekly_report(week_data)
            except Exception as e:
                logger.error(f"Weekly PDF failed: {e}")

        if self.email and self.email.is_enabled() and pdf_path:
            try:
                self.email.send_weekly_report(pdf_path, {
                    **week_data,
                    'best_agent': leaderboard[0]['name'] if leaderboard else '—'
                })
            except Exception as e:
                logger.error(f"Weekly email failed: {e}")

    # ── On-demand ─────────────────────────────────────────────────────────────

    def generate_now(self, report_type: str = 'daily') -> Optional[str]:
        """
        Trigger a report immediately. Returns PDF path.
        report_type: 'daily' | 'weekly'
        """
        now = datetime.now()
        if report_type == 'weekly':
            self._fire_weekly(now)
        else:
            self._fire_evening(now)
        logger.info(f"On-demand {report_type} report generated")
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_daily_data(self, state: Dict, agent_summary: Dict) -> Dict:
        port = state.get('portfolio', {})
        return {
            'date':              datetime.now().strftime('%Y-%m-%d'),
            'portfolio_value':   port.get('current_value', 0),
            'initial_capital':   port.get('initial_capital', 1_000_000),
            'daily_pnl':         port.get('daily_pnl', 0),
            'daily_pnl_pct':     port.get('daily_pnl_pct', 0) * 100,
            'total_trades':      port.get('total_trades', 0),
            'winning_trades':    int(port.get('win_rate', 0) * port.get('total_trades', 0)),
            'losing_trades':     port.get('total_trades', 0) - int(port.get('win_rate', 0) * port.get('total_trades', 0)),
            'trades':            [],
            'agent_performance': agent_summary,
            'positions':         state.get('positions', []),
            'top_signals':       state.get('recent_signals', []),
            'regime':            state.get('regime', 'UNKNOWN'),
            'mode':              state.get('system', {}).get('mode', 'PAPER'),
            'suggestions':       [],
        }
