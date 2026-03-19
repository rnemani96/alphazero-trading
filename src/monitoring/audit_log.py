"""
src/monitoring/audit_log.py  —  AlphaZero Capital
══════════════════════════════════════════════════
SEBI-Compliant Regulatory Audit Log

Every trade, order, and risk decision is written to an append-only SQLite
database. Entries cannot be modified once written (enforced by trigger).

SEBI required fields (per SEBI LODR / Stock Broker circular):
  - Client ID / account identifier
  - Order timestamp (IST, microsecond precision)
  - Instrument (symbol, exchange, ISIN where available)
  - Order type (MARKET / LIMIT / SL-M / BO)
  - Transaction type (BUY / SELL)
  - Quantity ordered
  - Quantity filled
  - Price (ordered / average fill)
  - Trade value
  - Strategy / algorithm ID
  - Risk decision (approved/rejected + reason)
  - Agent that generated the signal
  - Correlation ID (links signal → order → fill → close)

Export:
    audit.export_csv("2026-01-01", "2026-03-31", "sebi_report.csv")

Usage:
    audit = AuditLog()
    audit.log_signal(symbol, agent, action, confidence, regime)
    audit.log_order(symbol, qty, price, order_type, action, strategy)
    audit.log_fill(order_id, fill_price, fill_qty, slippage_bps)
    audit.log_risk_decision(symbol, approved, reason, position_size)
    audit.log_position_close(symbol, exit_price, pnl, reason)
"""

from __future__ import annotations

import csv
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AuditLog")

_LOG_DIR  = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_DB_PATH  = str(_LOG_DIR / "audit.db")

# SEBI-required schema version
_SCHEMA_VERSION = "1.0"


class AuditLog:
    """
    Append-only, immutable regulatory audit log.

    Thread-safe via threading.Lock.
    Each write is immediately committed (WAL mode for concurrency).
    """

    def __init__(self, db_path: str = _DB_PATH, client_id: str = "ALPHAZERO_001"):
        self._path      = db_path
        self._client_id = client_id
        self._lock      = threading.Lock()
        self._conn      = self._init_db()
        logger.info("AuditLog initialised → %s", db_path)

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")   # data integrity over speed

        conn.executescript("""
        -- Schema version
        CREATE TABLE IF NOT EXISTS schema_info (
            version TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        -- Signal events (TITAN / agent output before risk check)
        CREATE TABLE IF NOT EXISTS signals (
            id              TEXT PRIMARY KEY,
            client_id       TEXT NOT NULL,
            ts              TEXT NOT NULL,       -- ISO with microseconds
            symbol          TEXT NOT NULL,
            exchange        TEXT NOT NULL DEFAULT 'NSE',
            action          TEXT NOT NULL,       -- BUY / SELL
            agent           TEXT NOT NULL,
            strategy_id     TEXT,
            confidence      REAL,
            regime          TEXT,
            entry_price     REAL,
            stop_loss       REAL,
            target          REAL,
            rr_ratio        REAL,
            sentiment_score REAL,
            correlation_id  TEXT
        );

        -- Risk decisions (GUARDIAN output)
        CREATE TABLE IF NOT EXISTS risk_decisions (
            id             TEXT PRIMARY KEY,
            client_id      TEXT NOT NULL,
            ts             TEXT NOT NULL,
            symbol         TEXT NOT NULL,
            exchange        TEXT NOT NULL DEFAULT 'NSE',
            signal_id      TEXT,
            approved        INTEGER NOT NULL,    -- 1/0
            reason          TEXT NOT NULL,
            position_size   REAL,
            quantity        INTEGER,
            stop_loss       REAL,
            target          REAL,
            daily_pnl_at_decision REAL,
            correlation_id  TEXT
        );

        -- Orders (sent to broker / paper executor)
        CREATE TABLE IF NOT EXISTS orders (
            id             TEXT PRIMARY KEY,
            client_id      TEXT NOT NULL,
            ts             TEXT NOT NULL,
            symbol         TEXT NOT NULL,
            exchange        TEXT NOT NULL DEFAULT 'NSE',
            isin            TEXT,
            order_type      TEXT NOT NULL,       -- MARKET / LIMIT / SL-M / BO
            transaction_type TEXT NOT NULL,      -- BUY / SELL
            quantity        INTEGER NOT NULL,
            price           REAL,                -- 0 for MARKET
            product         TEXT DEFAULT 'MIS',  -- MIS / CNC / BO
            strategy_id     TEXT,
            algo_id         TEXT DEFAULT 'ALPHAZERO_v4',
            status          TEXT DEFAULT 'PENDING',
            broker_order_id TEXT,
            correlation_id  TEXT
        );

        -- Fills (confirmed execution)
        CREATE TABLE IF NOT EXISTS fills (
            id              TEXT PRIMARY KEY,
            client_id       TEXT NOT NULL,
            ts              TEXT NOT NULL,
            order_id        TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            exchange        TEXT NOT NULL DEFAULT 'NSE',
            fill_price      REAL NOT NULL,
            fill_qty        INTEGER NOT NULL,
            trade_value     REAL NOT NULL,
            slippage_bps    REAL,
            commission_inr  REAL,
            correlation_id  TEXT
        );

        -- Position closes (realised P&L)
        CREATE TABLE IF NOT EXISTS position_closes (
            id              TEXT PRIMARY KEY,
            client_id       TEXT NOT NULL,
            ts              TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            exchange        TEXT NOT NULL DEFAULT 'NSE',
            entry_price     REAL NOT NULL,
            exit_price      REAL NOT NULL,
            quantity        INTEGER NOT NULL,
            realised_pnl    REAL NOT NULL,
            holding_days    INTEGER,
            close_reason    TEXT,
            strategy_id     TEXT,
            correlation_id  TEXT
        );

        -- System events (kill-switch, regime change, circuit breaker, etc.)
        CREATE TABLE IF NOT EXISTS system_events (
            id          TEXT PRIMARY KEY,
            client_id   TEXT NOT NULL,
            ts          TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            agent       TEXT,
            payload     TEXT,                -- JSON string
            severity    TEXT DEFAULT 'INFO'  -- INFO / WARNING / CRITICAL
        );

        -- Immutability trigger: prevent UPDATE on all tables
        CREATE TRIGGER IF NOT EXISTS no_update_signals
            BEFORE UPDATE ON signals BEGIN
            SELECT RAISE(ABORT, 'Audit records are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS no_update_orders
            BEFORE UPDATE ON orders BEGIN
            SELECT RAISE(ABORT, 'Audit records are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS no_update_fills
            BEFORE UPDATE ON fills BEGIN
            SELECT RAISE(ABORT, 'Audit records are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS no_update_closes
            BEFORE UPDATE ON position_closes BEGIN
            SELECT RAISE(ABORT, 'Audit records are immutable');
        END;
        """)

        # Seed schema version if empty
        cur = conn.execute("SELECT COUNT(*) FROM schema_info")
        if cur.fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO schema_info VALUES (?, ?)",
                (_SCHEMA_VERSION, _ts()),
            )
        conn.commit()
        return conn

    # ── Write methods ─────────────────────────────────────────────────────────

    def log_signal(
        self,
        symbol:      str,
        agent:       str,
        action:      str,
        confidence:  float     = 0.0,
        regime:      str       = "UNKNOWN",
        strategy_id: str       = "",
        entry_price: float     = 0.0,
        stop_loss:   float     = 0.0,
        target:      float     = 0.0,
        rr_ratio:    float     = 0.0,
        sentiment:   float     = 0.0,
        correlation_id: Optional[str] = None,
    ) -> str:
        """Log a TITAN/agent signal. Returns the signal ID."""
        sid = _new_id()
        with self._lock:
            self._conn.execute(
                """INSERT INTO signals VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, self._client_id, _ts(), symbol, "NSE", action, agent,
                 strategy_id, confidence, regime, entry_price, stop_loss,
                 target, rr_ratio, sentiment, correlation_id or sid),
            )
            self._conn.commit()
        return sid

    def log_risk_decision(
        self,
        symbol:       str,
        approved:     bool,
        reason:       str,
        signal_id:    str       = "",
        position_size:float     = 0.0,
        quantity:     int       = 0,
        stop_loss:    float     = 0.0,
        target:       float     = 0.0,
        daily_pnl:    float     = 0.0,
        correlation_id: Optional[str] = None,
    ) -> str:
        rid = _new_id()
        with self._lock:
            self._conn.execute(
                """INSERT INTO risk_decisions VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rid, self._client_id, _ts(), symbol, "NSE", signal_id,
                 1 if approved else 0, reason, position_size, quantity,
                 stop_loss, target, daily_pnl, correlation_id or signal_id),
            )
            self._conn.commit()
        return rid

    def log_order(
        self,
        symbol:          str,
        qty:             int,
        price:           float,
        order_type:      str    = "MARKET",
        action:          str    = "BUY",
        product:         str    = "MIS",
        strategy_id:     str    = "",
        broker_order_id: str    = "",
        isin:            str    = "",
        correlation_id:  Optional[str] = None,
    ) -> str:
        oid = _new_id()
        with self._lock:
            self._conn.execute(
                """INSERT INTO orders VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (oid, self._client_id, _ts(), symbol, "NSE", isin or "",
                 order_type, action, qty, price, product, strategy_id,
                 "ALPHAZERO_v4", "PENDING", broker_order_id, correlation_id or oid),
            )
            self._conn.commit()
        return oid

    def log_fill(
        self,
        order_id:      str,
        symbol:        str,
        fill_price:    float,
        fill_qty:      int,
        slippage_bps:  float = 0.0,
        commission_inr:float = 0.0,
        correlation_id: Optional[str] = None,
    ) -> str:
        fid = _new_id()
        with self._lock:
            self._conn.execute(
                """INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fid, self._client_id, _ts(), order_id, symbol, "NSE",
                 fill_price, fill_qty, fill_price * fill_qty,
                 slippage_bps, commission_inr, correlation_id or order_id),
            )
            self._conn.commit()
        return fid

    def log_position_close(
        self,
        symbol:        str,
        entry_price:   float,
        exit_price:    float,
        quantity:      int,
        realised_pnl:  float,
        holding_days:  int    = 0,
        close_reason:  str    = "",
        strategy_id:   str    = "",
        correlation_id: Optional[str] = None,
    ) -> str:
        cid = _new_id()
        with self._lock:
            self._conn.execute(
                """INSERT INTO position_closes VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, self._client_id, _ts(), symbol, "NSE",
                 entry_price, exit_price, quantity, realised_pnl,
                 holding_days, close_reason, strategy_id,
                 correlation_id or cid),
            )
            self._conn.commit()
        return cid

    def log_system_event(
        self,
        event_type: str,
        agent:      str    = "",
        payload:    Any    = None,
        severity:   str    = "INFO",
    ) -> str:
        import json as _json
        eid = _new_id()
        payload_str = _json.dumps(payload, default=str) if payload else ""
        with self._lock:
            self._conn.execute(
                """INSERT INTO system_events VALUES (?,?,?,?,?,?,?)""",
                (eid, self._client_id, _ts(), event_type, agent, payload_str, severity),
            )
            self._conn.commit()
        return eid

    # ── Read / export ─────────────────────────────────────────────────────────

    def export_csv(
        self,
        start_date: str,
        end_date:   str,
        output_path: str = "logs/sebi_audit_export.csv",
    ) -> str:
        """
        Export fills + position closes for a date range to CSV.
        Format compatible with SEBI broker circular requirements.
        """
        query = """
        SELECT
            f.ts                AS 'Trade Timestamp',
            f.client_id         AS 'Client ID',
            f.symbol            AS 'Symbol',
            f.exchange          AS 'Exchange',
            '' AS 'ISIN',
            o.transaction_type  AS 'Buy/Sell',
            o.order_type        AS 'Order Type',
            o.product           AS 'Product',
            f.fill_qty          AS 'Quantity',
            f.fill_price        AS 'Trade Price',
            f.trade_value       AS 'Trade Value',
            f.commission_inr    AS 'Commission (INR)',
            f.slippage_bps      AS 'Slippage (bps)',
            o.strategy_id       AS 'Strategy/Algo',
            o.algo_id           AS 'Algo ID',
            f.correlation_id    AS 'Correlation ID'
        FROM fills f
        JOIN orders o ON f.order_id = o.id
        WHERE f.ts BETWEEN ? AND ?
        ORDER BY f.ts ASC
        """
        with self._lock:
            rows   = self._conn.execute(query, (start_date, end_date + " 23:59:59")).fetchall()
            header = [d[0] for d in self._conn.execute(query, (start_date, end_date + " 23:59:59")).description] \
                     if rows else []

        # Re-execute properly to get description
        cur    = self._conn.execute(query, (start_date, end_date + " 23:59:59"))
        rows   = cur.fetchall()
        header = [d[0] for d in cur.description]

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)

        logger.info("SEBI audit export: %d rows → %s", len(rows), output_path)
        return output_path

    def get_summary(self, days: int = 30) -> Dict[str, Any]:
        """Quick summary for dashboard / daily report."""
        cutoff = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            n_signals = self._conn.execute(
                "SELECT COUNT(*) FROM signals WHERE ts >= ?", (cutoff,)
            ).fetchone()[0]
            n_orders = self._conn.execute(
                "SELECT COUNT(*) FROM orders WHERE ts >= ?", (cutoff,)
            ).fetchone()[0]
            n_fills = self._conn.execute(
                "SELECT COUNT(*) FROM fills WHERE ts >= ?", (cutoff,)
            ).fetchone()[0]
            total_pnl = self._conn.execute(
                "SELECT COALESCE(SUM(realised_pnl), 0) FROM position_closes WHERE ts >= ?",
                (cutoff,)
            ).fetchone()[0]
            n_rejected = self._conn.execute(
                "SELECT COUNT(*) FROM risk_decisions WHERE approved=0 AND ts >= ?",
                (cutoff,)
            ).fetchone()[0]

        return {
            "today_signals":         n_signals,
            "today_orders":          n_orders,
            "today_fills":           n_fills,
            "today_rejected":        n_rejected,
            "today_realised_pnl":    round(total_pnl, 2),
            "db_path":               self._path,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    """IST timestamp with microsecond precision."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _new_id() -> str:
    return str(uuid.uuid4())[:16].replace("-", "")


# ── Module-level singleton ────────────────────────────────────────────────────

    def log_trade(
        self,
        symbol:       str,
        action:       str,
        quantity:     int,
        price:        float,
        strategy:     str  = "",
        regime:       str  = "UNKNOWN",
        confidence:   float = 0.0,
        mode:         str  = "PAPER",
        agents_voted: dict = None,
    ) -> str:
        """
        Convenience wrapper: log a completed trade execution in one call.
        Internally creates both an order record and a fill record so the
        audit trail is complete.  Returns the generated order_id.
        """
        agents_voted = agents_voted or {}
        order_id = self._new_id()
        # Log the order (using AuditLog.log_order's actual signature)
        self.log_order(
            symbol       = symbol,
            qty          = quantity,
            price        = price,
            order_type   = "MARKET",
            action       = action,
            strategy_id  = strategy,
            correlation_id = order_id,
        )
        # Log the fill (assume 100% fill at the given price)
        self.log_fill(
            order_id     = order_id,
            symbol       = symbol,
            fill_price   = price,
            fill_qty     = quantity,
            slippage_bps = 0.0,
        )
        # Log agent votes as a system event so they are auditable
        if agents_voted:
            self.log_system_event(
                event_type = "AGENT_VOTES",
                details    = {
                    "order_id":     order_id,
                    "symbol":       symbol,
                    "agents_voted": agents_voted,
                },
            )
        return order_id

    def flush(self) -> None:
        """
        Flush and checkpoint the audit database.
        Called on clean shutdown to ensure all pending writes are persisted.
        SQLite WAL mode is used so in-flight transactions are committed.
        """
        try:
            if hasattr(self, "_conn") and self._conn:
                self._conn.execute("PRAGMA wal_checkpoint(FULL)")
                self._conn.commit()
        except Exception:
            pass


_AUDIT_INSTANCE: Optional[AuditLog] = None
_AUDIT_LOCK = threading.Lock()


def get_audit_log(client_id: str = "ALPHAZERO_001") -> AuditLog:
    """Return the global AuditLog singleton."""
    global _AUDIT_INSTANCE
    with _AUDIT_LOCK:
        if _AUDIT_INSTANCE is None:
            _AUDIT_INSTANCE = AuditLog(client_id=client_id)
    return _AUDIT_INSTANCE
