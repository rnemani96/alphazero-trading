"""
LENS — Agent Evaluation Engine
Tracks every signal against real market outcomes.
Awards points for accuracy. Feeds results to KARMA (RL) for learning.
This is the core feedback loop that prevents live trading losses.
"""
import json
import sqlite3
import logging
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional
from pathlib import Path

logger = logging.getLogger("LENS")

# FIX: absolute path — relative "logs/" breaks when run from any dir except project root
DB_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "evaluation.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class SignalRecord:
    """A signal logged at emission time, evaluated later."""
    id:              str
    symbol:          str
    strategy_id:     str
    strategy_name:   str
    agent:           str
    direction:       int      # +1 BUY | -1 SELL
    confidence:      float
    entry_price:     float
    stop_loss:       float
    target:          float
    regime:          str
    trade_type:      str
    emitted_at:      str      # ISO datetime
    evaluated_at:    Optional[str] = None
    outcome:         Optional[str] = None   # WIN | LOSS | SCRATCH | EXPIRED
    exit_price:      Optional[float] = None
    actual_pnl_pct:  Optional[float] = None
    points_awarded:  Optional[float] = None
    lesson:          Optional[str] = None


@dataclass
class AgentScore:
    agent_id:        str
    total_signals:   int   = 0
    wins:            int   = 0
    losses:          int   = 0
    scratches:       int   = 0
    total_points:    float = 0.0
    win_rate:        float = 0.0
    avg_pnl_pct:     float = 0.0
    best_strategy:   str   = ""
    worst_strategy:  str   = ""
    regime_accuracy: dict  = None   # {regime: win_rate}

    def __post_init__(self):
        if self.regime_accuracy is None:
            self.regime_accuracy = {}


class EvaluationEngine:
    """
    LENS evaluates every signal in paper mode against real price data.

    Scoring:
      WIN (target hit before SL):   +confidence * 2 points
      LOSS (SL hit before target):  -confidence * 1 point   (asymmetric — penalise less to encourage signals)
      SCRATCH (neither in 24h):     ±0 points
      EXPIRED (market closed):      0 points

    After N evaluations, KARMA agent gets a report to update RL weights.
    """

    def __init__(self):
        self._lock    = threading.Lock()
        self._pending: dict[str, SignalRecord] = {}
        self._conn    = self._init_db()
        self._load_pending()

    # ── DB setup ──────────────────────────────────────────────────────────

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.execute("""CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY, symbol TEXT, strategy_id TEXT,
            strategy_name TEXT, agent TEXT, direction INTEGER,
            confidence REAL, entry_price REAL, stop_loss REAL,
            target REAL, regime TEXT, trade_type TEXT,
            emitted_at TEXT, evaluated_at TEXT, outcome TEXT,
            exit_price REAL, actual_pnl_pct REAL,
            points_awarded REAL, lesson TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS agent_scores (
            agent_id TEXT PRIMARY KEY, total_signals INTEGER,
            wins INTEGER, losses INTEGER, scratches INTEGER,
            total_points REAL, win_rate REAL, avg_pnl_pct REAL,
            best_strategy TEXT, worst_strategy TEXT,
            regime_accuracy TEXT, updated_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS strategy_performance (
            strategy_id TEXT, regime TEXT, wins INTEGER,
            losses INTEGER, total_pnl_pct REAL,
            PRIMARY KEY (strategy_id, regime)
        )""")
        conn.commit()
        logger.info("LENS: DB initialised at %s", DB_PATH)
        return conn

    def _load_pending(self):
        """Load unevaluated signals from DB on startup.
        FIX: guard against NULL values in required fields — one bad row was
        crashing the entire startup via SignalRecord(**{...}) TypeError."""
        cur = self._conn.execute(
            "SELECT * FROM signals WHERE evaluated_at IS NULL"
        )
        cols = [d[0] for d in cur.description]
        loaded = 0
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            if not d.get("id") or not d.get("symbol"):
                continue
            # Supply defaults for any NULLs in required string/numeric fields
            d.setdefault("strategy_id",   "UNKNOWN")
            d.setdefault("strategy_name", "Unknown")
            d.setdefault("agent",         "TITAN")
            d.setdefault("direction",     1)
            d.setdefault("confidence",    0.5)
            d.setdefault("entry_price",   0.0)
            d.setdefault("stop_loss",     0.0)
            d.setdefault("target",        0.0)
            d.setdefault("regime",        "UNKNOWN")
            d.setdefault("trade_type",    "INTRADAY")
            d.setdefault("emitted_at",    datetime.now().isoformat())
            try:
                rec = SignalRecord(**{k: d[k] for k in SignalRecord.__dataclass_fields__})
                self._pending[rec.id] = rec
                loaded += 1
            except Exception as e:
                logger.warning("LENS: skipping malformed signal row: %s", e)
        logger.info("LENS: %d pending signals loaded from DB", loaded)

    # ── Signal logging ────────────────────────────────────────────────────

    def log_signal(self, signal: SignalRecord):
        """Called by TITAN/APEX when a signal is emitted."""
        with self._lock:
            self._pending[signal.id] = signal
        self._conn.execute("""INSERT OR REPLACE INTO signals
            (id,symbol,strategy_id,strategy_name,agent,direction,
             confidence,entry_price,stop_loss,target,regime,trade_type,emitted_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (signal.id, signal.symbol, signal.strategy_id, signal.strategy_name,
             signal.agent, signal.direction, signal.confidence, signal.entry_price,
             signal.stop_loss, signal.target, signal.regime, signal.trade_type,
             signal.emitted_at))
        self._conn.commit()
        logger.debug("LENS: logged signal %s for %s", signal.strategy_id, signal.symbol)

    # ── Evaluation ────────────────────────────────────────────────────────

    def evaluate_pending(self, live_prices: dict[str, float]):
        """
        Check all pending signals against current prices.
        Call this every time new prices arrive.
        live_prices: {symbol: current_price}
        """
        evaluated = []
        with self._lock:
            pending_copy = dict(self._pending)

        for sig_id, rec in pending_copy.items():
            price = live_prices.get(rec.symbol)
            if price is None:
                continue

            outcome = self._check_outcome(rec, price)
            if outcome:
                rec.evaluated_at  = datetime.now().isoformat()
                rec.outcome       = outcome
                rec.exit_price    = price
                rec.actual_pnl_pct = self._calc_pnl(rec, price)
                rec.points_awarded = self._award_points(rec)
                rec.lesson         = self._generate_lesson(rec)
                evaluated.append(rec)
                with self._lock:
                    del self._pending[sig_id]
                self._save_evaluation(rec)
                self._update_agent_score(rec)
                self._update_strategy_performance(rec)
                logger.info("LENS: %s → %s | %s %s | pnl=%.2f%% pts=%.2f",
                            rec.strategy_id, rec.outcome, rec.symbol,
                            "BUY" if rec.direction > 0 else "SELL",
                            rec.actual_pnl_pct, rec.points_awarded)

        # Expire signals older than 24h (evaluation window)
        self._expire_old_signals()
        return evaluated

    def _check_outcome(self, rec: SignalRecord, price: float) -> Optional[str]:
        """Determine if a signal has resolved (WIN/LOSS/SCRATCH)."""
        emitted = datetime.fromisoformat(rec.emitted_at)
        age_hours = (datetime.now() - emitted).total_seconds() / 3600

        if rec.direction == 1:  # BUY
            if price >= rec.target:   return "WIN"
            if price <= rec.stop_loss: return "LOSS"
        else:                          # SELL
            if price <= rec.target:   return "WIN"
            if price >= rec.stop_loss: return "LOSS"

        if age_hours >= 24:
            return "SCRATCH"
        return None

    def _calc_pnl(self, rec: SignalRecord, exit_price: float) -> float:
        """Return P&L as percentage of entry."""
        if rec.entry_price == 0:
            return 0.0
        raw = (exit_price - rec.entry_price) / rec.entry_price * 100
        return round(raw * rec.direction, 4)

    def _award_points(self, rec: SignalRecord) -> float:
        """Asymmetric scoring: encourage signals, penalise large losses."""
        if rec.outcome == "WIN":
            return round(rec.confidence * 2.0, 3)
        if rec.outcome == "LOSS":
            # Penalise proportional to how far past SL we went
            sl_breach = abs(rec.actual_pnl_pct) if rec.actual_pnl_pct else 0
            penalty = min(rec.confidence * 1.0, rec.confidence * (sl_breach / 2))
            return -round(penalty, 3)
        return 0.0  # SCRATCH / EXPIRED

    def _generate_lesson(self, rec: SignalRecord) -> str:
        """Generate a human-readable lesson for KARMA."""
        if rec.outcome == "WIN":
            return f"{rec.strategy_id} worked in {rec.regime}. Confidence {rec.confidence:.0%} → target hit."
        if rec.outcome == "LOSS":
            return (f"{rec.strategy_id} failed in {rec.regime}. "
                    f"SL breached. Reduce confidence threshold in {rec.regime} for {rec.trade_type}.")
        return f"{rec.strategy_id} inconclusive in {rec.regime} after 24h."

    def _expire_old_signals(self):
        """Mark signals older than 48h as EXPIRED if still pending.
        FIX: snapshot list before iterating; use pop() to avoid KeyError."""
        cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
        with self._lock:
            expired = [s for s in list(self._pending.values()) if s.emitted_at < cutoff]
        for rec in expired:
            rec.evaluated_at   = datetime.now().isoformat()
            rec.outcome        = "EXPIRED"
            rec.points_awarded = 0.0
            rec.lesson         = f"{rec.strategy_id} expired — no resolution in 48h."
            with self._lock:
                self._pending.pop(rec.id, None)
            self._save_evaluation(rec)

    # ── Persistence ───────────────────────────────────────────────────────

    def _save_evaluation(self, rec: SignalRecord):
        self._conn.execute("""UPDATE signals SET
            evaluated_at=?,outcome=?,exit_price=?,actual_pnl_pct=?,
            points_awarded=?,lesson=? WHERE id=?""",
            (rec.evaluated_at, rec.outcome, rec.exit_price,
             rec.actual_pnl_pct, rec.points_awarded, rec.lesson, rec.id))
        self._conn.commit()

    def _update_agent_score(self, rec: SignalRecord):
        """Update rolling agent leaderboard."""
        cur = self._conn.execute(
            "SELECT * FROM agent_scores WHERE agent_id=?", (rec.agent,))
        row = cur.fetchone()
        if row:
            cols = [d[0] for d in cur.description]
            score_dict = dict(zip(cols, row))
            ra = json.loads(score_dict.get("regime_accuracy") or "{}")
        else:
            score_dict = {"agent_id": rec.agent, "total_signals": 0,
                          "wins": 0, "losses": 0, "scratches": 0,
                          "total_points": 0.0, "win_rate": 0.0,
                          "avg_pnl_pct": 0.0, "best_strategy": "",
                          "worst_strategy": "", "regime_accuracy": "{}"}
            ra = {}

        score_dict["total_signals"] += 1
        if rec.outcome == "WIN":    score_dict["wins"]     += 1
        elif rec.outcome == "LOSS": score_dict["losses"]   += 1
        else:                       score_dict["scratches"] += 1

        score_dict["total_points"] = round(score_dict["total_points"] + (rec.points_awarded or 0), 3)
        t = score_dict["total_signals"]
        score_dict["win_rate"] = round(score_dict["wins"] / t, 4) if t > 0 else 0

        # Regime accuracy
        if rec.regime not in ra:
            ra[rec.regime] = {"wins": 0, "total": 0}
        ra[rec.regime]["total"] += 1
        if rec.outcome == "WIN":
            ra[rec.regime]["wins"] += 1

        score_dict["regime_accuracy"] = json.dumps(ra)
        score_dict["updated_at"] = datetime.now().isoformat()

        self._conn.execute("""INSERT OR REPLACE INTO agent_scores
            (agent_id,total_signals,wins,losses,scratches,total_points,
             win_rate,avg_pnl_pct,best_strategy,worst_strategy,regime_accuracy,updated_at)
            VALUES (:agent_id,:total_signals,:wins,:losses,:scratches,:total_points,
                    :win_rate,:avg_pnl_pct,:best_strategy,:worst_strategy,:regime_accuracy,:updated_at)""",
            score_dict)
        self._conn.commit()

    def _update_strategy_performance(self, rec: SignalRecord):
        """Track per-strategy, per-regime win rate."""
        cur = self._conn.execute(
            "SELECT * FROM strategy_performance WHERE strategy_id=? AND regime=?",
            (rec.strategy_id, rec.regime))
        row = cur.fetchone()
        if row:
            wins = row[2] + (1 if rec.outcome == "WIN" else 0)
            losses = row[3] + (1 if rec.outcome == "LOSS" else 0)
            total_pnl = row[4] + (rec.actual_pnl_pct or 0)
        else:
            wins = 1 if rec.outcome == "WIN" else 0
            losses = 1 if rec.outcome == "LOSS" else 0
            total_pnl = rec.actual_pnl_pct or 0

        self._conn.execute("""INSERT OR REPLACE INTO strategy_performance
            (strategy_id,regime,wins,losses,total_pnl_pct)
            VALUES (?,?,?,?,?)""",
            (rec.strategy_id, rec.regime, wins, losses, total_pnl))
        self._conn.commit()

    # ── Query API ─────────────────────────────────────────────────────────

    def get_agent_scores(self) -> list[dict]:
        """Return all agent scores sorted by total_points desc."""
        cur = self._conn.execute(
            "SELECT * FROM agent_scores ORDER BY total_points DESC")
        cols = [d[0] for d in cur.description]
        rows = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            d["regime_accuracy"] = json.loads(d.get("regime_accuracy") or "{}")
            rows.append(d)
        return rows

    def get_signal_history(self, limit: int = 100) -> list[dict]:
        """Return recent evaluated signals."""
        cur = self._conn.execute(
            "SELECT * FROM signals WHERE outcome IS NOT NULL ORDER BY evaluated_at DESC LIMIT ?",
            (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_strategy_leaderboard(self) -> list[dict]:
        """Best strategies by regime."""
        cur = self._conn.execute("""
            SELECT strategy_id, regime, wins, losses,
                   ROUND(wins*1.0/(wins+losses+0.001),3) as win_rate,
                   ROUND(total_pnl_pct/(wins+losses+0.001),3) as avg_pnl
            FROM strategy_performance
            ORDER BY win_rate DESC, avg_pnl DESC
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_karma_report(self) -> dict:
        """
        Returns structured report for KARMA agent to update RL weights.
        KARMA reads this to avoid repeating losing strategy+regime combinations.
        """
        strategy_lb = self.get_strategy_leaderboard()
        agent_scores = self.get_agent_scores()

        # Strategies to DISABLE (< 40% win rate with > 5 samples)
        disable = [s for s in strategy_lb
                   if (s["wins"] + s["losses"]) >= 5 and s["win_rate"] < 0.40]

        # Best strategy per regime
        best_per_regime = {}
        for s in strategy_lb:
            r = s["regime"]
            if r not in best_per_regime or s["win_rate"] > best_per_regime[r]["win_rate"]:
                best_per_regime[r] = s

        # Regime performance
        regime_perf = {}
        for s in strategy_lb:
            r = s["regime"]
            if r not in regime_perf:
                regime_perf[r] = {"wins": 0, "losses": 0}
            regime_perf[r]["wins"]   += s["wins"]
            regime_perf[r]["losses"] += s["losses"]

        return {
            "generated_at":     datetime.now().isoformat(),
            "strategies_disable": [{"id": s["strategy_id"], "regime": s["regime"],
                                     "win_rate": s["win_rate"]} for s in disable],
            "best_per_regime":  best_per_regime,
            "regime_performance": regime_perf,
            "agent_leaderboard": [{
                "agent":       a["agent_id"],
                "points":      a["total_points"],
                "win_rate":    a["win_rate"],
                "total":       a["total_signals"],
            } for a in agent_scores],
            "pending_signals":   len(self._pending),
        }

    def get_dashboard_stats(self) -> dict:
        """Quick stats for dashboard header."""
        cur = self._conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) as losses,
                   AVG(actual_pnl_pct) as avg_pnl,
                   SUM(points_awarded) as total_points
            FROM signals WHERE outcome IS NOT NULL
        """)
        row = cur.fetchone()
        total = row[0] or 0
        wins  = row[1] or 0
        losses = row[2] or 0
        return {
            "total_evaluated": total,
            "wins":   wins,
            "losses": losses,
            "win_rate": round(wins / total, 4) if total > 0 else 0,
            "avg_pnl_pct": round(row[3] or 0, 3),
            "total_points": round(row[4] or 0, 2),
            "pending": len(self._pending),
        }
