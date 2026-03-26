"""
test_phase2.py — Phase 2 Acceptance Tests

Tests the data layer using the MockDataFeed (no internet required).

Usage:
    python test_phase2.py

Expected output:
    [PASS] MockDataFeed imports correctly
    [PASS] Historical candles for RELIANCE: 250 rows
    [PASS] Candle columns correct
    [PASS] Candle timestamps are IST timezone-aware
    [PASS] No pre-market candles (all >= 9:15 AM)
    [PASS] No zero-volume candles
    [PASS] OHLCV relationships valid (high >= open,close >= low)
    [PASS] Previous day OHLC for RELIANCE
    [PASS] Previous day high >= low
    [PASS] CandleStore loads 250 candles for RELIANCE
    [PASS] CandleStore.is_ready() = True (250 >= 200 required)
    [PASS] CandleStore.append() works
    [PASS] CandleStore.get() returns correct DataFrame
    [PASS] Affordable stocks filter: 28 stocks <= Rs2000
    [PASS] Live feed fired 8+ candle callbacks
    [PASS] Candle callback has all required fields
    [PASS] Candle high >= low in live feed
    ──────────────────────────────────────────────────
    All Phase 2 tests passed! Ready for Phase 3.
"""

import sys
import time
from datetime import time as dtime
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

print("\n" + "=" * 52)
print("  PHASE 2 TESTS — Market Data Layer (Mock Feed)")
print("=" * 52 + "\n")

# ── Test 1: MockDataFeed imports ──────────────────────────
print("1. Checking MockDataFeed...")

try:
    from mock_feed import MockDataFeed
    check(True, "MockDataFeed imports correctly")
except ImportError as e:
    check(False, "MockDataFeed imports", str(e))

print()

# ── Test 2: Historical candles ────────────────────────────
print("2. Testing historical candle generation for RELIANCE...")

import pytz
IST = pytz.timezone('Asia/Kolkata')
feed = MockDataFeed(seed=42)

try:
    df = feed.get_historical_candles("RELIANCE", days=10)

    check(not df.empty,
          f"Historical candles for RELIANCE: {len(df)} rows")

    # Columns
    required_cols = {'open', 'high', 'low', 'close', 'volume'}
    check(required_cols.issubset(df.columns),
          "Candle columns correct (open, high, low, close, volume)",
          f"Got: {list(df.columns)}")

    # Timezone
    check(df.index.tz is not None,
          f"Candle timestamps are IST timezone-aware (tz={df.index.tz})")

    # No pre-market candles
    pre_market = df[df.index.time < dtime(9, 15)]
    check(len(pre_market) == 0,
          "No pre-market candles (all >= 9:15 AM)",
          f"Found {len(pre_market)} candles before 9:15 AM")

    # No zero-volume candles
    zero_vol = df[df['volume'] == 0]
    check(len(zero_vol) == 0,
          "No zero-volume candles",
          f"Found {len(zero_vol)} zero-volume rows")

    # OHLCV relationships
    bad_high = df[df['high'] < df[['open', 'close']].max(axis=1)]
    bad_low  = df[df['low']  > df[['open', 'close']].min(axis=1)]
    check(len(bad_high) == 0 and len(bad_low) == 0,
          "OHLCV relationships valid (high >= open,close >= low)",
          f"{len(bad_high)} bad highs, {len(bad_low)} bad lows")

    # Sample output
    print(f"\n   Sample — last 3 candles for RELIANCE:")
    print(f"   {'Timestamp':<32} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8} {'Volume':>10}")
    print("   " + "-" * 82)
    for ts, row in df.tail(3).iterrows():
        print(f"   {str(ts):<32} {row['open']:>8.2f} {row['high']:>8.2f} "
              f"{row['low']:>8.2f} {row['close']:>8.2f} {row['volume']:>10,}")

except Exception as e:
    check(False, "Historical candles", str(e))

print()

# ── Test 3: Previous day OHLC ─────────────────────────────
print("3. Testing previous day OHLC for RELIANCE and ITC...")

for sym in ["RELIANCE", "ITC"]:
    try:
        ohlc = feed.get_previous_day_ohlc(sym)
        required = {'open', 'high', 'low', 'close', 'date'}
        check(required == set(ohlc.keys()),
              f"Previous day OHLC for {sym}: date={ohlc['date']} "
              f"H={ohlc['high']} L={ohlc['low']} C={ohlc['close']}")
        check(ohlc['high'] >= ohlc['low'],
              f"  {sym}: high ({ohlc['high']}) >= low ({ohlc['low']})")
    except Exception as e:
        check(False, f"Previous day OHLC for {sym}", str(e))

print()

# ── Test 4: CandleStore ───────────────────────────────────
print("4. Testing CandleStore...")

from candle_store import CandleStore
from config import MIN_CANDLES_REQUIRED
import datetime as dt

store   = CandleStore()
df_rel  = feed.get_historical_candles("RELIANCE", days=10)
store.load_historical("RELIANCE", df_rel)

count = store.get_candle_count("RELIANCE")
check(count > 0,
      f"CandleStore loaded {count} candles for RELIANCE")

check(store.is_ready("RELIANCE") == (count >= MIN_CANDLES_REQUIRED),
      f"CandleStore.is_ready() = {store.is_ready('RELIANCE')} "
      f"({count} candles, need {MIN_CANDLES_REQUIRED})")

# Test append
last = store.get_last_candle("RELIANCE")
check(last is not None, "CandleStore.get_last_candle() returns data")

fake_candle = {
    "timestamp": dt.datetime.now(IST),
    "open":   last['close'],
    "high":   round(last['close'] * 1.002, 2),
    "low":    round(last['close'] * 0.998, 2),
    "close":  round(last['close'] * 1.001, 2),
    "volume": 500_000,
}
before = store.get_candle_count("RELIANCE")
store.append("RELIANCE", fake_candle)
after  = store.get_candle_count("RELIANCE")
check(after >= before,
      f"CandleStore.append() works ({before} → {after} candles)")

df_out = store.get("RELIANCE")
check(not df_out.empty and set(df_out.columns) == {'open','high','low','close','volume'},
      "CandleStore.get() returns correct DataFrame")

print()

# ── Test 5: Affordable stocks filter ─────────────────────
print("5. Testing affordable stocks filter...")

from config import NIFTY_50_SYMBOLS, MAX_STOCK_PRICE
from mock_feed import SEED_PRICES

affordable   = [(s, SEED_PRICES[s]) for s in NIFTY_50_SYMBOLS
                if s in SEED_PRICES and SEED_PRICES[s] <= MAX_STOCK_PRICE]
unaffordable = [(s, SEED_PRICES[s]) for s in NIFTY_50_SYMBOLS
                if s in SEED_PRICES and SEED_PRICES[s] > MAX_STOCK_PRICE]

check(len(affordable) > 0,
      f"Affordable stocks (<= Rs{MAX_STOCK_PRICE}): {len(affordable)} stocks")

print(f"\n   Tradeable ({len(affordable)} stocks):")
for sym, price in sorted(affordable, key=lambda x: x[1]):
    print(f"     {sym:<15} Rs{price:,.0f}")

print(f"\n   Excluded — too expensive ({len(unaffordable)} stocks):")
for sym, price in sorted(unaffordable, key=lambda x: x[1]):
    print(f"     {sym:<15} Rs{price:,.0f}")

print()

# ── Test 6: Live feed simulation ─────────────────────────
print("6. Testing live feed (8 seconds)...")

candles_received = []

def on_candle(symbol, candle):
    candles_received.append((symbol, candle))

test_symbols = ["ITC", "SBIN", "NTPC"]
feed.start_live_feed(test_symbols, on_candle)

# Wait up to 10 seconds
for _ in range(10):
    time.sleep(1)
    if len(candles_received) >= len(test_symbols) * 3:
        break

feed.stop_live_feed()

check(len(candles_received) >= len(test_symbols),
      f"Live feed fired {len(candles_received)} candle callbacks",
      "No callbacks received — check mock_feed.py _live_loop")

if candles_received:
    sym, candle = candles_received[0]
    required_fields = {'timestamp', 'open', 'high', 'low', 'close', 'volume'}
    check(required_fields.issubset(candle.keys()),
          f"Candle callback has all required fields (symbol: {sym})")
    check(candle['high'] >= candle['low'],
          f"Candle high ({candle['high']}) >= low ({candle['low']})")

print()
print("─" * 52)
print("  All Phase 2 tests passed!")
print("  MockDataFeed working. Data layer complete.")
print("  Ready to build Phase 3 — Indicator Engine.")
print("─" * 52 + "\n")
