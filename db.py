"""
db.py — SQLite Trade Journal & Daily Summary

Persists every closed trade and end-of-day summary to a local SQLite
database so you can review performance across sessions.

DATABASE FILE:
  trades.db — created automatically on first run.
  Added to .gitignore so it doesn't get committed.

TABLES:
  trades        — one row per closed position
  daily_summary — one row per trading day (written at EOD)

DESIGN:
  - init_db()           : create tables if they don't exist (idempotent)
  - insert_trade()      : called by main.py immediately when a position closes
  - insert_daily_summary(): called by main.py at 3:30 PM EOD
  - get_trades_for_date(): query trades for a given date (for review/reporting)
  - get_daily_summary() : query the summary row for a given date
  - get_all_trades()    : full history
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

from loguru import logger

DB_PATH = Path("trades.db")


# ─────────────────────────────────────────────────────────────
#  CONNECTION HELPER
# ─────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row    # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent reads
    return conn


# ─────────────────────────────────────────────────────────────
#  SCHEMA
# ─────────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Create database tables if they don't already exist.
    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.
    """
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date    TEXT    NOT NULL,   -- YYYY-MM-DD (IST)
                symbol        TEXT    NOT NULL,
                direction     TEXT    NOT NULL,   -- BUY or SELL
                shares        INTEGER NOT NULL,
                entry_price   REAL    NOT NULL,
                exit_price    REAL    NOT NULL,
                stop_loss     REAL    NOT NULL,
                target        REAL    NOT NULL,
                entry_time    TEXT    NOT NULL,   -- ISO datetime string
                exit_time     TEXT    NOT NULL,
                exit_reason   TEXT    NOT NULL,   -- SL, TARGET, EOD, MANUAL
                gross_pnl     REAL    NOT NULL,
                total_charges REAL    NOT NULL,
                net_pnl       REAL    NOT NULL,
                stt           REAL    NOT NULL,
                exchange_fee  REAL    NOT NULL,
                sebi_charge   REAL    NOT NULL,
                stamp_duty    REAL    NOT NULL,
                gst           REAL    NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_summary (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date      TEXT    NOT NULL UNIQUE,  -- YYYY-MM-DD
                total_trades    INTEGER NOT NULL,
                winning_trades  INTEGER NOT NULL,
                losing_trades   INTEGER NOT NULL,
                gross_pnl       REAL    NOT NULL,
                total_charges   REAL    NOT NULL,
                net_pnl         REAL    NOT NULL,
                starting_cash   REAL    NOT NULL,
                ending_cash     REAL    NOT NULL,
                max_drawdown    REAL    NOT NULL    -- largest single losing trade (abs value)
            )
        """)

    logger.debug(f"[DB] Database initialised at {DB_PATH.resolve()}")


# ─────────────────────────────────────────────────────────────
#  WRITES
# ─────────────────────────────────────────────────────────────

def insert_trade(trade: dict) -> int:
    """
    Insert one closed trade into the trades table.

    Args:
        trade: dict from paper_trader.close_position() — must have all
               keys matching the table schema.

    Returns:
        int — the new row's id (for logging/debugging).
    """
    trade_date = _extract_date(trade['exit_time'])

    with _connect() as conn:
        cursor = conn.execute("""
            INSERT INTO trades (
                trade_date, symbol, direction, shares,
                entry_price, exit_price, stop_loss, target,
                entry_time, exit_time, exit_reason,
                gross_pnl, total_charges, net_pnl,
                stt, exchange_fee, sebi_charge, stamp_duty, gst
            ) VALUES (
                :trade_date, :symbol, :direction, :shares,
                :entry_price, :exit_price, :stop_loss, :target,
                :entry_time, :exit_time, :exit_reason,
                :gross_pnl, :total_charges, :net_pnl,
                :stt, :exchange_fee, :sebi_charge, :stamp_duty, :gst
            )
        """, {
            **trade,
            "trade_date": trade_date,
            "entry_time": _fmt_dt(trade['entry_time']),
            "exit_time":  _fmt_dt(trade['exit_time']),
        })

    row_id = cursor.lastrowid
    logger.debug(f"[DB] Trade inserted: id={row_id} {trade['symbol']} net=Rs{trade['net_pnl']:.2f}")
    return row_id


def insert_daily_summary(
    trade_date:   date | str,
    trades:       list[dict],
    starting_cash: float,
    ending_cash:   float,
) -> None:
    """
    Write (or replace) the daily summary for a given date.

    Args:
        trade_date:    Date of trading (date object or YYYY-MM-DD string)
        trades:        All trades closed today (list of dicts from paper_trader)
        starting_cash: Cash at market open
        ending_cash:   Cash after EOD force-close
    """
    trade_date_str = str(trade_date) if isinstance(trade_date, date) else trade_date

    total    = len(trades)
    wins     = sum(1 for t in trades if t['net_pnl'] > 0)
    losses   = total - wins
    gross    = sum(t['gross_pnl']     for t in trades)
    charges  = sum(t['total_charges'] for t in trades)
    net      = sum(t['net_pnl']       for t in trades)
    drawdown = abs(min((t['net_pnl'] for t in trades if t['net_pnl'] < 0), default=0.0))

    with _connect() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO daily_summary (
                trade_date, total_trades, winning_trades, losing_trades,
                gross_pnl, total_charges, net_pnl,
                starting_cash, ending_cash, max_drawdown
            ) VALUES (
                :trade_date, :total_trades, :winning_trades, :losing_trades,
                :gross_pnl, :total_charges, :net_pnl,
                :starting_cash, :ending_cash, :max_drawdown
            )
        """, {
            "trade_date":     trade_date_str,
            "total_trades":   total,
            "winning_trades": wins,
            "losing_trades":  losses,
            "gross_pnl":      round(gross,   2),
            "total_charges":  round(charges, 2),
            "net_pnl":        round(net,     2),
            "starting_cash":  round(starting_cash, 2),
            "ending_cash":    round(ending_cash,   2),
            "max_drawdown":   round(drawdown, 2),
        })

    logger.debug(
        f"[DB] Daily summary for {trade_date_str}: "
        f"{total} trades, net=Rs{net:.2f}"
    )


# ─────────────────────────────────────────────────────────────
#  READS
# ─────────────────────────────────────────────────────────────

def get_trades_for_date(trade_date: date | str) -> list[dict]:
    """Return all trades for a given date, oldest first."""
    date_str = str(trade_date) if isinstance(trade_date, date) else trade_date
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE trade_date = ? ORDER BY id",
            (date_str,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_daily_summary(trade_date: date | str) -> dict | None:
    """Return the daily summary row for a given date, or None if not found."""
    date_str = str(trade_date) if isinstance(trade_date, date) else trade_date
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM daily_summary WHERE trade_date = ?",
            (date_str,)
        ).fetchone()
    return dict(row) if row else None


def get_all_trades() -> list[dict]:
    """Return every trade ever recorded, oldest first."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM trades ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_performance_summary() -> dict:
    """
    Return aggregate statistics across all recorded trades.

    Returns:
        {
            "total_trades":  int,
            "winning_trades": int,
            "losing_trades":  int,
            "win_rate":       float (0.0–1.0),
            "total_net_pnl":  float,
            "avg_win":        float,
            "avg_loss":       float,
            "best_trade":     float,
            "worst_trade":    float,
        }
    """
    trades = get_all_trades()
    if not trades:
        return {
            "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
            "win_rate": 0.0, "total_net_pnl": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0,
        }

    wins   = [t['net_pnl'] for t in trades if t['net_pnl'] > 0]
    losses = [t['net_pnl'] for t in trades if t['net_pnl'] <= 0]
    total  = len(trades)

    return {
        "total_trades":   total,
        "winning_trades": len(wins),
        "losing_trades":  len(losses),
        "win_rate":       round(len(wins) / total, 3) if total else 0.0,
        "total_net_pnl":  round(sum(t['net_pnl'] for t in trades), 2),
        "avg_win":        round(sum(wins)   / len(wins),   2) if wins   else 0.0,
        "avg_loss":       round(sum(losses) / len(losses), 2) if losses else 0.0,
        "best_trade":     round(max(wins),   2) if wins   else 0.0,
        "worst_trade":    round(min(losses), 2) if losses else 0.0,
    }


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def _fmt_dt(dt) -> str:
    """Convert datetime (or string) to ISO string for storage."""
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _extract_date(dt) -> str:
    """Extract YYYY-MM-DD string from datetime or string."""
    if isinstance(dt, datetime):
        return dt.date().isoformat()
    if isinstance(dt, date):
        return dt.isoformat()
    # Try to parse the first 10 chars of an ISO string
    return str(dt)[:10]
