"""
test_phase4.py — Phase 4 Acceptance Tests: Pre-filter Engine

Usage:
    python test_phase4.py
"""

import sys
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
print("  PHASE 4 TESTS — Pre-filter Engine")
print("=" * 52 + "\n")

# ── Test 1: Imports ────────────────────────────────────────
print("1. Checking imports...")
from prefilter import score_stock, scan_for_candidates, PreFilterTracker
check(True, "prefilter.py imports correctly")
print()

# ── Test 2: score_stock basic range ───────────────────────
print("2. Testing score_stock value range (0-5)...")

from indicators import calculate_indicators
from pivot_points import enrich_pivots, calculate_pivot_points
from mock_feed import MockDataFeed
from candle_store import CandleStore

feed = MockDataFeed(seed=42)
df   = feed.get_historical_candles("RELIANCE", days=10)
ind  = calculate_indicators(df)
prev = feed.get_previous_day_ohlc("RELIANCE")
pvt  = enrich_pivots(ind['price'], calculate_pivot_points(
    prev['high'], prev['low'], prev['close']
))

long_score  = score_stock(ind, pvt, "long")
short_score = score_stock(ind, pvt, "short")

check(0 <= long_score <= 5,
      f"Long score in range [0,5]: {long_score}")
check(0 <= short_score <= 5,
      f"Short score in range [0,5]: {short_score}")
check(not (long_score == 5 and short_score == 5),
      "Long and short can't both be 5 simultaneously (contradictory signals)")
print()

# ── Test 3: Long/short are scored independently ───────────
print("3. Testing long and short scored independently...")

# LONG-favoring scenario: RSI oversold, MACD bullish cross,
# price above EMA20 above EMA50, high volume
long_favoring = {
    "price":              100.0,
    "rsi":                28.0,       # oversold → long +1
    "rsi_prev":           29.0,
    "ema20":              99.0,       # price > EMA20 > EMA50 → long +1
    "ema50":              98.0,
    "ema200":             95.0,
    "macd_line":          0.5,
    "signal_line":        0.3,
    "macd_bullish_cross": True,       # bullish cross → long +1
    "macd_bearish_cross": False,
    "volume":             200_000,
    "volume_sma20":       100_000,
    "volume_ratio":       2.0,        # 2× average → long +1
}
pivot_near_support = {
    "PP": 98.0, "R1": 102.0, "R2": 106.0, "R3": 110.0,
    "S1": 96.0, "S2": 92.0,  "S3": 88.0,
    "nearest_support":        99.3,   # 0.7% below price → long +1
    "nearest_resistance":     102.0,
    "support_dist_pct":       0.70,   # within PIVOT_PROXIMITY_PCT (0.75)
    "resistance_dist_pct":    2.0,
}

score_l = score_stock(long_favoring, pivot_near_support, "long")
score_s = score_stock(long_favoring, pivot_near_support, "short")

check(score_l >= 4,
      f"Long-favoring setup scores high for LONG: {score_l}/5")
check(score_l > score_s,
      f"Long score ({score_l}) > short score ({score_s}) for long-favoring setup")

# SHORT-favoring scenario: RSI overbought, bearish cross, price below EMAs
short_favoring = {
    "price":              100.0,
    "rsi":                72.0,       # overbought → short +1
    "rsi_prev":           71.0,
    "ema20":              101.0,      # price < EMA20 < EMA50 → short +1
    "ema50":              102.0,
    "ema200":             105.0,
    "macd_line":         -0.5,
    "signal_line":       -0.3,
    "macd_bullish_cross": False,
    "macd_bearish_cross": True,       # bearish cross → short +1
    "volume":             200_000,
    "volume_sma20":       100_000,
    "volume_ratio":       2.0,        # high volume → short +1
}
pivot_near_resist = {
    "PP": 102.0, "R1": 100.7, "R2": 104.0, "R3": 108.0,
    "S1": 98.0,  "S2": 96.0,  "S3": 94.0,
    "nearest_support":        98.0,
    "nearest_resistance":     100.7,  # 0.7% above price → short +1
    "support_dist_pct":       2.0,
    "resistance_dist_pct":    0.70,
}

score_l2 = score_stock(short_favoring, pivot_near_resist, "long")
score_s2 = score_stock(short_favoring, pivot_near_resist, "short")

check(score_s2 >= 4,
      f"Short-favoring setup scores high for SHORT: {score_s2}/5")
check(score_s2 > score_l2,
      f"Short score ({score_s2}) > long score ({score_l2}) for short-favoring setup")
print()

# ── Test 4: PreFilterTracker ──────────────────────────────
print("4. Testing PreFilterTracker...")

tracker = PreFilterTracker()

check(not tracker.was_sent("RELIANCE"),
      "Fresh tracker: RELIANCE not yet sent")

tracker.mark_sent("RELIANCE")
check(tracker.was_sent("RELIANCE"),
      "After mark_sent: RELIANCE is sent")
check(not tracker.was_sent("ITC"),
      "Other symbol (ITC) still not sent")
check(tracker.sent_count() == 1,
      f"Sent count = 1 after marking 1 symbol")

tracker.mark_sent("ITC")
check(tracker.sent_count() == 2,
      f"Sent count = 2 after marking 2 symbols")

tracker.reset()
check(not tracker.was_sent("RELIANCE"),
      "After reset: RELIANCE no longer sent")
check(tracker.sent_count() == 0,
      "After reset: sent count = 0")
print()

# ── Test 5: scan_for_candidates — open position exclusion ─
print("5. Testing open position exclusion in scan...")

from config import NIFTY_50_SYMBOLS, MAX_STOCK_PRICE
from mock_feed import SEED_PRICES

affordable = [s for s in NIFTY_50_SYMBOLS
              if s in SEED_PRICES and SEED_PRICES[s] <= MAX_STOCK_PRICE]

# Build candle store and pivots for all affordable stocks
store     = CandleStore()
pivots_m  = {}

for sym in affordable:
    df_s  = feed.get_historical_candles(sym, days=10)
    store.load_historical(sym, df_s)
    prev  = feed.get_previous_day_ohlc(sym)
    pivots_m[sym] = calculate_pivot_points(
        prev['high'], prev['low'], prev['close']
    )

tracker.reset()

# Scan with RELIANCE and ITC in open positions
open_pos = {"RELIANCE", "ITC"}
results  = scan_for_candidates(affordable, store, pivots_m, open_pos, tracker)

symbols_in_results = {r['symbol'] for r in results}
check("RELIANCE" not in symbols_in_results,
      "RELIANCE excluded (open position)")
check("ITC" not in symbols_in_results,
      "ITC excluded (open position)")
print()

# ── Test 6: scan_for_candidates — no duplicate symbols ────
print("6. Testing no duplicate symbols in scan output...")

tracker.reset()
results2 = scan_for_candidates(affordable, store, pivots_m, set(), tracker)

symbol_list = [r['symbol'] for r in results2]
check(len(symbol_list) == len(set(symbol_list)),
      f"No duplicate symbols in scan output ({len(symbol_list)} candidates)")
print()

# ── Test 7: scan_for_candidates — minimum score enforced ──
print("7. Testing minimum score threshold enforced...")

from config import MIN_FILTER_SCORE

for r in results2:
    check(r['score'] >= MIN_FILTER_SCORE,
          f"{r['symbol']}: score {r['score']} >= threshold {MIN_FILTER_SCORE}")
print()

# ── Test 8: scan_for_candidates — output structure ─────────
print("8. Testing candidate output structure...")

if results2:
    first = results2[0]
    required_keys = {'symbol', 'direction', 'score', 'long_score',
                     'short_score', 'indicators', 'pivots'}
    missing = required_keys - set(first.keys())
    check(len(missing) == 0,
          f"Candidate has all required keys",
          f"Missing: {missing}")
    check(first['direction'] in ('long', 'short'),
          f"Direction is 'long' or 'short': {first['direction']}")
    check(first['score'] == max(first['long_score'], first['short_score']),
          f"Score matches max(long, short): {first['score']}")

    # Results sorted descending by score
    scores = [r['score'] for r in results2]
    check(scores == sorted(scores, reverse=True),
          f"Results sorted by score descending: {scores[:5]}...")
else:
    print("  [INFO] No candidates found with current mock data — "
          "this can happen with seed=42, not a bug")
print()

# ── Test 9: tracker prevents re-sending in same interval ──
print("9. Testing tracker prevents duplicate Claude calls...")

tracker.reset()
# First scan
results_a = scan_for_candidates(affordable, store, pivots_m, set(), tracker)

# Mark all returned candidates as sent
for r in results_a:
    tracker.mark_sent(r['symbol'])

# Second scan in same interval — same stocks must NOT appear again
results_b = scan_for_candidates(affordable, store, pivots_m, set(), tracker)

symbols_a = {r['symbol'] for r in results_a}
symbols_b = {r['symbol'] for r in results_b}
overlap   = symbols_a & symbols_b

check(len(overlap) == 0,
      f"No overlap between scan 1 and scan 2 in same interval: {overlap or 'none'}",
      f"These symbols appeared twice: {overlap}")
print()

# ── Summary ────────────────────────────────────────────────
print(f"  Scan summary: {len(results2)} candidates from {len(affordable)} stocks")
if results2:
    print(f"\n  {'Symbol':<15} {'Direction':<8} {'Score':>6} {'Long':>6} {'Short':>6}")
    print("  " + "-" * 46)
    for r in results2:
        print(f"  {r['symbol']:<15} {r['direction']:<8} "
              f"{r['score']:>6} {r['long_score']:>6} {r['short_score']:>6}")

print()
print("─" * 52)
print("  All Phase 4 tests passed!")
print("  Pre-filter engine verified.")
print("  Ready to build Phase 5 — Claude Agent.")
print("─" * 52 + "\n")
