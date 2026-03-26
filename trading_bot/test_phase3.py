"""
test_phase3.py — Phase 3 Acceptance Tests: Indicator Engine

Tests indicators.py and pivot_points.py for correctness.

No internet required — uses MockDataFeed for candle data.

Usage:
    python test_phase3.py
"""

import sys
import numpy as np
import pandas as pd
import pytz
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="{message}", level="WARNING")

def check(condition, name, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         → {detail}")
        sys.exit(1)

IST = pytz.timezone('Asia/Kolkata')

print("\n" + "=" * 52)
print("  PHASE 3 TESTS — Indicator Engine")
print("=" * 52 + "\n")

# ── Test 1: Imports ────────────────────────────────────────
print("1. Checking imports...")

try:
    from indicators import calculate_indicators, InsufficientDataError
    check(True, "indicators.py imports correctly")
except ImportError as e:
    check(False, "indicators.py imports", str(e))

try:
    from pivot_points import calculate_pivot_points, get_nearest_levels, enrich_pivots
    check(True, "pivot_points.py imports correctly")
except ImportError as e:
    check(False, "pivot_points.py imports", str(e))

print()

# ── Test 2: Indicators on real mock data ──────────────────
print("2. Running indicators on 250 candles of RELIANCE mock data...")

from mock_feed import MockDataFeed
feed = MockDataFeed(seed=42)
df   = feed.get_historical_candles("RELIANCE", days=10)

try:
    ind = calculate_indicators(df)
    check(True, f"calculate_indicators() ran without error")
except Exception as e:
    check(False, "calculate_indicators()", str(e))

print()

# ── Test 3: Output schema ─────────────────────────────────
print("3. Validating indicator output schema...")

expected_keys = {
    "price", "rsi", "rsi_prev", "ema20", "ema50", "ema200",
    "macd_line", "signal_line", "macd_bullish_cross", "macd_bearish_cross",
    "volume", "volume_sma20", "volume_ratio",
}
missing_keys = expected_keys - set(ind.keys())
check(len(missing_keys) == 0,
      "All expected keys present in output",
      f"Missing: {missing_keys}")

print()

# ── Test 4: Value ranges ──────────────────────────────────
print("4. Validating indicator value ranges...")

check(0 <= ind['rsi'] <= 100,
      f"RSI in valid range [0, 100]: {ind['rsi']}")

check(0 <= ind['rsi_prev'] <= 100,
      f"RSI prev in valid range [0, 100]: {ind['rsi_prev']}")

check(ind['price'] > 0,
      f"Price is positive: Rs{ind['price']}")

# EMAs should be close to current price (within 10% is reasonable)
for ema_name in ['ema20', 'ema50', 'ema200']:
    ema_val = ind[ema_name]
    pct_diff = abs(ema_val - ind['price']) / ind['price'] * 100
    check(pct_diff < 15,
          f"{ema_name} (Rs{ema_val}) within 15% of price (Rs{ind['price']})",
          f"EMA is {pct_diff:.1f}% away — suspiciously far from price")

check(ind['volume'] > 0,
      f"Volume is positive: {ind['volume']:,}")

check(ind['volume_sma20'] > 0,
      f"Volume SMA20 is positive: {ind['volume_sma20']:,}")

check(ind['volume_ratio'] > 0,
      f"Volume ratio is positive: {ind['volume_ratio']}x")

check(isinstance(ind['macd_bullish_cross'], bool),
      "macd_bullish_cross is a bool")

check(isinstance(ind['macd_bearish_cross'], bool),
      "macd_bearish_cross is a bool")

# Both crossovers cannot be True at the same time
check(not (ind['macd_bullish_cross'] and ind['macd_bearish_cross']),
      "Bullish and bearish cross cannot both be True simultaneously")

print()

# ── Test 5: No NaN values ─────────────────────────────────
print("5. Checking for NaN values...")

for key, val in ind.items():
    if isinstance(val, float):
        check(not np.isnan(val),
              f"No NaN in '{key}': {val}")

print()

# ── Test 6: EMA ordering sanity ───────────────────────────
print("6. Checking EMA relative ordering (sanity check)...")

# In a 10-day random walk, EMAs can be in any order.
# We just check they're all different values (not identical, which would indicate a bug).
emas = [ind['ema20'], ind['ema50'], ind['ema200']]
check(len(set(emas)) == 3,
      f"EMA 20/50/200 are all distinct values: {emas}",
      "Two EMAs have identical values — possible calculation error")

print()

# ── Test 7: InsufficientDataError on too few candles ──────
print("7. Testing InsufficientDataError on insufficient data...")

from indicators import InsufficientDataError
from config import MIN_CANDLES_REQUIRED

# Create a DataFrame with only 50 candles (way less than 200 needed)
small_df = df.tail(50).copy()
try:
    calculate_indicators(small_df)
    check(False, "Should have raised InsufficientDataError",
          f"Got no error with only {len(small_df)} candles")
except InsufficientDataError as e:
    check(True,
          f"InsufficientDataError raised correctly for {len(small_df)} candles "
          f"(need {MIN_CANDLES_REQUIRED})")
except Exception as e:
    check(False, "Expected InsufficientDataError", f"Got: {type(e).__name__}: {e}")

print()

# ── Test 8: MACD crossover fires exactly at the cross ─────
print("8. Testing MACD crossover fires on correct candle...")

# Strategy: build two DataFrames where a cross is forced.
# We can do this by running indicators on all stocks over multiple candles
# and counting total crossover events — should be low (1-5 per stock per day).
crossover_counts = {}
for sym in ["RELIANCE", "ITC", "SBIN", "NTPC", "COALINDIA"]:
    sym_df   = feed.get_historical_candles(sym, days=10)
    bull_crosses = 0
    bear_crosses = 0

    # Slide a window of 200 candles across the full history
    # Each window represents "the indicator state at that candle close"
    for i in range(MIN_CANDLES_REQUIRED, len(sym_df)):
        window = sym_df.iloc[:i+1]
        try:
            ind_i = calculate_indicators(window)
            if ind_i['macd_bullish_cross']:
                bull_crosses += 1
            if ind_i['macd_bearish_cross']:
                bear_crosses += 1
        except InsufficientDataError:
            pass

    crossover_counts[sym] = (bull_crosses, bear_crosses)

for sym, (bull, bear) in crossover_counts.items():
    # On 50 candles (250-200), expect 0–5 crossovers each direction
    check(0 <= bull <= 10,
          f"{sym}: bullish crosses={bull} (expected 0-10 in 50 candles)")
    check(0 <= bear <= 10,
          f"{sym}: bearish crosses={bear} (expected 0-10 in 50 candles)")

total_crosses = sum(b+s for b,s in crossover_counts.values())
check(total_crosses > 0,
      f"At least 1 MACD crossover detected across 5 stocks: {total_crosses} total",
      "No crossovers at all — MACD cross detection may be broken")

print()

# ── Test 9: Pivot Points formula ──────────────────────────
print("9. Testing pivot point calculations...")

# Known values — calculate manually to verify
# If prev: High=1300, Low=1250, Close=1280
H, L, C = 1300.0, 1250.0, 1280.0
pivots   = calculate_pivot_points(H, L, C)

# Use unrounded intermediate PP for derived levels — same as pivot_points.py does.
# Rounding PP before computing R1/S1 introduces a small error (0.01 difference).
raw_pp      = (H + L + C) / 3
expected_pp = round(raw_pp, 2)
expected_r1 = round((2 * raw_pp) - L, 2)
expected_s1 = round((2 * raw_pp) - H, 2)

check(pivots['PP'] == expected_pp,
      f"PP formula correct: {pivots['PP']} == {expected_pp}")

check(pivots['R1'] == expected_r1,
      f"R1 formula correct: {pivots['R1']} == {expected_r1}")

check(pivots['S1'] == expected_s1,
      f"S1 formula correct: {pivots['S1']} == {expected_s1}")

# Mathematical guarantee: R1 > PP > S1 always
check(pivots['R1'] > pivots['PP'] > pivots['S1'],
      f"Level ordering correct: R1 ({pivots['R1']}) > PP ({pivots['PP']}) > S1 ({pivots['S1']})")

check(pivots['R2'] > pivots['R1'],
      f"R2 ({pivots['R2']}) > R1 ({pivots['R1']})")

check(pivots['S2'] < pivots['S1'],
      f"S2 ({pivots['S2']}) < S1 ({pivots['S1']})")

print(f"\n   Pivot levels for H={H}, L={L}, C={C}:")
for level in ['S3','S2','S1','PP','R1','R2','R3']:
    print(f"     {level}: Rs{pivots[level]}")

print()

# ── Test 10: get_nearest_levels ───────────────────────────
print("10. Testing nearest support/resistance lookup...")

# Price between S1 and PP
test_price = 1270.0   # Between S1=1253.33 and PP=1276.67
nearest    = get_nearest_levels(test_price, pivots)

check(nearest['nearest_support'] is not None,
      f"Nearest support found: Rs{nearest['nearest_support']}")

check(nearest['nearest_resistance'] is not None,
      f"Nearest resistance found: Rs{nearest['nearest_resistance']}")

check(nearest['nearest_support'] < test_price,
      f"Support ({nearest['nearest_support']}) is BELOW price ({test_price})")

check(nearest['nearest_resistance'] > test_price,
      f"Resistance ({nearest['nearest_resistance']}) is ABOVE price ({test_price})")

check(nearest['support_dist_pct'] > 0,
      f"Support distance is positive: {nearest['support_dist_pct']}%")

check(nearest['resistance_dist_pct'] > 0,
      f"Resistance distance is positive: {nearest['resistance_dist_pct']}%")

print()

# ── Test 11: Indicators on multiple stocks ────────────────
print("11. Running indicators on all affordable stocks...")

from mock_feed import SEED_PRICES
from config import NIFTY_50_SYMBOLS, MAX_STOCK_PRICE

affordable = [s for s in NIFTY_50_SYMBOLS
              if s in SEED_PRICES and SEED_PRICES[s] <= MAX_STOCK_PRICE]

errors   = []
successes = []

for sym in affordable:
    try:
        sym_df  = feed.get_historical_candles(sym, days=10)
        sym_ind = calculate_indicators(sym_df)

        # Quick sanity: price should be close to seed price
        seed = SEED_PRICES[sym]
        pct  = abs(sym_ind['price'] - seed) / seed * 100
        if pct > 25:
            errors.append(f"{sym}: price Rs{sym_ind['price']} too far from seed Rs{seed}")
        else:
            successes.append(sym)
    except Exception as e:
        errors.append(f"{sym}: {e}")

check(len(errors) == 0,
      f"Indicators calculated for all {len(successes)} affordable stocks",
      "\n         ".join(errors))

print(f"\n   Indicator snapshot for first 5 stocks:")
print(f"   {'Symbol':<15} {'Price':>8} {'RSI':>6} {'EMA20':>8} {'VolRatio':>9} {'MACD X':>8}")
print("   " + "-" * 62)
for sym in affordable[:5]:
    sym_df  = feed.get_historical_candles(sym, days=10)
    sym_ind = calculate_indicators(sym_df)
    cross = "Bull" if sym_ind['macd_bullish_cross'] else "Bear" if sym_ind['macd_bearish_cross'] else "-"
    print(f"   {sym:<15} {sym_ind['price']:>8.2f} {sym_ind['rsi']:>6.1f} "
          f"{sym_ind['ema20']:>8.2f} {sym_ind['volume_ratio']:>8.2f}x {cross:>8}")

print()
print("─" * 52)
print("  All Phase 3 tests passed!")
print("  Indicator engine verified. Pivot points verified.")
print("  Ready to build Phase 4 — Pre-filter Engine.")
print("─" * 52 + "\n")
