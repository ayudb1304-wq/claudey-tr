"""
yfinance_feed.py — Development Data Feed using Yahoo Finance

Used INSTEAD of Angel One during development (no API keys required).
Yahoo Finance provides free NSE data using the ".NS" suffix.

LIMITATIONS vs Angel One (important to know):
  - 15-min data only available for the last 60 days (Angel One: up to 1 year)
  - Slightly delayed (~15 min delay for free data)
  - Occasionally missing candles during low-volume periods
  - Does not support real WebSocket — we simulate live feed by replaying candles
  - Volume data is less accurate than exchange feed

These limitations do NOT affect development or strategy testing.
The bot logic, indicators, Claude agent, risk manager and paper trader
all work identically. Only the data source differs.

NSE SYMBOL FORMAT:
  yfinance requires ".NS" suffix: "RELIANCE" → "RELIANCE.NS"
  Special cases:
    "M&M"       → "M&M.NS"
    "BAJAJ-AUTO"→ "BAJAJ-AUTO.NS"
  These are handled automatically by _to_yf_symbol().

WHY WE USE yf.download() INSTEAD OF ticker.history():
  Yahoo Finance's API requires browser-like cookies/crumb tokens to serve data.
  ticker.history() sometimes fails to negotiate these, returning an empty response
  (error: "Expecting value: line 1 column 1"). yf.download() uses a different
  internal path that is more reliable. We also pass a requests.Session with a
  standard User-Agent header to avoid Yahoo Finance blocking automated requests.
"""

import time
import threading
import requests
import pandas as pd
import yfinance as yf
import pytz
from datetime import datetime, timedelta
from loguru import logger

from data_feed import DataFeed, DataFeedError
from config import IST, CANDLE_INTERVAL_MINUTES

# Browser-like User-Agent so Yahoo Finance doesn't block the request.
# Without this, Yahoo Finance sometimes returns an empty body which causes
# the "Expecting value: line 1 column 1 (char 0)" JSON parse error.
_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}


class YFinanceDataFeed(DataFeed):
    """
    DataFeed implementation using Yahoo Finance.
    Drop-in replacement for AngelOneDataFeed during development.
    """

    def __init__(self):
        self._live_thread   = None
        self._live_running  = False
        self._last_prices   = {}

        # Shared requests session with browser headers.
        # Passed to yfinance so all HTTP calls include the User-Agent.
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

        logger.info("YFinanceDataFeed initialised (development mode — no API keys required)")

    # ─────────────────────────────────────────────────────────
    #  SYMBOL CONVERSION
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _to_yf_symbol(symbol: str) -> str:
        """
        Convert NSE trading symbol to Yahoo Finance format.
            "RELIANCE"  → "RELIANCE.NS"
            "M&M"       → "M&M.NS"
            "BAJAJ-AUTO"→ "BAJAJ-AUTO.NS"
        """
        return f"{symbol}.NS"

    # ─────────────────────────────────────────────────────────
    #  HISTORICAL CANDLES
    # ─────────────────────────────────────────────────────────

    def get_historical_candles(self, symbol: str, days: int = 10) -> pd.DataFrame:
        """
        Fetch N trading days of 15-minute OHLCV candles from Yahoo Finance.

        Uses yf.download() which is more reliable than ticker.history() for
        avoiding Yahoo Finance's cookie/crumb authentication issues.

        Args:
            symbol: NSE symbol like "RELIANCE"
            days:   Number of trading days to fetch (default 10 = ~250 candles)

        Returns:
            DataFrame [open, high, low, close, volume], IST DatetimeIndex
        """
        yf_symbol = self._to_yf_symbol(symbol)

        # Request extra days to account for weekends and holidays in the range
        end_date   = datetime.now(IST)
        start_date = end_date - timedelta(days=days + 7)

        logger.debug(f"Fetching {days}d 15-min history for {symbol}...")

        df = self._download_with_retry(
            yf_symbol,
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            interval='15m',
        )

        if df is None or df.empty:
            raise DataFeedError(
                f"No data returned for {symbol} ({yf_symbol}).\n"
                f"  This usually means Yahoo Finance is temporarily blocking requests.\n"
                f"  Wait 30 seconds and try again, or check your internet connection."
            )

        df = self._clean_candles(df, symbol)

        if df.empty:
            raise DataFeedError(
                f"Data for {symbol} was fetched but had no valid NSE-hours candles after filtering.\n"
                f"  This can happen if today is a market holiday or if all candles had zero volume."
            )

        # Keep only the last `days` trading days
        unique_dates = df.index.normalize().unique()
        if len(unique_dates) > days:
            cutoff = unique_dates[-days]
            df = df[df.index.normalize() >= cutoff]

        logger.debug(
            f"{symbol}: {len(df)} candles loaded "
            f"({df.index[0].date()} → {df.index[-1].date()})"
        )
        return df

    def get_previous_day_ohlc(self, symbol: str) -> dict:
        """
        Fetch the most recently completed trading day's OHLC.
        Used every morning to compute Classic Pivot Points.
        """
        yf_symbol = self._to_yf_symbol(symbol)

        df = self._download_with_retry(yf_symbol, period='5d', interval='1d')

        if df is None or df.empty:
            raise DataFeedError(f"No daily data for {symbol}")

        # Convert index to IST
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC').tz_convert(IST)
        else:
            df.index = df.index.tz_convert(IST)

        df.columns = df.columns.str.lower()

        # Use the last completed day (exclude today if market is open)
        today          = datetime.now(IST).date()
        completed_days = df[df.index.date < today]

        if completed_days.empty:
            completed_days = df   # Fallback: use whatever is available

        last_row = completed_days.iloc[-1]

        return {
            "open":  round(float(last_row['open']),  2),
            "high":  round(float(last_row['high']),  2),
            "low":   round(float(last_row['low']),   2),
            "close": round(float(last_row['close']), 2),
            "date":  str(completed_days.index[-1].date()),
        }

    # ─────────────────────────────────────────────────────────
    #  LIVE FEED (Simulated — replays historical candles)
    # ─────────────────────────────────────────────────────────

    def start_live_feed(self, symbols: list[str], on_candle_close) -> None:
        """
        Simulate a live feed by replaying the most recent trading day's candles.

        Each candle fires every 2 seconds (vs 15 minutes in real trading).
        This lets you test the full bot loop in ~2 minutes.
        """
        if self._live_running:
            logger.warning("Live feed already running. Call stop_live_feed() first.")
            return

        logger.info(
            f"Starting simulated live feed for {len(symbols)} symbols. "
            f"Replaying last trading day candles at 2s per candle."
        )

        replay_data = {}
        for symbol in symbols:
            try:
                df        = self.get_historical_candles(symbol, days=2)
                last_date = df.index[-1].date()
                day_df    = df[df.index.date == last_date]
                if not day_df.empty:
                    replay_data[symbol] = day_df
                    logger.debug(f"  {symbol}: {len(day_df)} candles queued for replay")
            except DataFeedError as e:
                logger.warning(f"  Skipping {symbol} from live feed: {e}")

        if not replay_data:
            raise DataFeedError("No replay data available for any symbol.")

        self._live_running = True
        self._live_thread  = threading.Thread(
            target=self._replay_loop,
            args=(replay_data, on_candle_close),
            daemon=True,
        )
        self._live_thread.start()

    def _replay_loop(self, replay_data: dict, on_candle_close) -> None:
        candle_counts = [len(df) for df in replay_data.values()]
        num_candles   = min(candle_counts) if candle_counts else 0
        logger.info(f"Replaying {num_candles} candles per symbol...")

        for candle_idx in range(num_candles):
            if not self._live_running:
                break

            for symbol, df in replay_data.items():
                if candle_idx >= len(df):
                    continue

                row    = df.iloc[candle_idx]
                candle = {
                    "timestamp": df.index[candle_idx].to_pydatetime(),
                    "open":      round(float(row['open']),  2),
                    "high":      round(float(row['high']),  2),
                    "low":       round(float(row['low']),   2),
                    "close":     round(float(row['close']), 2),
                    "volume":    int(row['volume']),
                }

                self._last_prices[symbol] = candle['close']

                try:
                    on_candle_close(symbol, candle)
                except Exception as e:
                    logger.error(f"Callback error for {symbol}: {e}")

            time.sleep(2)

        logger.info("Candle replay complete.")
        self._live_running = False

    def stop_live_feed(self) -> None:
        self._live_running = False
        if self._live_thread and self._live_thread.is_alive():
            self._live_thread.join(timeout=5)
        logger.info("Live feed stopped.")

    def get_last_price(self, symbol: str) -> float:
        if symbol in self._last_prices:
            return self._last_prices[symbol]

        # Fetch via download (1 day daily) as fallback
        yf_symbol = self._to_yf_symbol(symbol)
        df = self._download_with_retry(yf_symbol, period='2d', interval='1d')
        if df is not None and not df.empty:
            price = float(df['Close'].iloc[-1])
            self._last_prices[symbol] = price
            return price

        raise DataFeedError(f"Could not get last price for {symbol}")

    # ─────────────────────────────────────────────────────────
    #  INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────

    def _download_with_retry(self, yf_symbol: str, max_retries: int = 3,
                              **kwargs) -> pd.DataFrame | None:
        """
        Call yf.download() with retry logic and browser session headers.

        We use yf.download() instead of ticker.history() because it is more
        reliable against Yahoo Finance's cookie/crumb authentication. The
        shared session with User-Agent headers further reduces blocking.

        Returns None if all retries fail (caller decides how to handle).
        """
        for attempt in range(1, max_retries + 1):
            try:
                df = yf.download(
                    tickers=yf_symbol,
                    session=self._session,
                    auto_adjust=True,
                    prepost=False,
                    progress=False,     # Suppress download progress bar
                    **kwargs,
                )

                # Newer yfinance versions return MultiIndex columns:
                # (Price, Ticker) e.g. ('Close', 'RELIANCE.NS')
                # Flatten to single-level column names.
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                if not df.empty:
                    return df

                logger.warning(
                    f"Empty response for {yf_symbol} "
                    f"(attempt {attempt}/{max_retries}) — retrying in 3s..."
                )

            except Exception as e:
                logger.warning(
                    f"Download error for {yf_symbol} "
                    f"(attempt {attempt}/{max_retries}): {e}"
                )

            if attempt < max_retries:
                time.sleep(3)   # Wait before retrying — Yahoo Finance rate limits

        logger.error(f"All {max_retries} download attempts failed for {yf_symbol}")
        return None

    @staticmethod
    def _clean_candles(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Standardise a yfinance DataFrame into our canonical OHLCV format.

        - Lowercases column names
        - Converts index to IST timezone
        - Filters to NSE hours only (9:15 AM – 3:30 PM IST)
        - Drops zero-volume and NaN rows
        - Sorts ascending by timestamp
        """
        df = df.copy()
        df.columns = df.columns.str.lower()

        needed  = ['open', 'high', 'low', 'close', 'volume']
        missing = [c for c in needed if c not in df.columns]
        if missing:
            raise DataFeedError(
                f"{symbol}: Missing columns in yfinance response: {missing}. "
                f"Got: {list(df.columns)}"
            )
        df = df[needed]

        # Convert index to IST
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC').tz_convert(IST)
        else:
            df.index = df.index.tz_convert(IST)

        # Keep only NSE market hours
        market_open  = pd.Timestamp('09:15', tz=IST).time()
        market_close = pd.Timestamp('15:30', tz=IST).time()
        df = df[
            (df.index.time >= market_open) &
            (df.index.time <= market_close)
        ]

        # Drop unusable rows
        df = df[df['volume'] > 0]
        df = df.dropna(subset=['open', 'high', 'low', 'close'])

        # Correct types
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].astype(float).round(2)
        df['volume'] = df['volume'].astype(int)

        return df.sort_index()
