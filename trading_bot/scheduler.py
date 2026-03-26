"""
scheduler.py — Market Timing & Candle Schedule Utilities

Provides pure functions for market hours, trading day checks, and
candle boundary detection. No state, no I/O — only datetime math.

CANDLE BOUNDARIES:
  NSE 15-min candles close at :00 and :15 and :30 and :45 of each hour.
  First candle of the day: 9:15 AM → closes at 9:30 AM
  Last candle of the day:  3:15 PM → closes at 3:30 PM (market close)
  The bot reacts to each candle CLOSE, not open.

USAGE:
  from scheduler import is_trading_day, is_market_open, seconds_until_next_candle
"""

from datetime import date, datetime, timedelta

from config import (
    IST,
    MARKET_OPEN,
    MARKET_CLOSE,
    NSE_HOLIDAYS_2026,
    CANDLE_INTERVAL_MINUTES,
    SKIP_FIRST_CANDLE,
)

# Convert holiday strings to date objects once at import time
_NSE_HOLIDAY_DATES: frozenset = frozenset(
    date.fromisoformat(d) for d in NSE_HOLIDAYS_2026
)


def is_trading_day(dt: datetime) -> bool:
    """
    True if `dt` falls on a day when NSE is open (weekday, not a holiday).

    Args:
        dt: Any datetime (will be converted to IST date)
    """
    d = dt.astimezone(IST).date()
    return d.weekday() < 5 and d not in _NSE_HOLIDAY_DATES    # 0=Mon, 4=Fri


def is_market_open(dt: datetime) -> bool:
    """
    True if `dt` is within NSE market hours on a trading day.

    Market hours: 9:15 AM – 3:30 PM IST (inclusive).
    """
    if not is_trading_day(dt):
        return False
    t = dt.astimezone(IST).time()
    return MARKET_OPEN <= t <= MARKET_CLOSE


def is_candle_close(dt: datetime) -> bool:
    """
    True if `dt` is exactly at a 15-minute candle boundary.

    Boundaries: XX:00, XX:15, XX:30, XX:45 of each hour.
    The first valid candle close is 9:30 AM (if SKIP_FIRST_CANDLE is True)
    or 9:15 AM otherwise.

    Note: This checks the minute only. Caller should check seconds == 0
    if real-time precision is needed.
    """
    if not is_market_open(dt):
        return False

    t = dt.astimezone(IST).time()

    # Must be at a 15-min boundary
    if t.minute % CANDLE_INTERVAL_MINUTES != 0:
        return False

    # Skip the very first candle of the day (9:15 open → 9:30 close is first valid)
    if SKIP_FIRST_CANDLE and t.hour == 9 and t.minute == 15:
        return False

    return True


def seconds_until_next_candle(dt: datetime) -> int:
    """
    Seconds until the next 15-minute candle close.

    If already at a candle boundary, returns 0 (act now).
    If market is closed, returns seconds until market open tomorrow
    (or next trading day).

    Args:
        dt: Current datetime (timezone-aware)

    Returns:
        int — seconds to sleep
    """
    now_ist = dt.astimezone(IST)

    # If currently at a boundary, act immediately
    if is_candle_close(now_ist):
        return 0

    # Find the next boundary within the same day
    minutes = now_ist.hour * 60 + now_ist.minute
    seconds = now_ist.second

    # Round up to next 15-min mark
    remainder = minutes % CANDLE_INTERVAL_MINUTES
    if remainder == 0:
        mins_to_next = 0
    else:
        mins_to_next = CANDLE_INTERVAL_MINUTES - remainder

    # Subtract elapsed seconds within the current minute
    secs_to_next = mins_to_next * 60 - seconds

    if secs_to_next <= 0:
        secs_to_next += CANDLE_INTERVAL_MINUTES * 60

    return max(0, secs_to_next)


def next_candle_time(dt: datetime) -> datetime:
    """
    Return the datetime of the next candle close.

    Useful for logging: "next signal check at HH:MM".
    """
    secs = seconds_until_next_candle(dt)
    return dt + timedelta(seconds=secs)


def candle_times_for_day(day: date) -> list:
    """
    Return all candle close times for a given trading day (as IST datetimes).

    First candle: 9:30 AM (skip 9:15 open if SKIP_FIRST_CANDLE)
    Last candle:  3:30 PM
    """
    times = []
    start_hour, start_min = 9, 15
    if SKIP_FIRST_CANDLE:
        start_min += CANDLE_INTERVAL_MINUTES   # 9:30 AM

    current = IST.localize(datetime(day.year, day.month, day.day, start_hour, start_min))
    end     = IST.localize(datetime(day.year, day.month, day.day, *[int(x) for x in str(MARKET_CLOSE).split(':')[:2]]))

    while current <= end:
        times.append(current)
        current += timedelta(minutes=CANDLE_INTERVAL_MINUTES)

    return times
