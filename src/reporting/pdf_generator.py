"""
AlphaZero Capital — PDF Report Generator
src/reporting/pdf_generator.py

Generates professional trading performance reports as PDF files.
Uses reportlab (already in requirements.txt via dependencies).

Report types:
  - Daily End-of-Day Report
  - Weekly Performance Report
  - Agent Scorecard Report
  - Portfolio Snapshot
"""

from __future__ import annotations
import os, logging
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# ── Colour palette (dark-finance theme) ──────────────────────────────────────
_BG     = (0.06, 0.08, 0.10)   # near-black
_PANEL  = (0.11, 0.13, 0.18)
_CYAN   = (0.0,  0.83, 1.0)
_GREEN  = (0.0,  1.0,  0.53)
_RED    = (1.0,  0.2,  0.4)
_AMBER  = (1.0,  0.67, 0.0)
_WHITE  = (1.0,  1.0,  1.0)
_GREY   = (0.55, 0.55, 0.55)


def _inr(n: float) -> str:
    return f"Rs.{abs(n):,.0f}"

def _pct(n: float) -> str:
    return f"{'+'if n>=0 else ''}{n:.2f}%"


class PDFReportGenerator:
    """Generates PDF reports for AlphaZero Capital."""

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or os.path.join(
            os.path.dirname(__file__), '..', '..', 'logs', 'reports'
        )
        os.makedirs(self.output_dir, exist_ok=True)
        self._check_reportlab()

    def _check_reportlab(self):
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
        except ImportError:
            raise ImportError("Run: pip install reportlab")

    # ── Public API ────────────────────────────────────────────────────────────

    def daily_report(self, data: Dict[str, Any]) -> str:
        """
        Generate end-of-day PDF report.

        data keys:
          date, portfolio_value, initial_capital, daily_pnl, daily_pnl_pct,
          total_trades, winning_trades, losing_trades,
          trades (list of dicts), agent_performance (dict),
          regime, top_signals (list), suggestions (list)

        Returns: path to generated PDF.
        """
        date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        filename = f"daily_report_{date_str}.pdf"
        path     = os.path.join(self.output_dir, filename)

        from reportlab.pdfgen import canvas as rlcanvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm

        W, H = A4
        c = rlcanvas.Canvas(path, pagesize=A4)

        # ── Page 1: Summary ──────────────────────────────────────────────────
        self._draw_background(c, W, H)
        self._draw_header(c, W, H, f"Daily Report — {date_str}", "AlphaZero Capital v17")
        y = H - 5*cm

        # Metric boxes
        portfolio = data.get('portfolio_value', 0)
        initial   = data.get('initial_capital', 1_000_000)
        pnl       = data.get('daily_pnl', 0)
        pnl_pct   = data.get('daily_pnl_pct', 0)
        total_gain = portfolio - initial

        boxes = [
            ("Portfolio Value",  _inr(portfolio),   _CYAN),
            ("Daily P&L",        f"{_inr(pnl)} ({_pct(pnl_pct)})", _GREEN if pnl >= 0 else _RED),
            ("Total Gain",       f"{_inr(total_gain)} ({_pct(total_gain/initial*100)})", _GREEN if total_gain >= 0 else _RED),
            ("Trades Today",     str(data.get('total_trades', 0)), _AMBER),
        ]
        y = self._draw_metric_boxes(c, W, y, boxes)
        y -= 0.5*cm

        # Trade stats
        total  = data.get('total_trades', 0)
        wins   = data.get('winning_trades', 0)
        losses = data.get('losing_trades', 0)
        wr     = wins/total*100 if total else 0

        y = self._draw_section_title(c, 2*cm, y, "Trade Statistics")
        stats = [
            ("Total Trades", str(total)),
            ("Winning Trades", str(wins)),
            ("Losing Trades", str(losses)),
            ("Win Rate", f"{wr:.1f}%"),
            ("Market Regime", data.get('regime', 'UNKNOWN')),
        ]
        y = self._draw_key_value_grid(c, W, y, stats)

        # Trades table
        y -= 0.3*cm
        trades = data.get('trades', [])
        if trades:
            y = self._draw_section_title(c, 2*cm, y, "Today's Trades")
            headers = ["Symbol", "Side", "Qty", "Entry", "Exit", "P&L", "Strategy"]
            rows = [
                [t.get('symbol',''), t.get('side',''), str(t.get('qty',0)),
                 _inr(t.get('entry',0)), _inr(t.get('exit',0)),
                 _inr(t.get('pnl',0)), t.get('strategy','')]
                for t in trades[:15]
            ]
            y = self._draw_table(c, W, y, headers, rows)

        c.showPage()

        # ── Page 2: Agent Performance ─────────────────────────────────────────
        self._draw_background(c, W, H)
        self._draw_header(c, W, H, f"Agent Performance — {date_str}", "AlphaZero Capital v17")
        y = H - 5*cm

        y = self._draw_section_title(c, 2*cm, y, "Agent Scorecards")
        agent_perf = data.get('agent_performance', {})
        if agent_perf:
            headers = ["Agent", "Signals", "Win Rate", "P&L", "Accuracy", "Status"]
            rows = [
                [name,
                 str(a.get('signals_generated', 0)),
                 f"{a.get('win_rate', 0):.0%}",
                 _inr(a.get('pnl', 0)),
                 f"{a.get('accuracy', 0):.0%}",
                 "✓ Active" if a.get('active', True) else "✗ Paused"]
                for name, a in agent_perf.items()
            ]
            y = self._draw_table(c, W, y, headers, rows)

        # Suggestions
        suggestions = data.get('suggestions', [])
        if suggestions:
            y -= 0.5*cm
            y = self._draw_section_title(c, 2*cm, y, "AI Suggestions for Tomorrow")
            for i, s in enumerate(suggestions[:8], 1):
                y = self._draw_bullet(c, 2*cm, y, f"{i}. {s}")

        c.showPage()

        # ── Page 3: Portfolio & Signals ───────────────────────────────────────
        self._draw_background(c, W, H)
        self._draw_header(c, W, H, f"Portfolio Snapshot — {date_str}", "AlphaZero Capital v17")
        y = H - 5*cm

        positions = data.get('positions', [])
        if positions:
            y = self._draw_section_title(c, 2*cm, y, "Open Positions")
            headers = ["Symbol", "Side", "Qty", "Entry", "Current", "Stop", "P&L"]
            rows = [[p.get('symbol',''), p.get('side',''), str(p.get('quantity',0)),
                     _inr(p.get('entry_price',0)), _inr(p.get('current_price',0)),
                     _inr(p.get('stop_loss',0)), _inr(p.get('unrealised_pnl',0))]
                    for p in positions]
            y = self._draw_table(c, W, y, headers, rows)

        signals = data.get('top_signals', [])
        if signals:
            y -= 0.5*cm
            y = self._draw_section_title(c, 2*cm, y, "Top Signals (Last 24h)")
            headers = ["Symbol", "Signal", "Strength", "Source", "MTF", "Time"]
            rows = [[s.get('symbol',''), s.get('signal',''), f"{s.get('strength',0):.0%}",
                     s.get('source',''), '✓' if s.get('mtf_confirmed') else '—',
                     s.get('timestamp','')]
                    for s in signals[:10]]
            y = self._draw_table(c, W, y, headers, rows)

        self._draw_footer(c, W)
        c.save()
        logger.info(f"PDF report saved: {path}")
        return path

    def weekly_report(self, data: Dict[str, Any]) -> str:
        """Generate weekly performance PDF."""
        week_str = data.get('week', datetime.now().strftime('%Y-W%W'))
        filename = f"weekly_report_{week_str}.pdf"
        path     = os.path.join(self.output_dir, filename)

        from reportlab.pdfgen import canvas as rlcanvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm

        W, H = A4
        c = rlcanvas.Canvas(path, pagesize=A4)
        self._draw_background(c, W, H)
        self._draw_header(c, W, H, f"Weekly Report — {week_str}", "AlphaZero Capital v17")
        y = H - 5*cm

        boxes = [
            ("Week P&L",    f"{_inr(data.get('weekly_pnl',0))} ({_pct(data.get('weekly_pnl_pct',0))})", _GREEN if data.get('weekly_pnl',0) >= 0 else _RED),
            ("Total Trades", str(data.get('total_trades',0)), _CYAN),
            ("Win Rate",     f"{data.get('win_rate',0)*100:.1f}%", _AMBER),
            ("Profit Factor",f"{data.get('profit_factor',0):.2f}", _GREEN),
        ]
        y = self._draw_metric_boxes(c, W, y, boxes)

        # Daily breakdown
        daily = data.get('daily_breakdown', [])
        if daily:
            y -= 0.5*cm
            y = self._draw_section_title(c, 2*cm, y, "Daily Breakdown")
            headers = ["Date", "P&L", "Trades", "Win Rate", "Regime"]
            rows = [[d.get('date',''), _inr(d.get('pnl',0)), str(d.get('trades',0)),
                     f"{d.get('win_rate',0)*100:.0f}%", d.get('regime','')]
                    for d in daily]
            y = self._draw_table(c, W, y, headers, rows)

        # Agent leaderboard
        agents = data.get('agent_leaderboard', [])
        if agents:
            y -= 0.5*cm
            y = self._draw_section_title(c, 2*cm, y, "Agent Leaderboard")
            headers = ["Rank", "Agent", "P&L", "Win Rate", "Signals", "Score"]
            rows = [[str(i+1), a.get('name',''), _inr(a.get('pnl',0)),
                     f"{a.get('win_rate',0)*100:.1f}%", str(a.get('signals',0)),
                     f"{a.get('score',0):.1f}"]
                    for i, a in enumerate(agents)]
            y = self._draw_table(c, W, y, headers, rows)

        self._draw_footer(c, W)
        c.save()
        logger.info(f"Weekly PDF saved: {path}")
        return path

    # ── Drawing helpers ───────────────────────────────────────────────────────

    def _draw_background(self, c, W, H):
        from reportlab.lib.units import cm
        c.setFillColorRGB(*_BG)
        c.rect(0, 0, W, H, fill=1, stroke=0)

    def _draw_header(self, c, W, H, title: str, subtitle: str):
        from reportlab.lib.units import cm
        # Header bar
        c.setFillColorRGB(*_PANEL)
        c.rect(0, H-3.5*cm, W, 3.5*cm, fill=1, stroke=0)
        # Accent line
        c.setFillColorRGB(*_CYAN)
        c.rect(0, H-3.5*cm, W, 0.08*cm, fill=1, stroke=0)
        c.setFillColorRGB(*_CYAN)
        c.setFont("Helvetica-Bold", 20)
        c.drawString(2*cm, H-2*cm, title)
        c.setFillColorRGB(*_GREY)
        c.setFont("Helvetica", 10)
        c.drawString(2*cm, H-2.8*cm, f"{subtitle}  |  Generated: {datetime.now().strftime('%d %b %Y %H:%M')}")

    def _draw_metric_boxes(self, c, W, y, boxes):
        from reportlab.lib.units import cm
        box_w = (W - 4*cm) / len(boxes)
        x     = 2*cm
        box_h = 2.2*cm
        for label, value, colour in boxes:
            c.setFillColorRGB(*_PANEL)
            c.roundRect(x, y-box_h, box_w-0.3*cm, box_h, 8, fill=1, stroke=0)
            c.setFillColorRGB(*_GREY)
            c.setFont("Helvetica", 8)
            c.drawString(x+0.3*cm, y-0.5*cm, label.upper())
            c.setFillColorRGB(*colour)
            c.setFont("Helvetica-Bold", 13)
            c.drawString(x+0.3*cm, y-1.4*cm, value)
            x += box_w
        return y - box_h - 0.3*cm

    def _draw_section_title(self, c, x, y, title: str):
        from reportlab.lib.units import cm
        c.setFillColorRGB(*_CYAN)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x, y, title)
        c.setFillColorRGB(*_CYAN)
        c.setLineWidth(0.5)
        c.setStrokeColorRGB(*_CYAN)
        c.line(x, y-0.15*cm, x+16*cm, y-0.15*cm)
        return y - 0.7*cm

    def _draw_key_value_grid(self, c, W, y, items):
        from reportlab.lib.units import cm
        col_w = (W - 4*cm) / 3
        x = 2*cm; row_y = y
        for i, (k, v) in enumerate(items):
            if i > 0 and i % 3 == 0:
                row_y -= 0.8*cm; x = 2*cm
            c.setFillColorRGB(*_GREY); c.setFont("Helvetica", 8)
            c.drawString(x, row_y, k)
            c.setFillColorRGB(*_WHITE); c.setFont("Helvetica-Bold", 10)
            c.drawString(x, row_y-0.35*cm, v)
            x += col_w
        return row_y - 1*cm

    def _draw_table(self, c, W, y, headers, rows):
        from reportlab.lib.units import cm
        col_w  = (W - 4*cm) / len(headers)
        row_h  = 0.55*cm
        x0     = 2*cm

        # Header row
        c.setFillColorRGB(*_PANEL)
        c.rect(x0, y-row_h, W-4*cm, row_h, fill=1, stroke=0)
        c.setFillColorRGB(*_CYAN); c.setFont("Helvetica-Bold", 8)
        for i, h in enumerate(headers):
            c.drawString(x0+i*col_w+0.15*cm, y-row_h+0.15*cm, h)
        y -= row_h

        # Data rows
        for ri, row in enumerate(rows):
            bg = _PANEL if ri % 2 == 0 else (0.08, 0.10, 0.14)
            c.setFillColorRGB(*bg)
            c.rect(x0, y-row_h, W-4*cm, row_h, fill=1, stroke=0)
            for ci, cell in enumerate(row):
                # Colour P&L cells
                if "Rs." in str(cell):
                    val = str(cell).replace("Rs.","").replace(",","")
                    try:
                        colour = _GREEN if float(val) >= 0 else _RED
                    except ValueError:
                        colour = _WHITE
                else:
                    colour = _WHITE
                c.setFillColorRGB(*colour)
                c.setFont("Helvetica", 8)
                c.drawString(x0+ci*col_w+0.15*cm, y-row_h+0.15*cm, str(cell)[:18])
            y -= row_h
            if y < 3*cm:
                c.showPage()
                self._draw_background(c, W, c._pagesize[1])
                y = c._pagesize[1] - 2*cm

        return y - 0.2*cm

    def _draw_bullet(self, c, x, y, text: str):
        from reportlab.lib.units import cm
        c.setFillColorRGB(*_CYAN); c.setFont("Helvetica-Bold", 9)
        c.drawString(x, y, "•")
        c.setFillColorRGB(*_WHITE); c.setFont("Helvetica", 9)
        # Wrap text at 80 chars
        max_w = 140
        words = text.split()
        line  = ""; lines = []
        for word in words:
            if len(line) + len(word) + 1 <= max_w:
                line += (" " if line else "") + word
            else:
                lines.append(line); line = word
        if line: lines.append(line)
        for li, l in enumerate(lines):
            c.drawString(x+0.4*cm, y - li*0.4*cm, l)
        return y - len(lines)*0.4*cm - 0.15*cm

    def _draw_footer(self, c, W):
        from reportlab.lib.units import cm
        c.setFillColorRGB(*_GREY); c.setFont("Helvetica", 8)
        c.drawCentredString(W/2, 1.5*cm, "AlphaZero Capital v17  |  Autonomous NSE Trading System  |  PAPER MODE")
        c.setFillColorRGB(*_PANEL)
        c.rect(0, 0, W, 1.2*cm, fill=1, stroke=0)
        c.setFillColorRGB(*_CYAN)
        c.rect(0, 1.2*cm, W, 0.06*cm, fill=1, stroke=0)
