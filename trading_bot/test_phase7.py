"""
test_phase7.py — Phase 7 Acceptance Tests: Risk Manager

Tests risk_manager.py using mocked datetimes so time-based rules
can be verified without waiting for real clock times.

Usage:
    python test_phase7.py
"""

import sys
from datetime import datetime
from unittest.mock import patch

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

def make_ist_time(hour, minute):
    """Return a timezone-aware datetime at the given IST hour:minute (today)."""
    naive = datetime(2026, 3, 26, hour, minute, 0)
    return IST.localize(naive)

print("\n" + "=" * 52)
print("  PHASE 7 TESTS -- Risk Manager")
print("=" * 52 + "\n")

# ── Test 1: Import ─────────────────────────────────────────
print("1. Checking imports...")
from risk_manager import RiskManager
check(True, "risk_manager.py imports correctly")
print()

# ── Test 2: Construction ───────────────────────────────────
print("2. Testing RiskManager construction...")

rm = RiskManager(starting_capital=10_000.0)
check(rm.daily_pnl   == 0.0,  "Initial daily_pnl = 0.0")
check(rm.open_count  == 0,    "Initial open_count = 0")
check(rm.daily_loss_cap > 0,  f"Daily loss cap positive: Rs{rm.daily_loss_cap}")

# 3% of 10000 = 300
check(abs(rm.daily_loss_cap - 750.0) < 0.01,
      f"Daily loss cap = Rs{rm.daily_loss_cap} (expected Rs750)")

try:
    RiskManager(starting_capital=-1000.0)
    check(False, "Should raise ValueError for negative capital")
except ValueError:
    check(True, "ValueError raised for negative starting_capital")
print()

# ── Test 3: Daily loss cap detection ──────────────────────
print("3. Testing daily loss cap detection...")

rm.reset_daily(10_000.0)
check(not rm.is_daily_loss_cap_hit(),
      "Loss cap not hit at 0 P&L")

rm.update_daily_pnl(-400.0)
check(not rm.is_daily_loss_cap_hit(),
      f"Loss cap not hit at -Rs400 (cap=-Rs750): P&L={rm.daily_pnl}")

rm.update_daily_pnl(-400.0)    # now at -800 total
check(rm.is_daily_loss_cap_hit(),
      f"Loss cap HIT at -Rs800 (cap=-Rs750): P&L={rm.daily_pnl}")
print()

# ── Test 4: Time check — trading allowed ──────────────────
print("4. Testing time-based entry rules...")

rm.reset_daily(10_000.0)   # reset P&L

# 10:30 AM — should be allowed
t_ok = make_ist_time(10, 30)
check(not rm.is_too_late_to_trade(t_ok),
      f"10:30 AM IST — NOT too late to trade")

# 14:59 — just before cutoff (2:59 PM)
t_before = make_ist_time(14, 59)
check(not rm.is_too_late_to_trade(t_before),
      f"14:59 IST — NOT too late (cutoff is 15:00)")

# 15:00:00 — exactly at cutoff
t_cutoff = make_ist_time(15, 0)
check(rm.is_too_late_to_trade(t_cutoff),
      f"15:00 IST — too late (exactly at cutoff)")

# 15:05 — after cutoff
t_after = make_ist_time(15, 5)
check(rm.is_too_late_to_trade(t_after),
      f"15:05 IST — too late")
print()

# ── Test 5: Max open positions ─────────────────────────────
print("5. Testing max open positions gate...")

rm.reset_daily(10_000.0)
check(not rm.is_max_positions_reached(),
      "0 open positions — not at max")

rm.update_open_count(+1)
check(not rm.is_max_positions_reached(),
      "1 open position — not at max (max=2)")

rm.update_open_count(+1)
check(rm.is_max_positions_reached(),
      "2 open positions — max reached")

rm.update_open_count(-1)    # close one
check(not rm.is_max_positions_reached(),
      "After closing 1, back to 1 — not at max")
print()

# ── Test 6: can_open_new_trade() — all gates ──────────────
print("6. Testing can_open_new_trade() combined gate...")

rm.reset_daily(10_000.0)
t_mid = make_ist_time(11, 0)

allowed, reason = rm.can_open_new_trade(t_mid)
check(allowed,
      f"Normal conditions: trade allowed (reason: '{reason}')")

# Block 1: daily loss cap
rm.update_daily_pnl(-800.0)    # exceeds -750 cap (3% of Rs25,000)
allowed, reason = rm.can_open_new_trade(t_mid)
check(not allowed,
      f"Daily loss cap hit: trade blocked (reason: '{reason[:40]}...')")
check("cap" in reason.lower() or "loss" in reason.lower(),
      "Reason mentions loss cap")

# Block 2: time
rm.reset_daily(10_000.0)
allowed, reason = rm.can_open_new_trade(make_ist_time(15, 5))
check(not allowed, f"After 15:00: trade blocked")
check("late" in reason.lower() or "cutoff" in reason.lower(),
      "Reason mentions time cutoff")

# Block 3: max positions
rm.reset_daily(10_000.0)
rm.update_open_count(+1)
rm.update_open_count(+1)
allowed, reason = rm.can_open_new_trade(t_mid)
check(not allowed, f"Max positions: trade blocked")
check("position" in reason.lower(),
      "Reason mentions positions")
print()

# ── Test 7: Position sizing ────────────────────────────────
print("7. Testing position sizing...")

rm.reset_daily(10_000.0)

# entry=1290, sl=1275 → distance=15
# risk_budget = 10000 × 0.02 = 200
# shares_by_risk = floor(200/15) = 13
# shares_by_capital = floor(10000/1290) = 7
# → min(13, 7) = 7
shares = rm.size_position(entry_price=1290.0, stop_loss=1275.0,
                           available_capital=10_000.0)
check(shares == 7,
      f"7 shares (risk-budget logic + capital cap): got {shares}")

# Tight SL: entry=1290, sl=1289 → distance=1
# shares_by_risk = floor(200/1) = 200
# shares_by_capital = floor(10000/1290) = 7
# → min(200, 7) = 7
shares_tight = rm.size_position(entry_price=1290.0, stop_loss=1289.0,
                                  available_capital=10_000.0)
check(shares_tight == 7,
      f"Tight SL: capped by capital to 7 shares: got {shares_tight}")

# Wide SL: entry=1290, sl=1200 → distance=90
# shares_by_risk = floor(200/90) = 2
# shares_by_capital = floor(10000/1290) = 7
# → min(2, 7) = 2
shares_wide = rm.size_position(entry_price=1290.0, stop_loss=1200.0,
                                 available_capital=10_000.0)
check(shares_wide == 2,
      f"Wide SL: limited by risk to 2 shares: got {shares_wide}")

# Zero distance → 0 shares
shares_zero = rm.size_position(entry_price=1290.0, stop_loss=1290.0,
                                 available_capital=10_000.0)
check(shares_zero == 0,
      f"SL = entry: 0 shares: got {shares_zero}")

# Low capital (Rs500 only): entry=1290
# shares_by_capital = floor(500/1290) = 0 → can't afford even 1 share
shares_low_cap = rm.size_position(entry_price=1290.0, stop_loss=1275.0,
                                    available_capital=500.0)
check(shares_low_cap == 0,
      f"Can't afford 1 share with Rs500 capital: got {shares_low_cap}")
print()

# ── Test 8: R:R validation ─────────────────────────────────
print("8. Testing R:R validation...")

# BUY: entry=1290, sl=1275, target=1315 → risk=15, reward=25 → R:R=1.67
passes, rr = rm.check_rr_ratio(1290.0, 1275.0, 1315.0, "BUY")
check(passes, f"BUY R:R={rr} >= 1.5 threshold: approved")
check(abs(rr - 1.67) < 0.01, f"R:R = {rr} (expected 1.67)")

# BUY: entry=1290, sl=1280, target=1300 → risk=10, reward=10 → R:R=1.0
passes2, rr2 = rm.check_rr_ratio(1290.0, 1280.0, 1300.0, "BUY")
check(not passes2, f"BUY R:R={rr2} < 1.5: rejected")

# BUY: entry=1290, sl=1280, target=1305 → risk=10, reward=15 → R:R=1.5
passes3, rr3 = rm.check_rr_ratio(1290.0, 1280.0, 1305.0, "BUY")
check(passes3, f"BUY R:R={rr3} == 1.5 (exactly at threshold): approved")

# SELL: entry=1290, sl=1305, target=1265 → risk=15, reward=25 → R:R=1.67
passes4, rr4 = rm.check_rr_ratio(1290.0, 1305.0, 1265.0, "SELL")
check(passes4, f"SELL R:R={rr4} >= 1.5: approved")
print()

# ── Test 9: evaluate_trade() — approved path ──────────────
print("9. Testing evaluate_trade() full approval...")

rm.reset_daily(10_000.0)

result = rm.evaluate_trade(
    now               = make_ist_time(10, 30),
    entry_price       = 1290.0,
    stop_loss         = 1275.0,
    target            = 1315.0,
    direction         = "BUY",
    available_capital = 10_000.0,
)

check(result['approved'],
      f"evaluate_trade() approved: {result}")
check(result['shares'] == 7,
      f"Correct share count: {result['shares']}")
check(result['rr_ratio'] >= 1.5,
      f"R:R {result['rr_ratio']} >= 1.5")
check(result['risk_Rs'] > 0,
      f"risk_Rs positive: Rs{result['risk_Rs']}")
check(result['reason'] == "",
      f"No rejection reason when approved")
print()

# ── Test 10: evaluate_trade() — all rejection paths ───────
print("10. Testing evaluate_trade() rejection paths...")

# Daily loss cap
rm.reset_daily(25_000.0)
rm.update_daily_pnl(-800.0)
r = rm.evaluate_trade(make_ist_time(11, 0), 1290.0, 1275.0, 1315.0, "BUY", 25_000.0)
check(not r['approved'], "Rejected: daily loss cap")
check(r['shares'] == 0,  "shares=0 when rejected")

# Too late
rm.reset_daily(10_000.0)
r = rm.evaluate_trade(make_ist_time(15, 10), 1290.0, 1275.0, 1315.0, "BUY", 10_000.0)
check(not r['approved'], "Rejected: too late")

# Max positions
rm.reset_daily(10_000.0)
rm.update_open_count(+1)
rm.update_open_count(+1)
r = rm.evaluate_trade(make_ist_time(11, 0), 1290.0, 1275.0, 1315.0, "BUY", 10_000.0)
check(not r['approved'], "Rejected: max positions")

# Bad R:R
rm.reset_daily(10_000.0)
r = rm.evaluate_trade(make_ist_time(11, 0), 1290.0, 1280.0, 1300.0, "BUY", 10_000.0)
check(not r['approved'], "Rejected: bad R:R (1.0 < 1.5)")

# Zero shares (can't afford)
rm.reset_daily(10_000.0)
r = rm.evaluate_trade(make_ist_time(11, 0), 1290.0, 1275.0, 1315.0, "BUY", 500.0)
check(not r['approved'], "Rejected: can't afford 1 share (Rs500 capital)")
print()

# ── Test 11: reset_daily() resets state ───────────────────
print("11. Testing reset_daily() correctly resets state...")

rm.update_daily_pnl(-200.0)
rm.update_open_count(+2)
rm.reset_daily(9_800.0)     # new capital after losses

check(rm.daily_pnl  == 0.0,  "daily_pnl reset to 0")
check(rm.open_count == 0,    "open_count reset to 0 (all positions force-closed at 3:15 PM)")

# open_count IS reset because all positions are force-closed at 3:15 PM daily.
# A new trading day always starts with 0 open positions.
print()

# ── Test 12: Risk per-trade never exceeds available capital ─
print("12. Testing risk budget never exceeds available capital...")

rm.reset_daily(10_000.0)

# Very high price stock with small capital
shares_hi = rm.size_position(entry_price=1990.0, stop_loss=1970.0,
                               available_capital=1_000.0)
cost = shares_hi * 1990.0
check(cost <= 1_000.0,
      f"Trade cost Rs{cost} <= available capital Rs1000 ({shares_hi} shares)")
print()

# ── Summary ────────────────────────────────────────────────
print("-" * 52)
print("  All Phase 7 tests passed!")
print("  Risk manager verified.")
print("  Ready to build Phase 8 -- Paper Trader.")
print("-" * 52 + "\n")
