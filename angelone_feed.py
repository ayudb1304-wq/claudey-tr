"""
angelone_feed.py — Angel One SmartAPI Data Feed (Live NSE Data)

Implements the DataFeed interface using Angel One's SmartAPI:
  - get_historical_candles(): Uses getCandleData() with FIFTEEN_MINUTE interval
  - get_previous_day_ohlc():  Uses getCandleData() with ONE_DAY interval
  - get_last_price():         Uses ltpData() for current LTP
  - start_live_feed():        No-op — main.py uses polling, not WebSocket push
  - stop_live_feed():         No-op

SYMBOL FORMAT:
  Angel One requires "<NAME>-EQ" format (e.g., "RELIANCE-EQ") and a numeric
  token (e.g., "2885"). Both are loaded from scrip_master.json at startup
  via instruments.load_nifty50_tokens().

RATE LIMITS:
  Angel One allows ~3 requests/second. A 400ms sleep is inserted after
  each API call to stay safely within this limit.

USAGE:
  import auth
  auth.login()
  from angelone_feed import AngelOneDataFeed
  feed = AngelOneDataFeed()
  df = feed.get_historical_candles("RELIANCE", days=10)
"""

import time
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger

from data_feed import DataFeed, DataFeedError
from config import IST, CANDLE_INTERVAL
import auth
from instruments import load_nifty50_tokens


class AngelOneDataFeed(DataFeed):
    """
    Live NSE market data via Angel One SmartAPI.
    Requires a valid session (auth.login()) before creating this object.
    """

    _REQUEST_DELAY = 0.4   # seconds between API calls (rate limit: ~3 req/sec)

    def __init__(self):
        """
        Load instrument tokens at startup.
        auth.login() must have been called before instantiation.
        """
        logger.info("[FEED] Initialising AngelOneDataFeed...")
        self._token_map = load_nifty50_tokens()
        logger.success(
            f"[FEED] Ready — {len(self._token_map)} Nifty 50 tokens loaded."
        )

    # ─────────────────────────────────────────────────────────────
    #  INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────────

    def _get_token(self, symbol: str) -> str:
        """Return numeric token string for a symbol. Raises DataFeedError if missing."""
        info = self._token_map.get(symbol)
        if info is None:
            raise DataFeedError(
                f"No token for '{symbol}'. Is it in NIFTY_50_SYMBOLS "
                f"and in the ScripMaster file?"
            )
        return info['token']

    def _angel_symbol(self, symbol: str) -> str:
        """Angel One expects 'RELIANCE-EQ' format, not plain 'RELIANCE'."""
        return f"{symbol}-EQ"

    def _candle_df(self, raw_data: list) -> pd.DataFrame:
        """
        Convert Angel One candle list to a standard OHLCV DataFrame.

        raw_data format (each entry):
            ["2024-01-15T09:15:00+05:30", open, high, low, close, volume]

        Returns:
            DataFrame with columns [open, high, low, close, volume],
            indexed by IST-aware DatetimeIndex, sorted ascending.
        """
        if not raw_data:
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

        rows = []
        for entry in raw_data:
            ts_str, open_, high, low, close, volume = entry
            ts = pd.Timestamp(ts_str).tz_convert(IST)
            rows.append({
                'timestamp': ts,
                'open':   float(open_),
                'high':   float(high),
                'low':    float(low),
                'close':  float(close),
                'volume': int(volume),
            })

        df = pd.DataFrame(rows).set_index('timestamp').sort_index()
        return df

    def _from_datetime(self, days_back: int) -> datetime:
        """
        Return an IST datetime approximately days_back trading days ago.

        Uses a 1.5x calendar-day buffer to account for weekends and holidays.
        e.g. 10 trading days -> look back ~20 calendar days.
        """
        calendar_days = int(days_back * 1.5) + 5
        from_dt = datetime.now(IST) - timedelta(days=calendar_days)
        return from_dt.replace(hour=9, minute=15, second=0, microsecond=0)

    def _call_candle_api(self, symbol: str, token: str,
                         interval: str, from_dt: datetime, to_dt: datetime) -> list:
        """
        Call getCandleData() and return the raw data list.
        Raises DataFeedError on API error or network failure.
        """
        params = {
            "exchange":    "NSE",
            "symboltoken": token,
            "interval":    interval,
            "fromdate":    from_dt.strftime("%Y-%m-%d %H:%M"),
            "todate":      to_dt.strftime("%Y-%m-%d %H:%M"),
        }

        try:
            smart_api = auth.get_smart_api()
            response  = smart_api.getCandleData(params)
        except DataFeedError:
            raise
        except Exception as e:
            raise DataFeedError(f"getCandleData network error for {symbol}: {e}")

        if not response or not response.get('status'):
            msg = (response.get('message', 'unknown') if response else 'no response')
            raise DataFeedError(
                f"Angel One API error for {symbol} [{interval}]: {msg}"
            )

        data = response.get('data') or []
        time.sleep(self._REQUEST_DELAY)
        return data

    # ─────────────────────────────────────────────────────────────
    #  PUBLIC INTERFACE
    # ─────────────────────────────────────────────────────────────

    def get_historical_candles(self, symbol: str, days: int = 10) -> pd.DataFrame:
        """
        Fetch N trading days of 15-minute OHLCV candles.

        For days=10 this returns ~250 candles (25 per day), enough to seed
        EMA 200 and all other indicators at startup.

        For days=1 (called at each candle close in main.py) this returns
        today's candles so far — the last row is the just-closed candle.
        """
        token   = self._get_token(symbol)
        from_dt = self._from_datetime(days)
        to_dt   = datetime.now(IST)

        raw = self._call_candle_api(symbol, token, CANDLE_INTERVAL, from_dt, to_dt)
        df  = self._candle_df(raw)

        logger.debug(
            f"[FEED] {symbol}: {len(df)} x 15-min candles "
            f"({from_dt.strftime('%d-%b')} to {to_dt.strftime('%d-%b')})"
        )
        return df

    def get_previous_day_ohlc(self, symbol: str) -> dict:
        """
        Fetch the most recently completed trading day's daily OHLC.

        Looks back 5 calendar days so Monday runs correctly return Friday's data.
        Used at startup to compute Classic Pivot Points.
        """
        token   = self._get_token(symbol)
        to_dt   = datetime.now(IST).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        from_dt = to_dt - timedelta(days=5)

        raw = self._call_candle_api(symbol, token, "ONE_DAY", from_dt, to_dt)

        if not raw:
            raise DataFeedError(
                f"No daily candle data returned for {symbol}. "
                f"Token may be stale — run: python instruments.py"
            )

        # Last entry = most recently completed trading day
        ts_str, open_, high, low, close, volume = raw[-1]
        trade_date = pd.Timestamp(ts_str).tz_convert(IST).date()

        logger.debug(
            f"[FEED] {symbol} prev-day OHLC [{trade_date}]: "
            f"O={open_} H={high} L={low} C={close}"
        )

        return {
            "open":  float(open_),
            "high":  float(high),
            "low":   float(low),
            "close": float(close),
            "date":  str(trade_date),
        }

    def get_last_price(self, symbol: str) -> float:
        """
        Fetch the Last Traded Price (LTP) for a symbol via ltpData().
        Used by paper_trader to simulate order fills at current market price.
        """
        token        = self._get_token(symbol)
        angel_symbol = self._angel_symbol(symbol)

        try:
            smart_api = auth.get_smart_api()
            response  = smart_api.ltpData("NSE", angel_symbol, token)
        except DataFeedError:
            raise
        except Exception as e:
            raise DataFeedError(f"ltpData network error for {symbol}: {e}")

        if not response or not response.get('status'):
            msg = (response.get('message', 'unknown') if response else 'no response')
            raise DataFeedError(f"Angel One LTP error for {symbol}: {msg}")

        ltp = (response.get('data') or {}).get('ltp')
        if ltp is None:
            raise DataFeedError(
                f"No 'ltp' field in response for {symbol}: {response}"
            )

        time.sleep(self._REQUEST_DELAY)
        logger.debug(f"[FEED] {symbol} LTP: Rs{float(ltp):.2f}")
        return float(ltp)

    def start_live_feed(self, symbols: list, on_candle_close) -> None:
        """
        No-op. main.py uses a polling loop — it calls get_historical_candles(days=1)
        at each 15-minute candle-close boundary. No WebSocket is needed.
        """
        logger.debug("[FEED] start_live_feed: polling mode, no WebSocket started.")

    def stop_live_feed(self) -> None:
        """No-op — no background thread to clean up."""
        logger.debug("[FEED] stop_live_feed: nothing to stop.")
