"""
AlphaZero Capital — Email Reporter
src/reporting/email_reporter.py

Sends trading reports via email with PDF attachments.

Setup in .env:
  EMAIL_SENDER=yourbot@gmail.com
  EMAIL_PASSWORD=your_app_password      # Gmail: use App Password, not account password
  EMAIL_RECIPIENT=you@example.com
  EMAIL_SMTP_HOST=smtp.gmail.com        # default
  EMAIL_SMTP_PORT=587                   # default

Gmail setup:
  1. Enable 2FA on your Google account
  2. Go to myaccount.google.com → Security → App Passwords
  3. Create an App Password for "Mail"
  4. Use that 16-char password as EMAIL_PASSWORD

Other providers:
  Outlook:  SMTP_HOST=smtp.office365.com  PORT=587
  Yahoo:    SMTP_HOST=smtp.mail.yahoo.com  PORT=587
  Custom:   Set any SMTP_HOST + PORT
"""

from __future__ import annotations
import os, logging, smtplib, threading
from email.mime.multipart  import MIMEMultipart
from email.mime.text       import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


class EmailReporter:
    """Sends PDF reports and alert emails."""

    def __init__(self):
        self.sender    = os.getenv('EMAIL_SENDER', '')
        self.password  = os.getenv('EMAIL_PASSWORD', '')
        self.recipient = os.getenv('EMAIL_RECIPIENT', '')
        self.smtp_host = os.getenv('EMAIL_SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('EMAIL_SMTP_PORT', '587'))
        self._enabled  = bool(self.sender and self.password and self.recipient)

        if not self._enabled:
            logger.warning("EmailReporter: disabled (EMAIL_SENDER / EMAIL_PASSWORD / EMAIL_RECIPIENT not set)")
        else:
            logger.info(f"EmailReporter: active → {self.recipient}")

    # ── Public API ─────────────────────────────────────────────────────────────

    def send_daily_report(self, pdf_path: str, stats: dict):
        """Send end-of-day report with PDF attachment (non-blocking)."""
        if not self._enabled: return
        date_str = datetime.now().strftime('%d %b %Y')
        pnl      = stats.get('daily_pnl', 0)
        pnl_pct  = stats.get('daily_pnl_pct', 0)
        pnl_sign = "+" if pnl >= 0 else ""
        trades   = stats.get('total_trades', 0)
        wr       = stats.get('win_rate', 0) * 100

        subject  = f"AlphaZero Capital | Daily Report {date_str} | P&L: {pnl_sign}Rs.{abs(pnl):,.0f} ({pnl_sign}{pnl_pct:.2f}%)"

        html = self._build_html(
            title   = f"Daily Report — {date_str}",
            summary = f"""
                <tr><td>Daily P&L</td>
                    <td style="color:{'#00ff88' if pnl >= 0 else '#ff3366'}">
                        {pnl_sign}Rs.{abs(pnl):,.0f} ({pnl_sign}{pnl_pct:.2f}%)</td></tr>
                <tr><td>Portfolio Value</td><td>Rs.{stats.get('portfolio_value',0):,.0f}</td></tr>
                <tr><td>Trades Today</td><td>{trades}</td></tr>
                <tr><td>Win Rate</td><td>{wr:.1f}%</td></tr>
                <tr><td>Market Regime</td><td>{stats.get('regime','UNKNOWN')}</td></tr>
                <tr><td>Mode</td><td>{stats.get('mode','PAPER')}</td></tr>
            """,
            note = "Full breakdown attached as PDF."
        )
        threading.Thread(
            target=self._send,
            args=(subject, html, pdf_path),
            daemon=True
        ).start()

    def send_weekly_report(self, pdf_path: str, stats: dict):
        """Send weekly report with PDF attachment."""
        if not self._enabled: return
        week     = stats.get('week', datetime.now().strftime('W%W'))
        pnl      = stats.get('weekly_pnl', 0)
        subject  = f"AlphaZero Capital | Weekly Report {week} | P&L: Rs.{pnl:+,.0f}"

        html = self._build_html(
            title   = f"Weekly Report — {week}",
            summary = f"""
                <tr><td>Weekly P&L</td>
                    <td style="color:{'#00ff88' if pnl >= 0 else '#ff3366'}">Rs.{pnl:+,.0f}</td></tr>
                <tr><td>Total Trades</td><td>{stats.get('total_trades',0)}</td></tr>
                <tr><td>Win Rate</td><td>{stats.get('win_rate',0)*100:.1f}%</td></tr>
                <tr><td>Profit Factor</td><td>{stats.get('profit_factor',0):.2f}</td></tr>
                <tr><td>Best Agent</td><td>{stats.get('best_agent','—')}</td></tr>
            """,
            note = "Full weekly analysis attached as PDF."
        )
        threading.Thread(
            target=self._send,
            args=(subject, html, pdf_path),
            daemon=True
        ).start()

    def send_alert(self, subject: str, message: str):
        """Send a plain-text alert email."""
        if not self._enabled: return
        html = self._build_html(
            title   = subject,
            summary = f"<tr><td colspan='2'>{message}</td></tr>",
            note    = ""
        )
        threading.Thread(
            target=self._send,
            args=(f"AlphaZero Alert | {subject}", html, None),
            daemon=True
        ).start()

    def is_enabled(self) -> bool:
        return self._enabled

    # ── Internals ─────────────────────────────────────────────────────────────

    def _build_html(self, title: str, summary: str, note: str) -> str:
        return f"""
        <!DOCTYPE html><html><head><meta charset="UTF-8"></head>
        <body style="background:#0f1419;color:#e0e0e0;font-family:Segoe UI,Arial,sans-serif;padding:0;margin:0">
          <div style="max-width:640px;margin:0 auto;padding:20px">
            <!-- Header -->
            <div style="background:linear-gradient(135deg,#1e2330,#2a3142);padding:28px 32px;border-radius:16px 16px 0 0;border-bottom:3px solid #00d4ff">
              <h1 style="margin:0;background:linear-gradient(135deg,#00d4ff,#00ff88);
                         -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                         font-size:1.6em">🚀 AlphaZero Capital v17</h1>
              <p style="margin:8px 0 0;color:#888;font-size:.85em">{title}</p>
            </div>
            <!-- Body -->
            <div style="background:#1a1f2e;padding:28px 32px">
              <table style="width:100%;border-collapse:collapse">
                <thead>
                  <tr style="background:#1e2330">
                    <th style="color:#00d4ff;padding:10px 14px;text-align:left;font-size:.8em;
                               text-transform:uppercase;letter-spacing:1px">Metric</th>
                    <th style="color:#00d4ff;padding:10px 14px;text-align:left;font-size:.8em;
                               text-transform:uppercase;letter-spacing:1px">Value</th>
                  </tr>
                </thead>
                <tbody style="font-size:.95em">
                  {summary}
                </tbody>
              </table>
              {'<p style="margin:20px 0 0;color:#888;font-size:.85em;border-top:1px solid #2a3142;padding-top:16px">'+note+'</p>' if note else ''}
            </div>
            <!-- Footer -->
            <div style="background:#1e2330;padding:16px 32px;border-radius:0 0 16px 16px;
                        text-align:center;color:#555;font-size:.78em">
              AlphaZero Capital v17 &mdash; Autonomous NSE Trading System<br>
              Generated: {datetime.now().strftime('%d %b %Y %H:%M:%S IST')}
            </div>
          </div>
        </body></html>
        """

    def _send(self, subject: str, html: str, pdf_path: Optional[str]):
        """Build and send the email (blocking, run in thread)."""
        try:
            msg = MIMEMultipart('alternative' if not pdf_path else 'mixed')
            msg['Subject'] = subject
            msg['From']    = self.sender
            msg['To']      = self.recipient

            msg.attach(MIMEText(html, 'html'))

            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, 'rb') as f:
                    att = MIMEApplication(f.read(), _subtype='pdf')
                att.add_header('Content-Disposition', 'attachment',
                               filename=os.path.basename(pdf_path))
                msg.attach(att)

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as s:
                s.ehlo()
                s.starttls()
                s.login(self.sender, self.password)
                s.sendmail(self.sender, self.recipient, msg.as_string())

            logger.info(f"Email sent: {subject}")

        except Exception as e:
            logger.error(f"Email send failed: {e}")
