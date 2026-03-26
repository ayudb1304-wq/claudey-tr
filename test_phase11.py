"""
test_phase11.py — Phase 11 Acceptance Tests: Angel One Data Feed

Tests angelone_feed.py internal helpers without hitting the live API,
plus optional live API tests when Angel One credentials are available.

The live tests (Section 3) are skipped automatically if .env is missing
or if credentials are invalid — so this script can also be run offline.

Usage:
    python test_phase11.py           (runs all tests, skips live if no .env)
    python test_phase11.py --live    (force-runs live API tests, fails if no creds)
"""

import sys
import os
import argparse
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytz

IST = pytz.timezone('Asia/Kolkata')

def check(condition, name, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         -> {detail}")
        sys.exit(1)

parser = argparse.ArgumentParser()
parser.add_argument("--live", action="store_true", help="Run live API tests")
args = parser.parse_args()

print("\n" + "=" * 55)
print("  PHASE 11 TESTS -- Angel One Data Feed")
print("=" * 55 + "\n")


# ── Section 1: Internal helpers (no API needed) ──────────────

print("1. Testing _candle_df() conversion...")

from angelone_feed import AngelOneDataFeed

# Patch load_nifty50_tokens so we don't need scrip_master.json
MOCK_TOKEN_MAP = {
    "RELIANCE": {"token": "2885", "exchange": "NSE", "full_name": "RELIANCE"},
    "INFY":     {"token": "1594", "exchange": "NSE", "full_name": "INFOSYS"},
}

with patch("angelone_feed.load_nifty50_tokens", return_value=MOCK_TOKEN_MAP), \
     patch("angelone_feed.auth.get_smart_api"):
    feed = AngelOneDataFeed.__new__(AngelOneDataFeed)
    feed._token_map = MOCK_TOKEN_MAP

# Test _candle_df with sample data
raw = [
    ["2026-03-26T09:15:00+05:30", 1450.0, 1465.0, 1445.0, 1460.0, 500000],
    ["2026-03-26T09:30:00+05:30", 1460.0, 1475.0, 1458.0, 1470.0, 420000],
    ["2026-03-26T09:45:00+05:30", 1470.0, 1480.0, 1462.0, 1465.0, 380000],
]

df = feed._candle_df(raw)

check(isinstance(df, pd.DataFrame),       "Returns a DataFrame")
check(len(df) == 3,                        f"3 rows parsed: got {len(df)}")
check(list(df.columns) == ['open', 'high', 'low', 'close', 'volume'],
      f"Columns correct: {list(df.columns)}")
check(df.index.tz is not None,             "Index is timezone-aware")
check(str(df.index.tz) == "Asia/Kolkata",  f"Index is IST: got {df.index.tz}")
check(df['open'].iloc[0]   == 1450.0,      "open parsed correctly")
check(df['high'].iloc[0]   == 1465.0,      "high parsed correctly")
check(df['low'].iloc[0]    == 1445.0,      "low parsed correctly")
check(df['close'].iloc[0]  == 1460.0,      "close parsed correctly")
check(df['volume'].iloc[0] == 500000,      "volume parsed correctly")
check(df.index.is_monotonic_increasing,    "Index sorted ascending (oldest first)")
print()

print("2. Testing _candle_df() edge cases...")

empty_df = feed._candle_df([])
check(isinstance(empty_df, pd.DataFrame), "Empty raw data returns empty DataFrame")
check(len(empty_df) == 0,                 "Empty DataFrame has 0 rows")
check(set(empty_df.columns) == {'open', 'high', 'low', 'close', 'volume'},
      "Empty DataFrame has correct columns")
print()


print("3. Testing _angel_symbol()...")

check(feed._angel_symbol("RELIANCE")  == "RELIANCE-EQ",  "RELIANCE -> RELIANCE-EQ")
check(feed._angel_symbol("INFY")      == "INFY-EQ",      "INFY -> INFY-EQ")
check(feed._angel_symbol("BAJAJ-AUTO") == "BAJAJ-AUTO-EQ", "BAJAJ-AUTO -> BAJAJ-AUTO-EQ")
print()


print("4. Testing _get_token()...")

from data_feed import DataFeedError

check(feed._get_token("RELIANCE") == "2885",  "RELIANCE token = 2885")
check(feed._get_token("INFY")     == "1594",  "INFY token = 1594")

# Unknown symbol raises DataFeedError
try:
    feed._get_token("UNKNOWN_STOCK")
    check(False, "Unknown symbol should raise DataFeedError")
except DataFeedError as e:
    check(True, f"Unknown symbol raises DataFeedError: {str(e)[:50]}")
print()


print("5. Testing _from_datetime() look-back window...")

# 10 days back should be well before today
from_dt = feed._from_datetime(10)
now     = datetime.now(IST)
diff_days = (now - from_dt).days

check(isinstance(from_dt, datetime),   "Returns a datetime")
check(from_dt.tzinfo is not None,      "Datetime is timezone-aware")
check(diff_days >= 10,                 f"Look-back >= 10 days: got {diff_days} days")
check(diff_days <= 30,                 f"Look-back <= 30 days (not excessive): {diff_days}")
check(from_dt.hour == 9,              f"Start hour is 9 AM: got {from_dt.hour}")
check(from_dt.minute == 15,          f"Start minute is 15: got {from_dt.minute}")

# 1 day back (for daily candle fetch)
from_1 = feed._from_datetime(1)
diff_1  = (now - from_1).days
check(diff_1 >= 1,   f"1-day look-back >= 1 day: got {diff_1}")
check(diff_1 <= 10,  f"1-day look-back <= 10 days: got {diff_1}")
print()


# ── Section 2: API call mocking ───────────────────────────────

print("6. Testing get_historical_candles() with mocked API...")

mock_response = {
    "status":  True,
    "message": "SUCCESS",
    "data":    raw,   # reuse the 3-row fixture from Section 1
}

mock_smart = MagicMock()
mock_smart.getCandleData.return_value = mock_response

with patch("angelone_feed.auth.get_smart_api", return_value=mock_smart), \
     patch("angelone_feed.time.sleep"):        # skip 400ms delay in tests
    result_df = feed.get_historical_candles("RELIANCE", days=3)

check(isinstance(result_df, pd.DataFrame), "Returns DataFrame")
check(len(result_df) == 3,                  f"3 candles returned: got {len(result_df)}")
check(mock_smart.getCandleData.called,      "getCandleData was called")

call_params = mock_smart.getCandleData.call_args[0][0]
check(call_params["exchange"]    == "NSE",          "exchange = NSE")
check(call_params["symboltoken"] == "2885",         "symboltoken = 2885 (RELIANCE)")
check(call_params["interval"]    == "FIFTEEN_MINUTE", "interval = FIFTEEN_MINUTE")
print()


print("7. Testing get_historical_candles() error handling...")

# API returns status=False
error_response = {"status": False, "message": "Invalid token"}
mock_smart2 = MagicMock()
mock_smart2.getCandleData.return_value = error_response

with patch("angelone_feed.auth.get_smart_api", return_value=mock_smart2), \
     patch("angelone_feed.time.sleep"):
    try:
        feed.get_historical_candles("RELIANCE", days=1)
        check(False, "Should raise DataFeedError on API error")
    except DataFeedError as e:
        check(True, f"DataFeedError raised on API failure: {str(e)[:55]}")

# Network exception
mock_smart3 = MagicMock()
mock_smart3.getCandleData.side_effect = ConnectionError("timeout")

with patch("angelone_feed.auth.get_smart_api", return_value=mock_smart3), \
     patch("angelone_feed.time.sleep"):
    try:
        feed.get_historical_candles("RELIANCE", days=1)
        check(False, "Should raise DataFeedError on network error")
    except DataFeedError as e:
        check(True, f"DataFeedError raised on network error: {str(e)[:55]}")
print()


print("8. Testing get_previous_day_ohlc() with mocked API...")

daily_raw = [
    ["2026-03-25T09:15:00+05:30", 1440.0, 1480.0, 1435.0, 1468.0, 5000000],
]

mock_smart4 = MagicMock()
mock_smart4.getCandleData.return_value = {"status": True, "data": daily_raw}

with patch("angelone_feed.auth.get_smart_api", return_value=mock_smart4), \
     patch("angelone_feed.time.sleep"):
    ohlc = feed.get_previous_day_ohlc("RELIANCE")

check(isinstance(ohlc, dict),        "Returns a dict")
check("open"  in ohlc,               "Has 'open' key")
check("high"  in ohlc,               "Has 'high' key")
check("low"   in ohlc,               "Has 'low' key")
check("close" in ohlc,               "Has 'close' key")
check("date"  in ohlc,               "Has 'date' key")
check(ohlc['open']  == 1440.0,       f"open = 1440: got {ohlc['open']}")
check(ohlc['high']  == 1480.0,       f"high = 1480: got {ohlc['high']}")
check(ohlc['low']   == 1435.0,       f"low = 1435: got {ohlc['low']}")
check(ohlc['close'] == 1468.0,       f"close = 1468: got {ohlc['close']}")

call_params = mock_smart4.getCandleData.call_args[0][0]
check(call_params["interval"] == "ONE_DAY",  "Uses ONE_DAY interval for prev-day OHLC")
print()


print("9. Testing get_previous_day_ohlc() on empty response...")

mock_smart5 = MagicMock()
mock_smart5.getCandleData.return_value = {"status": True, "data": []}

with patch("angelone_feed.auth.get_smart_api", return_value=mock_smart5), \
     patch("angelone_feed.time.sleep"):
    try:
        feed.get_previous_day_ohlc("RELIANCE")
        check(False, "Empty data should raise DataFeedError")
    except DataFeedError as e:
        check(True, f"DataFeedError raised on empty response: {str(e)[:55]}")
print()


print("10. Testing get_last_price() with mocked API...")

ltp_response = {
    "status": True,
    "data":   {"ltp": 1472.50, "tradingSymbol": "RELIANCE-EQ"}
}

mock_smart6 = MagicMock()
mock_smart6.ltpData.return_value = ltp_response

with patch("angelone_feed.auth.get_smart_api", return_value=mock_smart6), \
     patch("angelone_feed.time.sleep"):
    ltp = feed.get_last_price("RELIANCE")

check(isinstance(ltp, float),       f"Returns float: got {type(ltp)}")
check(ltp == 1472.50,               f"LTP = 1472.50: got {ltp}")

call_args = mock_smart6.ltpData.call_args[0]
check(call_args[0] == "NSE",           f"exchange = NSE: got {call_args[0]}")
check(call_args[1] == "RELIANCE-EQ",   f"symbol = RELIANCE-EQ: got {call_args[1]}")
check(call_args[2] == "2885",          f"token = 2885: got {call_args[2]}")
print()


print("11. Testing get_last_price() error handling...")

# Missing 'ltp' field
bad_ltp_response = {"status": True, "data": {"tradingSymbol": "RELIANCE-EQ"}}
mock_smart7 = MagicMock()
mock_smart7.ltpData.return_value = bad_ltp_response

with patch("angelone_feed.auth.get_smart_api", return_value=mock_smart7), \
     patch("angelone_feed.time.sleep"):
    try:
        feed.get_last_price("RELIANCE")
        check(False, "Missing ltp field should raise DataFeedError")
    except DataFeedError as e:
        check(True, f"DataFeedError on missing ltp: {str(e)[:50]}")
print()


print("12. Testing start_live_feed / stop_live_feed are no-ops...")

# Should not raise
feed.start_live_feed(["RELIANCE", "INFY"], lambda sym, c: None)
feed.stop_live_feed()
check(True, "start_live_feed() does not raise")
check(True, "stop_live_feed() does not raise")
print()


# ── Section 3: Live API tests (optional) ─────────────────────

live_available = False
if args.live or os.path.exists(".env"):
    try:
        from dotenv import load_dotenv
        load_dotenv()
        has_creds = all([
            os.getenv("ANGEL_ONE_API_KEY"),
            os.getenv("ANGEL_ONE_CLIENT_ID"),
            os.getenv("ANGEL_ONE_PASSWORD"),
            os.getenv("ANGEL_ONE_TOTP_SECRET"),
        ])
        live_available = has_creds
    except Exception:
        pass

if live_available:
    print("13. LIVE TEST — Angel One login + data fetch...")
    print("    (This makes real API calls and takes ~30 seconds)")

    try:
        import auth
        auth.login()

        from angelone_feed import AngelOneDataFeed as LiveFeed
        live_feed = LiveFeed()

        # Test get_previous_day_ohlc for RELIANCE
        ohlc = live_feed.get_previous_day_ohlc("RELIANCE")
        check(ohlc['close'] > 0,   f"RELIANCE prev-day close > 0: Rs{ohlc['close']}")
        check(ohlc['high']  >= ohlc['low'],  "high >= low (sanity check)")
        check(len(ohlc['date']) == 10,       f"date format YYYY-MM-DD: got {ohlc['date']}")

        # Test get_historical_candles for RELIANCE (days=1)
        df = live_feed.get_historical_candles("RELIANCE", days=1)
        check(isinstance(df, pd.DataFrame),  "get_historical_candles returns DataFrame")
        # During market hours we'd have candles; outside hours data may be empty
        if len(df) > 0:
            check(df['close'].iloc[-1] > 0,  f"Last close > 0: Rs{df['close'].iloc[-1]}")
        else:
            print("  [INFO] No candles today (market may be closed) — OK")

        # Test get_last_price for RELIANCE
        ltp = live_feed.get_last_price("RELIANCE")
        check(ltp > 0,  f"RELIANCE LTP > 0: Rs{ltp:.2f}")

        print()
        print("  LIVE tests passed.")

    except Exception as e:
        print(f"  [FAIL] Live test error: {e}")
        if args.live:
            sys.exit(1)

else:
    print("13. Live API tests: SKIPPED (run with --live flag or add .env file)")
    print()


print("-" * 55)
print("  All Phase 11 tests passed!")
print("  AngelOneDataFeed verified against mocked Angel One API.")
print("  Ready to set DATA_SOURCE = 'angelone' and run live.")
print("-" * 55 + "\n")
