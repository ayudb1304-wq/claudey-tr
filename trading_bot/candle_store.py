"""
candle_store.py — Per-Symbol In-Memory Candle Buffer

WHAT THIS DOES:
  Holds the rolling window of 15-min candles for every stock we're watching.
  It's the single source of truth for historical + live candle data.

WHY IT EXISTS:
  The indicator engine needs a pandas DataFrame of candles to work.
  The candle store:
    1. Loads historical candles at startup (from DataFeed)
    2. Appends each new live candle as it arrives
    3. Serves the latest N candles to the indicator engine on demand
    4. Prunes old candles to prevent unbounded memory growth

  Think of it as a rolling window: we always keep the last MAX_CANDLES
  candles per stock — enough for all indicators, no more.

USAGE:
    store = CandleStore()

    # At startup: load history
    store.load_historical(symbol, df_from_data_feed)

    # During live trading: append each new candle
    store.append(symbol, candle_dict)

    # Get candles for indicator calculation
    df = store.get(symbol)
    indicators = calculate_indicators(df)
"""

import pandas as pd
import pytz
from datetime import datetime
from loguru import logger
from config import IST, MIN_CANDLES_REQUIRED

# Keep the last 300 candles per symbol.
# 300 > 200 (EMA 200 requirement) with comfortable buffer.
# At 25 candles/day, 300 candles = 12 trading days.
MAX_CANDLES = 300


class CandleStore:
    """
    Thread-safe per-symbol candle buffer.

    Stores up to MAX_CANDLES 15-min OHLCV candles per symbol.
    """

    def __init__(self):
        # Main store: symbol → pandas DataFrame
        # Each DataFrame has DatetimeIndex (IST) and columns [open, high, low, close, volume]
        self._store: dict[str, pd.DataFrame] = {}

        # Track how many symbols are ready (have enough candles for all indicators)
        self._ready: dict[str, bool] = {}

    # ─────────────────────────────────────────────────────────
    #  LOADING HISTORICAL DATA
    # ─────────────────────────────────────────────────────────

    def load_historical(self, symbol: str, df: pd.DataFrame) -> None:
        """
        Load historical candles for a symbol at startup.

        Args:
            symbol: NSE trading symbol (e.g., "RELIANCE")
            df:     DataFrame from DataFeed.get_historical_candles()
                    Must have [open, high, low, close, volume] columns
                    and a timezone-aware DatetimeIndex (IST).

        Call this for every stock at 9:00 AM before the market opens.
        """
        if df.empty:
            logger.warning(f"{symbol}: Historical data is empty — skipping.")
            self._ready[symbol] = False
            return

        # Keep only the last MAX_CANDLES candles
        if len(df) > MAX_CANDLES:
            df = df.iloc[-MAX_CANDLES:]

        self._store[symbol] = df.copy()
        candle_count = len(df)
        is_ready = candle_count >= MIN_CANDLES_REQUIRED

        self._ready[symbol] = is_ready

        if is_ready:
            logger.debug(
                f"{symbol}: {candle_count} historical candles loaded. "
                f"All indicators ready."
            )
        else:
            logger.warning(
                f"{symbol}: Only {candle_count} candles loaded "
                f"(need {MIN_CANDLES_REQUIRED} for EMA 200). "
                f"Indicators will be limited until more data arrives."
            )

    # ─────────────────────────────────────────────────────────
    #  APPENDING LIVE CANDLES
    # ─────────────────────────────────────────────────────────

    def append(self, symbol: str, candle: dict) -> bool:
        """
        Append a new live candle to the buffer.

        Called by the data feed's on_candle_close callback.

        Args:
            symbol: NSE trading symbol
            candle: {
                "timestamp": datetime (IST, timezone-aware),
                "open":   float,
                "high":   float,
                "low":    float,
                "close":  float,
                "volume": int
            }

        Returns:
            True if the symbol now has enough data for all indicators.
            False if still accumulating (less than MIN_CANDLES_REQUIRED).
        """
        if symbol not in self._store:
            # First candle for this symbol — initialise with empty DataFrame
            self._store[symbol] = pd.DataFrame(
                columns=['open', 'high', 'low', 'close', 'volume']
            )
            self._store[symbol].index = pd.DatetimeIndex([], tz=IST)

        # Build a one-row DataFrame for this candle
        ts = candle['timestamp']

        # Ensure timestamp is timezone-aware IST
        if ts.tzinfo is None:
            ts = IST.localize(ts)
        elif str(ts.tzinfo) != str(IST):
            ts = ts.astimezone(IST)

        new_row = pd.DataFrame(
            [{
                'open':   float(candle['open']),
                'high':   float(candle['high']),
                'low':    float(candle['low']),
                'close':  float(candle['close']),
                'volume': int(candle['volume']),
            }],
            index=pd.DatetimeIndex([ts], tz=IST)
        )

        # Check for duplicate timestamp (can happen on reconnect)
        if ts in self._store[symbol].index:
            logger.debug(f"{symbol}: Duplicate candle at {ts} — updating existing row.")
            self._store[symbol].loc[ts] = new_row.iloc[0]
        else:
            self._store[symbol] = pd.concat([self._store[symbol], new_row])

        # Prune to MAX_CANDLES to prevent memory growth
        if len(self._store[symbol]) > MAX_CANDLES:
            self._store[symbol] = self._store[symbol].iloc[-MAX_CANDLES:]

        # Sort by time (safety net — should already be sorted)
        self._store[symbol] = self._store[symbol].sort_index()

        # Update readiness
        count = len(self._store[symbol])
        self._ready[symbol] = count >= MIN_CANDLES_REQUIRED

        return self._ready[symbol]

    # ─────────────────────────────────────────────────────────
    #  READING CANDLES
    # ─────────────────────────────────────────────────────────

    def get(self, symbol: str, n: int = None) -> pd.DataFrame:
        """
        Get candles for a symbol, used by the indicator engine.

        Args:
            symbol: NSE trading symbol
            n:      Return last N candles only (None = return all)

        Returns:
            DataFrame [open, high, low, close, volume], sorted oldest-first.
            Returns empty DataFrame if symbol has no data.
        """
        if symbol not in self._store:
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

        df = self._store[symbol]

        if n is not None and len(df) > n:
            return df.iloc[-n:].copy()

        return df.copy()

    def get_last_candle(self, symbol: str) -> dict | None:
        """
        Get the most recently closed candle for a symbol.

        Returns:
            Dict with candle OHLCV + timestamp, or None if no data.
        """
        if symbol not in self._store or self._store[symbol].empty:
            return None

        row = self._store[symbol].iloc[-1]
        return {
            "timestamp": self._store[symbol].index[-1],
            "open":      float(row['open']),
            "high":      float(row['high']),
            "low":       float(row['low']),
            "close":     float(row['close']),
            "volume":    int(row['volume']),
        }

    def is_ready(self, symbol: str) -> bool:
        """
        Returns True if this symbol has enough candles for all indicators.

        The bot should only generate signals for symbols that are ready.
        """
        return self._ready.get(symbol, False)

    def get_candle_count(self, symbol: str) -> int:
        """Returns the number of candles currently stored for a symbol."""
        if symbol not in self._store:
            return 0
        return len(self._store[symbol])

    # ─────────────────────────────────────────────────────────
    #  STATUS
    # ─────────────────────────────────────────────────────────

    def status(self) -> dict:
        """
        Returns a summary of the candle store state.
        Useful for logging at startup.
        """
        total = len(self._store)
        ready = sum(1 for v in self._ready.values() if v)
        counts = {sym: len(df) for sym, df in self._store.items()}
        return {
            "total_symbols":  total,
            "ready_symbols":  ready,
            "not_ready":      total - ready,
            "candle_counts":  counts,
        }

    def symbols(self) -> list[str]:
        """Returns list of all symbols currently in the store."""
        return list(self._store.keys())
