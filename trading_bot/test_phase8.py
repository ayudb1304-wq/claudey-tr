"""
test_phase8.py — Phase 8 Acceptance Tests: Paper Trading Engine

Tests paper_trader.py for correct cash arithmetic, slippage, exit logic,
and transaction cost integration.

Usage:
    python test_phase8.py
"""

import sys
from datetime import datetime

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

def ist(h, m):
    return IST.localize(datetime(2026, 3, 26, h, m, 0))

print("\n" + "=" * 52)
print("  PHASE 8 TESTS -- Paper Trading Engine")
print("=" * 52 + "\n")

# ── Test 1: Import ─────────────────────────────────────────
print("1. Checking imports...")
from paper_trader import PaperTrader, SLIPPAGE_PCT
from risk_manager import RiskManager
check(True, "paper_trader.py imports correctly")
print()

# ── Fixtures ───────────────────────────────────────────────
def make_trader(capital=10_000.0):
    rm = RiskManager(starting_capital=capital)
    rm.reset_daily(capital)
    return PaperTrader(starting_capital=capital, risk_manager=rm), rm

# ── Test 2: Open position deducts cash correctly ──────────
print("2. Testing open_position() cash deduction (with slippage)...")

trader, rm = make_trader()

ok, reason = trader.open_position(
    "RELIANCE", "BUY", shares=7,
    entry_price=1290.0, stop_loss=1275.0, target=1315.0,
    now=ist(10, 30),
)

check(ok, f"open_position() returned success: reason='{reason}'")
check("RELIANCE" in trader.positions, "Position recorded")

# Actual entry = 1290 * 1.0005 = 1290.645 → rounded = 1290.65
expected_entry = round(1290.0 * (1 + SLIPPAGE_PCT), 2)
actual_entry   = trader.positions["RELIANCE"]["entry_price"]
check(actual_entry == expected_entry,
      f"Entry with slippage: Rs{actual_entry} (expected Rs{expected_entry})")

expected_cost = expected_entry * 7
expected_cash = round(10_000.0 - expected_cost, 2)
check(abs(trader.cash - expected_cash) < 0.01,
      f"Cash after open: Rs{trader.cash:.2f} (expected Rs{expected_cash:.2f})")

check(rm.open_count == 1, f"Risk manager open_count = 1")
print()

# ── Test 3: Duplicate open rejected ────────────────────────
print("3. Testing duplicate position is rejected...")

ok2, reason2 = trader.open_position(
    "RELIANCE", "BUY", shares=5,
    entry_price=1291.0, stop_loss=1276.0, target=1316.0,
    now=ist(10, 45),
)
check(not ok2, f"Duplicate RELIANCE rejected (reason: '{reason2}')")
check("RELIANCE" in reason2, "Reason mentions the symbol")
print()

# ── Test 4: TARGET exit ────────────────────────────────────
print("4. Testing TARGET exit fires correctly...")

trader2, rm2 = make_trader()
trader2.open_position("RELIANCE", "BUY", 7, 1290.0, 1275.0, 1315.0, ist(10, 30))

# Candle where high >= target (1315)
trade = trader2.check_exits(
    "RELIANCE",
    candle_high=1318.0, candle_low=1291.0, candle_close=1316.0,
    now=ist(11, 0),
)

check(trade is not None,               "Exit triggered")
check(trade['exit_reason'] == "TARGET", f"Exit reason = TARGET")
check("RELIANCE" not in trader2.positions, "Position removed from open positions")
check(rm2.open_count == 0,             "Risk manager open_count = 0")

# Exit price = target (1315) with slippage applied
expected_exit = round(1315.0 * (1 - SLIPPAGE_PCT), 2)
check(trade['exit_price'] == expected_exit,
      f"Exit price with slippage: Rs{trade['exit_price']} (expected Rs{expected_exit})")

# Gross P&L: (exit - entry) * shares
entry = trader2.closed_trades[0]['entry_price']
gross = round((expected_exit - entry) * 7, 2)
check(abs(trade['gross_pnl'] - gross) < 0.02,
      f"Gross P&L: Rs{trade['gross_pnl']} (expected ~Rs{gross})")

# Net P&L < gross (charges deducted)
check(trade['net_pnl'] < trade['gross_pnl'],
      f"Net P&L Rs{trade['net_pnl']} < gross Rs{trade['gross_pnl']} (charges applied)")
print()

# ── Test 5: SL exit ────────────────────────────────────────
print("5. Testing SL exit fires correctly...")

trader3, rm3 = make_trader()
trader3.open_position("RELIANCE", "BUY", 7, 1290.0, 1275.0, 1315.0, ist(10, 30))

# Candle where low <= SL (1275)
trade_sl = trader3.check_exits(
    "RELIANCE",
    candle_high=1291.0, candle_low=1274.0, candle_close=1276.0,
    now=ist(11, 0),
)

check(trade_sl is not None,            "SL exit triggered")
check(trade_sl['exit_reason'] == "SL", "Exit reason = SL")

# Exit at SL price with slippage
expected_sl_exit = round(1275.0 * (1 - SLIPPAGE_PCT), 2)
check(trade_sl['exit_price'] == expected_sl_exit,
      f"SL exit price: Rs{trade_sl['exit_price']} (expected Rs{expected_sl_exit})")

# Loss trade: net_pnl < 0
check(trade_sl['net_pnl'] < 0,
      f"SL exit is a losing trade: net_pnl=Rs{trade_sl['net_pnl']:.2f}")
print()

# ── Test 6: SL takes priority over target on same candle ──
print("6. Testing SL takes priority over target on same candle...")

trader4, rm4 = make_trader()
trader4.open_position("RELIANCE", "BUY", 7, 1290.0, 1275.0, 1315.0, ist(10, 30))

# Both SL and target touched on same candle (gap down then spike up — rare but possible)
trade_priority = trader4.check_exits(
    "RELIANCE",
    candle_high=1320.0, candle_low=1270.0, candle_close=1295.0,
    now=ist(11, 0),
)

check(trade_priority is not None,                 "Exit triggered")
check(trade_priority['exit_reason'] == "SL",      "SL takes priority (conservative)")
print()

# ── Test 7: EOD force-close ────────────────────────────────
print("7. Testing EOD force-close at 3:15 PM...")

trader5, rm5 = make_trader()
trader5.open_position("RELIANCE", "BUY", 7, 1290.0, 1275.0, 1315.0, ist(10, 30))

# Candle at 3:15 PM — neither SL nor target touched
trade_eod = trader5.check_exits(
    "RELIANCE",
    candle_high=1295.0, candle_low=1288.0, candle_close=1293.0,
    now=ist(15, 15),
)

check(trade_eod is not None,              "EOD exit triggered")
check(trade_eod['exit_reason'] == "EOD",  "Exit reason = EOD")

expected_eod_exit = round(1293.0 * (1 - SLIPPAGE_PCT), 2)
check(trade_eod['exit_price'] == expected_eod_exit,
      f"EOD exit at close price: Rs{trade_eod['exit_price']} (expected Rs{expected_eod_exit})")
print()

# ── Test 8: No exit triggered when price in range ─────────
print("8. Testing no exit when price stays in range...")

trader6, rm6 = make_trader()
trader6.open_position("RELIANCE", "BUY", 7, 1290.0, 1275.0, 1315.0, ist(10, 30))

result = trader6.check_exits(
    "RELIANCE",
    candle_high=1295.0, candle_low=1288.0, candle_close=1293.0,
    now=ist(11, 0),
)

check(result is None,                      "No exit triggered mid-day")
check("RELIANCE" in trader6.positions,     "Position still open")
print()

# ── Test 9: SELL (short) exit logic ───────────────────────
print("9. Testing SELL (short) exit logic...")

trader7, rm7 = make_trader()
trader7.open_position("RELIANCE", "SELL", 7, 1290.0, stop_loss=1305.0,
                       target=1265.0, now=ist(10, 30))

pos = trader7.positions["RELIANCE"]
# For SELL: entry slippage = 1290 * (1 - 0.0005)
expected_sell_entry = round(1290.0 * (1 - SLIPPAGE_PCT), 2)
check(pos['entry_price'] == expected_sell_entry,
      f"SELL entry with slippage: Rs{pos['entry_price']} (expected Rs{expected_sell_entry})")

# SELL SL hit: candle HIGH >= SL (1305)
trade_sell_sl = trader7.check_exits(
    "RELIANCE",
    candle_high=1306.0, candle_low=1285.0, candle_close=1300.0,
    now=ist(11, 0),
)
check(trade_sell_sl is not None,              "SELL SL triggered")
check(trade_sell_sl['exit_reason'] == "SL",   "SELL SL exit reason correct")
check(trade_sell_sl['net_pnl'] < 0,           "SELL SL is a losing trade")
print()

# ── Test 10: SELL target hit ───────────────────────────────
print("10. Testing SELL target hit...")

trader8, rm8 = make_trader()
trader8.open_position("RELIANCE", "SELL", 7, 1290.0, stop_loss=1305.0,
                       target=1265.0, now=ist(10, 30))

# SELL target: candle LOW <= target (1265)
trade_sell_tgt = trader8.check_exits(
    "RELIANCE",
    candle_high=1292.0, candle_low=1263.0, candle_close=1270.0,
    now=ist(11, 0),
)
check(trade_sell_tgt is not None,                "SELL target triggered")
check(trade_sell_tgt['exit_reason'] == "TARGET", "SELL target exit reason correct")
check(trade_sell_tgt['net_pnl'] > 0,             "SELL target is a winning trade")
print()

# ── Test 11: Cash arithmetic round-trip ────────────────────
print("11. Testing cash arithmetic round-trip...")

trader9, rm9 = make_trader(10_000.0)
initial_cash = trader9.cash

trader9.open_position("RELIANCE", "BUY", 7, 1290.0, 1275.0, 1315.0, ist(10, 30))
after_open = trader9.cash

trader9.check_exits("RELIANCE", candle_high=1320.0, candle_low=1292.0,
                     candle_close=1318.0, now=ist(11, 0))
after_close = trader9.cash

trade = trader9.closed_trades[0]

check(after_open < initial_cash,
      f"Cash decreased after open: Rs{after_open:.2f} < Rs{initial_cash:.2f}")
check(after_close > after_open,
      f"Cash increased after profitable close: Rs{after_close:.2f} > Rs{after_open:.2f}")

# Cash should be initial + net_pnl
expected_final = round(initial_cash + trade['net_pnl'], 2)
check(abs(after_close - expected_final) < 0.02,
      f"Final cash Rs{after_close:.2f} == initial Rs{initial_cash} + net Rs{trade['net_pnl']:.2f} = Rs{expected_final:.2f}")
print()

# ── Test 12: force_close_all() ─────────────────────────────
print("12. Testing force_close_all()...")

trader10, rm10 = make_trader(20_000.0)   # enough for 2 positions
trader10.open_position("RELIANCE", "BUY", 7,  1290.0, 1275.0, 1315.0, ist(10, 30))
trader10.open_position("ITC",      "SELL", 20, 455.0,  465.0,  440.0,  ist(10, 30))

check(len(trader10.positions) == 2, "2 open positions before force close")

closed = trader10.force_close_all(
    prices={"RELIANCE": 1295.0, "ITC": 450.0},
    now=ist(15, 15),
)

check(len(closed) == 2,              "Both positions force-closed")
check(len(trader10.positions) == 0,  "No open positions after force close")
check(rm10.open_count == 0,          "Risk manager open_count = 0")
print()

# ── Test 13: get_summary() ─────────────────────────────────
print("13. Testing get_summary()...")

trader11, rm11 = make_trader(10_000.0)
trader11.open_position("RELIANCE", "BUY", 7, 1290.0, 1275.0, 1315.0, ist(10, 30))
trader11.check_exits("RELIANCE", 1320.0, 1292.0, 1318.0, now=ist(11, 0))   # target hit

summary = trader11.get_summary()

check('cash'            in summary, "summary has 'cash'")
check('open_positions'  in summary, "summary has 'open_positions'")
check('net_pnl_today'   in summary, "summary has 'net_pnl_today'")
check('closed_today'    in summary, "summary has 'closed_today'")
check(summary['open_positions'] == 0, f"open_positions = 0 after close")
check(summary['closed_today']   == 1, f"closed_today = 1")
check(summary['net_pnl_today']  >  0, f"net_pnl_today positive after winning trade")
print()

# ── Test 14: Insufficient cash rejected ────────────────────
print("14. Testing open rejected when insufficient cash...")

trader12, rm12 = make_trader(1_000.0)   # only Rs1000
ok, reason = trader12.open_position(
    "RELIANCE", "BUY", shares=7,       # 7 × ~1290 = ~Rs9030 — too much
    entry_price=1290.0, stop_loss=1275.0, target=1315.0,
    now=ist(10, 30),
)
check(not ok,   f"Open rejected: insufficient cash (reason: '{reason[:40]}...')")
check(abs(trader12.cash - 1_000.0) < 0.01, "Cash unchanged after rejection")
print()

# ── Test 15: Closed trades have all required fields ────────
print("15. Testing closed trade dict has all required fields...")

trader13, rm13 = make_trader()
trader13.open_position("ITC", "BUY", 20, 455.0, 445.0, 473.0, ist(10, 30))
trader13.check_exits("ITC", 475.0, 456.0, 474.0, now=ist(11, 15))   # target

t = trader13.closed_trades[0]
for field in ["symbol", "direction", "shares", "entry_price", "exit_price",
              "stop_loss", "target", "entry_time", "exit_time", "exit_reason",
              "gross_pnl", "net_pnl", "total_charges", "stt", "stamp_duty", "gst"]:
    check(field in t, f"Closed trade has field '{field}'")
print()

# ── Summary ────────────────────────────────────────────────
print("-" * 52)
print("  All Phase 8 tests passed!")
print("  Paper trader verified.")
print("  Ready to build Phase 9 -- Main Loop.")
print("-" * 52 + "\n")
