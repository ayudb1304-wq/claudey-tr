"""
test_phase10.py — Phase 10 Acceptance Tests: Logging & DB

Tests db.py for correct schema, insert/query, arithmetic integrity,
and the performance summary aggregation.

Uses an in-memory SQLite path (trades_test.db) so it never touches
the real database.

Usage:
    python test_phase10.py
"""

import sys
import os
from datetime import datetime, date
from pathlib import Path

import pytz
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="{message}", level="WARNING")

IST = pytz.timezone('Asia/Kolkata')

def check(condition, name, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         -> {detail}")
        sys.exit(1)

# ── Use a test-only DB so we don't pollute the real one ───
TEST_DB = Path("trades_test.db")

print("\n" + "=" * 52)
print("  PHASE 10 TESTS -- Logging & DB")
print("=" * 52 + "\n")

# ── Test 1: Import & patch DB path ─────────────────────────
print("1. Checking imports and redirecting to test database...")

import db
# Redirect all DB operations to the test file
db.DB_PATH = TEST_DB

# Remove any leftover test DB from a previous run
if TEST_DB.exists():
    TEST_DB.unlink()

from db import (
    init_db, insert_trade, insert_daily_summary,
    get_trades_for_date, get_daily_summary,
    get_all_trades, get_performance_summary,
)
check(True, "db.py imports correctly")
print()

# ── Test 2: init_db() creates tables ──────────────────────
print("2. Testing init_db() creates tables...")

init_db()
check(TEST_DB.exists(), f"Database file created at {TEST_DB}")

# Call again — should not raise (idempotent)
init_db()
check(True, "init_db() is idempotent (safe to call twice)")
print()

# ── Sample trade fixtures ──────────────────────────────────
def make_trade(symbol="RELIANCE", direction="BUY", net_pnl=135.69,
               exit_reason="TARGET", entry_h=10, exit_h=11):
    entry_time = IST.localize(datetime(2026, 3, 26, entry_h, 30, 0))
    exit_time  = IST.localize(datetime(2026, 3, 26, exit_h,  15, 0))
    entry  = 1290.64
    exit_p = 1314.34 if direction == "BUY" else 1265.0
    gross  = round(net_pnl + 4.31, 2)
    return {
        "symbol":        symbol,
        "direction":     direction,
        "shares":        7,
        "entry_price":   entry,
        "exit_price":    exit_p,
        "stop_loss":     1275.0,
        "target":        1315.0,
        "entry_time":    entry_time,
        "exit_time":     exit_time,
        "exit_reason":   exit_reason,
        "gross_pnl":     gross,
        "total_charges": 4.31,
        "net_pnl":       net_pnl,
        "stt":           2.29,
        "exchange_fee":  0.54,
        "sebi_charge":   0.02,
        "stamp_duty":    1.35,
        "gst":           0.10,
    }

# ── Test 3: insert_trade() ─────────────────────────────────
print("3. Testing insert_trade()...")

t1 = make_trade("RELIANCE", "BUY",  net_pnl=135.69, exit_reason="TARGET")
t2 = make_trade("ITC",      "SELL", net_pnl=-42.50, exit_reason="SL",    exit_h=12)
t3 = make_trade("SBIN",     "BUY",  net_pnl=88.20,  exit_reason="EOD",   exit_h=15)

id1 = insert_trade(t1)
id2 = insert_trade(t2)
id3 = insert_trade(t3)

check(isinstance(id1, int) and id1 > 0, f"insert_trade() returns positive int id: {id1}")
check(id2 > id1,  "Second insert has higher id than first")
check(id3 > id2,  "Third insert has higher id than second")
print()

# ── Test 4: get_trades_for_date() ─────────────────────────
print("4. Testing get_trades_for_date()...")

trades_today = get_trades_for_date("2026-03-26")
check(len(trades_today) == 3,
      f"get_trades_for_date() returns 3 trades: got {len(trades_today)}")

check(trades_today[0]['symbol'] == "RELIANCE",
      f"First trade is RELIANCE: got {trades_today[0]['symbol']}")

check(trades_today[1]['symbol'] == "ITC",
      f"Second trade is ITC: got {trades_today[1]['symbol']}")

# Empty for a different date
trades_other = get_trades_for_date("2026-03-27")
check(len(trades_other) == 0,
      "No trades for 2026-03-27 (correct — nothing inserted for that date)")
print()

# ── Test 5: Trade fields round-trip correctly ──────────────
print("5. Testing trade field round-trip...")

r = trades_today[0]
check(r['symbol']      == "RELIANCE",  "symbol correct")
check(r['direction']   == "BUY",       "direction correct")
check(r['shares']      == 7,           "shares correct")
check(r['exit_reason'] == "TARGET",    "exit_reason correct")
check(abs(r['net_pnl']       - 135.69) < 0.01, f"net_pnl correct: {r['net_pnl']}")
check(abs(r['total_charges'] - 4.31)   < 0.01, f"total_charges correct: {r['total_charges']}")
check(abs(r['gross_pnl'] - r['net_pnl'] - r['total_charges']) < 0.01,
      f"gross = net + charges: {r['gross_pnl']} = {r['net_pnl']} + {r['total_charges']}")
print()

# ── Test 6: insert_daily_summary() ─────────────────────────
print("6. Testing insert_daily_summary()...")

all_trades = [t1, t2, t3]
insert_daily_summary(
    trade_date    = "2026-03-26",
    trades        = all_trades,
    starting_cash = 25_000.0,
    ending_cash   = 25_181.39,
)

summary = get_daily_summary("2026-03-26")
check(summary is not None,                 "Daily summary row exists")
check(summary['total_trades']   == 3,      f"total_trades = 3: got {summary['total_trades']}")
check(summary['winning_trades'] == 2,      f"winning_trades = 2 (RELIANCE + SBIN): got {summary['winning_trades']}")
check(summary['losing_trades']  == 1,      f"losing_trades = 1 (ITC): got {summary['losing_trades']}")

expected_net = round(135.69 + (-42.50) + 88.20, 2)
check(abs(summary['net_pnl'] - expected_net) < 0.01,
      f"net_pnl = Rs{summary['net_pnl']} (expected Rs{expected_net})")

check(summary['max_drawdown'] == 42.50,
      f"max_drawdown = Rs{summary['max_drawdown']} (worst loss = Rs42.50)")
print()

# ── Test 7: net_pnl matches SUM(trades.net_pnl) ───────────
print("7. Testing daily_summary.net_pnl == SUM(trades.net_pnl)...")

sum_from_trades  = round(sum(t['net_pnl'] for t in all_trades), 2)
sum_from_summary = round(summary['net_pnl'], 2)
check(abs(sum_from_trades - sum_from_summary) < 0.01,
      f"SUM(trades.net_pnl) Rs{sum_from_trades} == daily_summary.net_pnl Rs{sum_from_summary}")
print()

# ── Test 8: Daily summary INSERT OR REPLACE ───────────────
print("8. Testing INSERT OR REPLACE (idempotent daily summary)...")

# Insert same date again with different values — should replace, not duplicate
insert_daily_summary(
    trade_date    = "2026-03-26",
    trades        = all_trades,
    starting_cash = 25_000.0,
    ending_cash   = 25_181.39,
)

import sqlite3
with sqlite3.connect(TEST_DB) as conn:
    count = conn.execute(
        "SELECT COUNT(*) FROM daily_summary WHERE trade_date = '2026-03-26'"
    ).fetchone()[0]

check(count == 1,
      f"Only 1 daily_summary row for 2026-03-26 after two inserts: got {count}")
print()

# ── Test 9: get_all_trades() ───────────────────────────────
print("9. Testing get_all_trades()...")

all_from_db = get_all_trades()
check(len(all_from_db) == 3,  f"get_all_trades() returns all 3 trades: got {len(all_from_db)}")
print()

# ── Test 10: get_performance_summary() ────────────────────
print("10. Testing get_performance_summary()...")

perf = get_performance_summary()
check(perf['total_trades']   == 3,   f"total_trades = 3: got {perf['total_trades']}")
check(perf['winning_trades'] == 2,   f"winning_trades = 2: got {perf['winning_trades']}")
check(perf['losing_trades']  == 1,   f"losing_trades = 1: got {perf['losing_trades']}")
check(abs(perf['win_rate'] - 0.667) < 0.001,
      f"win_rate = 0.667: got {perf['win_rate']}")
check(perf['avg_win']   > 0,  f"avg_win > 0: Rs{perf['avg_win']}")
check(perf['avg_loss']  < 0,  f"avg_loss < 0: Rs{perf['avg_loss']}")
check(perf['best_trade']  > 0,  f"best_trade > 0: Rs{perf['best_trade']}")
check(perf['worst_trade'] < 0,  f"worst_trade < 0: Rs{perf['worst_trade']}")
print()

# ── Test 11: Performance summary on empty DB ───────────────
print("11. Testing get_performance_summary() on empty database...")

# Create a separate empty DB for this check
empty_db = Path("trades_empty_test.db")
if empty_db.exists():
    empty_db.unlink()

db.DB_PATH = empty_db
init_db()

perf_empty = get_performance_summary()
check(perf_empty['total_trades'] == 0,  "Empty DB: total_trades = 0")
check(perf_empty['win_rate']     == 0.0, "Empty DB: win_rate = 0.0")
check(perf_empty['total_net_pnl'] == 0.0, "Empty DB: total_net_pnl = 0.0")

# Clean up — close any lingering connections before deleting on Windows
import gc; gc.collect()
try:
    empty_db.unlink()
except PermissionError:
    pass   # Windows file lock — will be cleaned up on next run
db.DB_PATH = TEST_DB   # restore
print()

# ── Test 12: Missing date returns None ─────────────────────
print("12. Testing get_daily_summary() returns None for missing date...")

missing = get_daily_summary("2025-01-01")
check(missing is None, "get_daily_summary() returns None for unknown date")
print()

# ── Cleanup ────────────────────────────────────────────────
import gc; gc.collect()
try:
    TEST_DB.unlink()
    print(f"  Test database removed.")
except PermissionError:
    print(f"  Test database will be removed on next run (Windows file lock).")
print()
print("-" * 52)
print("  All Phase 10 tests passed!")
print("  SQLite trade journal verified.")
print("  Ready for Phase 11 -- Paper Trading Run.")
print("-" * 52 + "\n")
