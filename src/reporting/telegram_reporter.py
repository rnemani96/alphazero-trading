"""
AlphaZero Capital — Telegram Reporter
src/reporting/telegram_reporter.py

Sends real-time alerts and scheduled reports to your Telegram chat.

Setup:
  1. Message @BotFather on Telegram → /newbot → copy token
  2. Message your bot once, then run:
       python -c "import requests; print(requests.get('https://api.telegram.org/botYOUR_TOKEN/getUpdates').json())"
  3. Copy your chat_id from the response
  4. Set in .env:
       TELEGRAM_BOT_TOKEN=your_token
       TELEGRAM_CHAT_ID=your_chat_id

Alert types sent:
  🚀 Trade executed      📉 Stop loss hit     🎯 Target reached
  🚨 Risk alert          🌊 Regime change      📰 News alert
  📊 Daily report (8am)  📊 EOD report (6pm)   🔴 Kill switch
"""

from __future__ import annotations
import os, logging, threading, time, json
from datetime import datetime
from typing import Dict, Any, Optional
from queue import Queue, Empty

logger = logging.getLogger(__name__)

# fmt helpers
def _inr(n: float) -> str:
    """Format as ₹ with Indian comma style."""
    return f"₹{abs(n):,.0f}"

def _pct(n: float) -> str:
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:.2f}%"

def _ts() -> str:
    return datetime.now().strftime("%d %b %Y %H:%M:%S")


class TelegramReporter:
    """
    Thread-safe Telegram reporter.

    All public methods are non-blocking — messages are queued and sent
    by a background thread so they never slow down the trading loop.
    """

    def __init__(self, token: str = None, chat_id: str = None):
        self.token   = token   or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._queue: Queue = Queue()
        self._enabled = bool(self.token and self.chat_id)

        if not self._enabled:
            logger.warning("TelegramReporter: disabled (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)")
        else:
            self._worker = threading.Thread(target=self._send_loop, daemon=True, name="TelegramSender")
            self._worker.start()
            logger.info(f"TelegramReporter: active (chat_id={self.chat_id})")

    # ── Public alert methods ──────────────────────────────────────────────────

    def trade_executed(self, symbol: str, side: str, qty: int,
                       price: float, strategy: str, confidence: float,
                       target: float = 0, stop_loss: float = 0):
        icon  = "📈" if side == "BUY" else "📉"
        side_emoji = "🟢 BUY" if side == "BUY" else "🔴 SELL"
        msg = (
            f"{icon} *TRADE EXECUTED*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"*Symbol:*     {symbol}\n"
            f"*Side:*       {side_emoji}\n"
            f"*Qty:*        {qty} shares\n"
            f"*Price:*      {_inr(price)}\n"
            f"*Value:*      {_inr(price * qty)}\n"
            f"*Strategy:*   {strategy}\n"
            f"*Confidence:* {confidence:.0%}\n"
        )
        if target:    msg += f"*Target:*     {_inr(target)}\n"
        if stop_loss: msg += f"*Stop Loss:*  {_inr(stop_loss)}\n"
        msg += f"_🕐 {_ts()}_"
        self._enqueue(msg)

    def stop_loss_hit(self, symbol: str, entry: float, exit_price: float,
                      qty: int, pnl: float):
        msg = (
            f"🛑 *STOP LOSS HIT*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"*Symbol:*  {symbol}\n"
            f"*Entry:*   {_inr(entry)}\n"
            f"*Exit:*    {_inr(exit_price)}\n"
            f"*Qty:*     {qty}\n"
            f"*P&L:*     {_inr(pnl)} 🔴\n"
            f"_🕐 {_ts()}_"
        )
        self._enqueue(msg)

    def target_reached(self, symbol: str, entry: float, exit_price: float,
                       qty: int, pnl: float):
        msg = (
            f"🎯 *TARGET REACHED*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"*Symbol:*  {symbol}\n"
            f"*Entry:*   {_inr(entry)}\n"
            f"*Exit:*    {_inr(exit_price)}\n"
            f"*Qty:*     {qty}\n"
            f"*P&L:*     {_inr(pnl)} 🟢\n"
            f"_🕐 {_ts()}_"
        )
        self._enqueue(msg)

    def risk_alert(self, alert_type: str, detail: str):
        icon = "🚨" if "KILL" in alert_type.upper() else "⚠️"
        msg = (
            f"{icon} *RISK ALERT: {alert_type}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{detail}\n"
            f"_🕐 {_ts()}_"
        )
        self._enqueue(msg)

    def kill_switch_activated(self, reason: str, daily_pnl: float):
        msg = (
            f"🔴🔴 *KILL SWITCH ACTIVATED* 🔴🔴\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"*Reason:*    {reason}\n"
            f"*Daily P&L:* {_inr(daily_pnl)}\n"
            f"*Action:*    All trading STOPPED\n"
            f"_🕐 {_ts()}_"
        )
        self._enqueue(msg, parse_mode="Markdown")

    def regime_change(self, old_regime: str, new_regime: str, impact: str = ""):
        icons = {"TRENDING": "🟢", "SIDEWAYS": "🔵", "VOLATILE": "🟡", "RISK_OFF": "🔴"}
        msg = (
            f"🌊 *REGIME CHANGE*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{icons.get(old_regime,'⚪')} {old_regime} → {icons.get(new_regime,'⚪')} {new_regime}\n"
        )
        if impact: msg += f"*Impact:* {impact}\n"
        msg += f"_🕐 {_ts()}_"
        self._enqueue(msg)

    def options_signal(self, symbol: str, signal: str, strength: float,
                       sweeps: int, dark_pool: str):
        msg = (
            f"💰 *OPTIONS FLOW SIGNAL*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"*Symbol:*     {symbol}\n"
            f"*Signal:*     {signal}\n"
            f"*Strength:*   {strength:.0%}\n"
            f"*Sweeps:*     {sweeps}\n"
            f"*Dark Pool:*  {dark_pool}\n"
            f"_🕐 {_ts()}_"
        )
        self._enqueue(msg)

    def morning_report(self, portfolio_value: float, daily_pnl: float,
                       regime: str, top_signals: list, watchlist: list):
        signals_text = "\n".join(
            f"  • {s['symbol']}: {s['signal']} ({s.get('confidence',0):.0%})"
            for s in top_signals[:5]
        ) or "  None yet"
        watchlist_text = ", ".join(watchlist[:8]) or "—"

        msg = (
            f"🌅 *MORNING REPORT — {datetime.now().strftime('%d %b %Y')}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Portfolio:*  {_inr(portfolio_value)}\n"
            f"*Daily P&L:*  {_inr(daily_pnl)}\n"
            f"*Regime:*     {regime}\n"
            f"\n*Top Signals:*\n{signals_text}\n"
            f"\n*Watchlist:* {watchlist_text}\n"
            f"\n_AlphaZero Capital v17 | Paper Mode_"
        )
        self._enqueue(msg)

    def evening_report(self, portfolio_value: float, daily_pnl: float,
                       daily_pnl_pct: float, total_trades: int,
                       winning_trades: int, biggest_win: Dict,
                       biggest_loss: Dict, best_agent: str,
                       agent_summary: Dict):
        win_rate = (winning_trades / total_trades * 100) if total_trades else 0
        agents_text = "\n".join(
            f"  • {name}: {data.get('win_rate', 0):.0%} WR, {_inr(data.get('pnl', 0))}"
            for name, data in list(agent_summary.items())[:5]
        ) or "  No data"

        msg = (
            f"🌆 *EVENING REPORT — {datetime.now().strftime('%d %b %Y')}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Portfolio:*    {_inr(portfolio_value)}\n"
            f"*Daily P&L:*    {_inr(daily_pnl)} ({_pct(daily_pnl_pct)})\n"
            f"\n*Trades Today:* {total_trades}\n"
            f"*Win Rate:*     {win_rate:.1f}%\n"
        )
        if biggest_win:
            msg += f"*Best Trade:*   {biggest_win.get('symbol','?')} +{_inr(biggest_win.get('pnl',0))}\n"
        if biggest_loss:
            msg += f"*Worst Trade:*  {biggest_loss.get('symbol','?')} {_inr(biggest_loss.get('pnl',0))}\n"
        msg += (
            f"\n*Top Agent:*    {best_agent}\n"
            f"\n*Agent Summary:*\n{agents_text}\n"
            f"\n_Full PDF report sent to email_ 📧"
        )
        self._enqueue(msg)

    def send_message(self, text: str):
        """Send a raw custom message."""
        self._enqueue(text)

    def send_pdf_link(self, report_type: str, filename: str):
        """Notify that a PDF report was generated."""
        msg = (
            f"📄 *{report_type} PDF Ready*\n"
            f"File: `{filename}`\n"
            f"Check your email for the attached report.\n"
            f"_🕐 {_ts()}_"
        )
        self._enqueue(msg)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _enqueue(self, text: str, parse_mode: str = "Markdown"):
        if self._enabled:
            self._queue.put((text, parse_mode))

    def _send_loop(self):
        """Background thread — drains queue and sends messages with retry."""
        while True:
            try:
                text, parse_mode = self._queue.get(timeout=5)
                self._send_now(text, parse_mode)
                self._queue.task_done()
                time.sleep(0.3)   # respect Telegram rate limit (30 msg/s)
            except Empty:
                pass
            except Exception as e:
                logger.error(f"TelegramReporter send error: {e}")

    def _send_now(self, text: str, parse_mode: str = "Markdown", retries: int = 3):
        """Actually POST to Telegram API."""
        import urllib.request, urllib.parse
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = json.dumps({
            "chat_id":    self.chat_id,
            "text":       text,
            "parse_mode": parse_mode,
        }).encode()
        for attempt in range(retries):
            try:
                req = urllib.request.Request(
                    url, data=payload,
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=10):
                    return
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"Telegram send failed after {retries} attempts: {e}")

    def is_enabled(self) -> bool:
        return self._enabled


class TelegramCommandHandler:
    """
    Polls Telegram for bot commands and triggers on-demand reports.

    Supported commands:
        /report  or /daily  → trigger daily report + email now
        /weekly             → trigger weekly report now
        /status             → send current portfolio snapshot
        /help               → list all commands

    Usage:
        handler = TelegramCommandHandler(telegram_reporter, report_scheduler)
        handler.start()  # runs in background thread
    """

    def __init__(self, reporter: 'TelegramReporter', scheduler=None):
        self.reporter  = reporter
        self.scheduler = scheduler
        self._offset   = 0
        self._running  = False

    def start(self):
        if not self.reporter.is_enabled():
            return
        self._running = True
        t = threading.Thread(target=self._poll_loop, daemon=True, name="TelegramCmd")
        t.start()
        logger.info("TelegramCommandHandler started — listening for /report /status /weekly")

    def stop(self):
        self._running = False

    def _poll_loop(self):
        while self._running:
            try:
                self._poll_once()
            except Exception as e:
                logger.error(f"TelegramCommandHandler poll error: {e}")
            time.sleep(5)

    def _poll_once(self):
        import urllib.request
        url = (f"https://api.telegram.org/bot{self.reporter.token}/getUpdates"
               f"?offset={self._offset}&timeout=5&limit=10")
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
        except Exception:
            return

        for update in data.get('result', []):
            self._offset = update['update_id'] + 1
            msg = update.get('message', {})
            text = (msg.get('text') or '').strip().lower().split()[0]  # first word
            cid  = str(msg.get('chat', {}).get('id', ''))

            # Only respond to our configured chat
            if cid != self.reporter.chat_id:
                continue

            if text in ('/report', '/daily'):
                self.reporter.send_message("📄 Generating daily report… will email + send summary shortly.")
                if self.scheduler:
                    self.scheduler.generate_now('daily')

            elif text == '/weekly':
                self.reporter.send_message("📊 Generating weekly report… will email shortly.")
                if self.scheduler:
                    self.scheduler.generate_now('weekly')

            elif text == '/status':
                self._send_status()

            elif text == '/help':
                self.reporter.send_message(
                    "🚀 *AlphaZero Capital v17 Commands*\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "/status  — Portfolio snapshot right now\n"
                    "/report  — Generate daily PDF report\n"
                    "/daily   — Same as /report\n"
                    "/weekly  — Generate weekly PDF report\n"
                    "/help    — Show this message"
                )

    def _send_status(self):
        """Send current portfolio snapshot on demand."""
        try:
            from src.monitoring import state as live_state
            s    = live_state.read()
            port = s.get('portfolio', {})
            pnl  = port.get('daily_pnl', 0)
            self.reporter.send_message(
                f"📊 *Live Status — {_ts()}*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"*Portfolio:*  {_inr(port.get('current_value',0))}\n"
                f"*Daily P&L:*  {_inr(pnl)} ({_pct((port.get('daily_pnl_pct',0))*100)})\n"
                f"*Positions:*  {port.get('open_positions',0)}\n"
                f"*Win Rate:*   {(port.get('win_rate',0)*100):.1f}%\n"
                f"*Regime:*     {s.get('regime','UNKNOWN')}\n"
                f"*Mode:*       {s.get('system',{}).get('mode','PAPER')}"
            )
        except Exception as e:
            self.reporter.send_message(f"Could not fetch status: {e}")
