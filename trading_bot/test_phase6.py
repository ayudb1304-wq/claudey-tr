"""
test_phase6.py — Phase 6 Acceptance Tests: Transaction Cost Engine

Tests transaction_costs.py for accuracy against manually verified values.

Reference trade used throughout:
  RELIANCE BUY 7 shares @ Rs1290, exit @ Rs1310
  buy_turnover  = 7 × 1290 = Rs9030
  sell_turnover = 7 × 1310 = Rs9170
  gross_pnl     = Rs9170 - Rs9030 = Rs140.00

Expected charges (manually calculated):
  STT:          Rs9170 × 0.00025       = Rs2.2925
  Exchange fee: (Rs9030 + Rs9170) × 0.0000297 = Rs0.5405
  SEBI:         (Rs9030 + Rs9170) × 0.000001  = Rs0.0182
  Stamp duty:   Rs9030 × 0.00015      = Rs1.3545
  GST:          (Rs0.5405 + Rs0.0182) × 0.18  = Rs0.1006
  Total:        = Rs4.3063

Usage:
    python test_phase6.py
"""

import sys
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="{message}", level="WARNING")

def check(condition, name, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         -> {detail}")
        sys.exit(1)

print("\n" + "=" * 52)
print("  PHASE 6 TESTS -- Transaction Cost Engine")
print("=" * 52 + "\n")

# ── Test 1: Import ─────────────────────────────────────────
print("1. Checking imports...")
from transaction_costs import calculate_charges, charges_summary
check(True, "transaction_costs.py imports correctly")
print()

# ── Reference trade setup ──────────────────────────────────
ENTRY = 1290.0
EXIT  = 1310.0
QTY   = 7

BUY_TURN  = ENTRY * QTY   # 9030.0
SELL_TURN = EXIT  * QTY   # 9170.0

# ── Test 2: BUY trade output structure ────────────────────
print("2. Testing output structure for BUY trade...")

result = calculate_charges(ENTRY, EXIT, QTY, "BUY")

required_keys = {
    "gross_pnl", "buy_turnover", "sell_turnover",
    "stt", "exchange_fee", "sebi_charge", "stamp_duty", "gst",
    "total_charges", "net_pnl",
}
missing = required_keys - set(result.keys())
check(len(missing) == 0,
      "All required keys present",
      f"Missing: {missing}")
print()

# ── Test 3: Turnover values ────────────────────────────────
print("3. Testing turnover calculations...")

check(result['buy_turnover']  == round(BUY_TURN,  2),
      f"buy_turnover = Rs{result['buy_turnover']} (expected Rs{BUY_TURN})")
check(result['sell_turnover'] == round(SELL_TURN, 2),
      f"sell_turnover = Rs{result['sell_turnover']} (expected Rs{SELL_TURN})")
print()

# ── Test 4: Gross P&L ─────────────────────────────────────
print("4. Testing gross P&L calculation...")

expected_gross = round(SELL_TURN - BUY_TURN, 2)    # 140.00
check(result['gross_pnl'] == expected_gross,
      f"gross_pnl = Rs{result['gross_pnl']} (expected Rs{expected_gross})")
print()

# ── Test 5: STT — sell side only ──────────────────────────
print("5. Testing STT (sell side only)...")

expected_stt = round(SELL_TURN * 0.00025, 4)    # 2.2925
check(abs(result['stt'] - expected_stt) < 0.001,
      f"STT = Rs{result['stt']} (expected Rs{expected_stt})")

# STT must be based on sell leg only — not total turnover
wrong_stt = round((BUY_TURN + SELL_TURN) * 0.00025, 4)
check(result['stt'] != wrong_stt,
      f"STT is NOT charged on both legs (would be Rs{wrong_stt} if wrong)")
print()

# ── Test 6: Exchange fee — both legs ──────────────────────
print("6. Testing NSE exchange fee (both legs)...")

expected_exch = round((BUY_TURN + SELL_TURN) * 0.0000297, 4)
check(abs(result['exchange_fee'] - expected_exch) < 0.001,
      f"Exchange fee = Rs{result['exchange_fee']} (expected Rs{expected_exch})")
print()

# ── Test 7: SEBI charge — both legs ───────────────────────
print("7. Testing SEBI charge (both legs)...")

expected_sebi = round((BUY_TURN + SELL_TURN) * 0.000001, 4)
check(abs(result['sebi_charge'] - expected_sebi) < 0.0001,
      f"SEBI charge = Rs{result['sebi_charge']} (expected Rs{expected_sebi})")
print()

# ── Test 8: Stamp duty — buy side only ────────────────────
print("8. Testing stamp duty (buy side only)...")

expected_stamp = round(BUY_TURN * 0.00015, 4)    # 1.3545
check(abs(result['stamp_duty'] - expected_stamp) < 0.001,
      f"Stamp duty = Rs{result['stamp_duty']} (expected Rs{expected_stamp})")

# Must NOT apply on sell leg
wrong_stamp = round((BUY_TURN + SELL_TURN) * 0.00015, 4)
check(result['stamp_duty'] != wrong_stamp,
      f"Stamp duty is NOT charged on both legs (would be Rs{wrong_stamp} if wrong)")
print()

# ── Test 9: GST on exchange fee + SEBI ────────────────────
print("9. Testing GST (18% on exchange fee + SEBI only)...")

expected_gst = round((result['exchange_fee'] + result['sebi_charge']) * 0.18, 4)
check(abs(result['gst'] - expected_gst) < 0.001,
      f"GST = Rs{result['gst']} (expected Rs{expected_gst})")
print()

# ── Test 10: Total charges arithmetic ─────────────────────
print("10. Testing total charges = sum of all components...")

manual_total = round(
    result['stt'] + result['exchange_fee'] + result['sebi_charge'] +
    result['stamp_duty'] + result['gst'],
    4
)
check(abs(result['total_charges'] - manual_total) < 0.0001,
      f"total_charges = Rs{result['total_charges']} (manual sum = Rs{manual_total})")
print()

# ── Test 11: net_pnl = gross_pnl - total_charges ──────────
print("11. Testing net_pnl = gross_pnl - total_charges...")

expected_net = round(result['gross_pnl'] - result['total_charges'], 2)
check(result['net_pnl'] == expected_net,
      f"net_pnl = Rs{result['net_pnl']} (expected Rs{expected_net})")

# Net P&L should be less than gross (charges reduce profit)
check(result['net_pnl'] < result['gross_pnl'],
      f"net_pnl (Rs{result['net_pnl']}) < gross_pnl (Rs{result['gross_pnl']})")
print()

# ── Test 12: SELL (short) direction ───────────────────────
print("12. Testing SELL (short) direction...")

# Short: entered at 1310, covered at 1290 (profitable short)
sell_result = calculate_charges(1310.0, 1290.0, 7, "SELL")

check(sell_result['buy_turnover']  == round(1290.0 * 7, 2),
      f"SELL: buy_turnover is the EXIT leg: Rs{sell_result['buy_turnover']}")
check(sell_result['sell_turnover'] == round(1310.0 * 7, 2),
      f"SELL: sell_turnover is the ENTRY leg: Rs{sell_result['sell_turnover']}")
check(sell_result['gross_pnl'] == round(1310.0 * 7 - 1290.0 * 7, 2),
      f"SELL gross_pnl = Rs{sell_result['gross_pnl']} (expected Rs140.00)")
check(sell_result['net_pnl'] < sell_result['gross_pnl'],
      f"SELL net_pnl (Rs{sell_result['net_pnl']}) < gross (Rs{sell_result['gross_pnl']})")
print()

# ── Test 13: Losing trade ─────────────────────────────────
print("13. Testing losing trade (net_pnl negative)...")

# BUY at 1290, exit at 1285 (loss)
loss_result = calculate_charges(1290.0, 1285.0, 7, "BUY")

check(loss_result['gross_pnl'] < 0,
      f"Losing trade: gross_pnl negative: Rs{loss_result['gross_pnl']}")
check(loss_result['net_pnl'] < loss_result['gross_pnl'],
      f"Charges make loss worse: net Rs{loss_result['net_pnl']} < gross Rs{loss_result['gross_pnl']}")
check(loss_result['total_charges'] > 0,
      f"Charges still positive even on a losing trade: Rs{loss_result['total_charges']}")
print()

# ── Test 14: Symmetry — BUY then SELL vs SELL then BUY ────
print("14. Testing charge symmetry (BUY 1290->1310 vs SELL 1310->1290)...")

buy_charges  = calculate_charges(1290.0, 1310.0, 7, "BUY")
sell_charges = calculate_charges(1310.0, 1290.0, 7, "SELL")

# Both trades have identical turnover and identical gross P&L
check(buy_charges['buy_turnover']   == sell_charges['buy_turnover'],
      f"buy_turnover matches: Rs{buy_charges['buy_turnover']}")
check(buy_charges['sell_turnover']  == sell_charges['sell_turnover'],
      f"sell_turnover matches: Rs{sell_charges['sell_turnover']}")
check(buy_charges['gross_pnl']      == sell_charges['gross_pnl'],
      f"gross_pnl matches: Rs{buy_charges['gross_pnl']}")
check(buy_charges['total_charges']  == sell_charges['total_charges'],
      f"total_charges matches: Rs{buy_charges['total_charges']}")
print()

# ── Test 15: ValueError on bad inputs ─────────────────────
print("15. Testing ValueError on invalid inputs...")

import traceback

def expect_value_error(fn, *args, name):
    try:
        fn(*args)
        check(False, f"Should have raised ValueError: {name}")
    except ValueError:
        check(True, f"ValueError raised for: {name}")

expect_value_error(calculate_charges, 1290.0, 1310.0, 7, "HOLD",   name="invalid direction")
expect_value_error(calculate_charges, -100.0, 1310.0, 7, "BUY",    name="negative entry price")
expect_value_error(calculate_charges, 1290.0, 1310.0, 0, "BUY",    name="zero quantity")
expect_value_error(calculate_charges, 1290.0, 0.0,    7, "BUY",    name="zero exit price")
print()

# ── Test 16: charges_summary() string format ──────────────
print("16. Testing charges_summary() helper...")

summary = charges_summary(result)
check(isinstance(summary, str),          "charges_summary() returns a string")
check("gross=" in summary,               "Contains gross= field")
check("charges=" in summary,             "Contains charges= field")
check("net=" in summary,                 "Contains net= field")
check("STT=" in summary,                 "Contains STT= field")
print()

# ── Test 17: Small trade (<100 shares low price) ──────────
print("17. Testing small trade (3 shares at Rs155 — e.g. TATASTEEL)...")

small = calculate_charges(155.0, 160.0, 3, "BUY")
check(small['gross_pnl'] == 15.0,
      f"gross_pnl = Rs{small['gross_pnl']} (expected Rs15.00)")
check(small['total_charges'] > 0,
      f"Charges > 0 even for small trade: Rs{small['total_charges']}")
check(small['total_charges'] < small['gross_pnl'],
      f"Charges (Rs{small['total_charges']}) < gross_pnl (Rs{small['gross_pnl']})")
print()

# ── Summary ────────────────────────────────────────────────
print("Reference trade breakdown:")
print(f"  RELIANCE BUY 7 @ Rs{ENTRY} -> Rs{EXIT}")
print(f"  buy_turnover:   Rs{result['buy_turnover']:.2f}")
print(f"  sell_turnover:  Rs{result['sell_turnover']:.2f}")
print(f"  gross_pnl:      Rs{result['gross_pnl']:.2f}")
print(f"  STT:            Rs{result['stt']:.4f}")
print(f"  Exchange fee:   Rs{result['exchange_fee']:.4f}")
print(f"  SEBI charge:    Rs{result['sebi_charge']:.4f}")
print(f"  Stamp duty:     Rs{result['stamp_duty']:.4f}")
print(f"  GST:            Rs{result['gst']:.4f}")
print(f"  Total charges:  Rs{result['total_charges']:.4f}")
print(f"  Net P&L:        Rs{result['net_pnl']:.2f}")
print()
print("-" * 52)
print("  All Phase 6 tests passed!")
print("  Transaction cost engine verified.")
print("  Ready to build Phase 7 -- Risk Manager.")
print("-" * 52 + "\n")
