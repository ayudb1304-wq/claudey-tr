"""
data_feed.py — Abstract Data Feed Interface

This file defines the "contract" that every data source must follow.
Both YFinanceDataFeed (development) and AngelOneDataFeed (production)
implement this same interface.

WHY AN ABSTRACTION?
  The rest of the bot (indicators, pre-filter, main loop) never talks
  to Angel One or yfinance directly. They only talk to a DataFeed object.
  This means:
    - During development: use YFinanceDataFeed (free, no keys needed)
    - When Angel One keys arrive: swap to AngelOneDataFeed (one line change)
    - Everything else stays the same

HOW TO SWITCH:
  In config.py, change DATA_SOURCE = "yfinance" → DATA_SOURCE = "angelone"
  The main.py will instantiate the right class based on that setting.
"""

from abc import ABC, abstractmethod
import pandas as pd


class DataFeed(ABC):
    """
    Abstract base class for all market data sources.

    All data sources must provide:
      1. Historical OHLCV candles    (for seeding indicators at startup)
      2. Previous day's daily OHLC   (for computing pivot points)
      3. A live candle stream         (for real-time signal generation)

    Candle DataFrame format (returned by all methods):
        Index:   DatetimeIndex (timezone-aware, IST)
        Columns: open, high, low, close, volume  (all float64 except volume int64)
        Sorted:  ascending by time (oldest first)
    """

    @abstractmethod
    def get_historical_candles(self, symbol: str, days: int = 10) -> pd.DataFrame:
        """
        Fetch past N trading days of 15-minute OHLCV candles for a symbol.

        Used at startup to seed EMA 200 and other indicators.
        10 days = ~250 candles, enough for all indicators.

        Args:
            symbol: NSE trading symbol, e.g. "RELIANCE"
            days:   Number of trading days to fetch (default 10)

        Returns:
            DataFrame with columns [open, high, low, close, volume]
            Index: DatetimeIndex (IST, timezone-aware)
            Pre-market (before 9:15 AM) and post-market rows excluded.

        Raises:
            DataFeedError: If the symbol is invalid or data unavailable
        """
        pass

    @abstractmethod
    def get_previous_day_ohlc(self, symbol: str) -> dict:
        """
        Fetch the previous trading day's Open, High, Low, Close for a symbol.

        Used every morning to compute Classic Pivot Points.
        "Previous trading day" skips weekends and holidays automatically.

        Args:
            symbol: NSE trading symbol, e.g. "RELIANCE"

        Returns:
            {
                "open":  float,
                "high":  float,
                "low":   float,
                "close": float,
                "date":  str  (YYYY-MM-DD of that trading day)
            }
        """
        pass

    @abstractmethod
    def start_live_feed(self, symbols: list[str], on_candle_close) -> None:
        """
        Start receiving live 15-minute candles.

        Each time a 15-minute candle closes, on_candle_close is called with:
            on_candle_close(symbol: str, candle: dict)
            where candle = {
                "timestamp": datetime (IST),
                "open":   float,
                "high":   float,
                "low":    float,
                "close":  float,
                "volume": int
            }

        This method is non-blocking — it starts the feed in the background.
        Call stop_live_feed() to shut it down.

        Args:
            symbols:        List of NSE symbols to watch
            on_candle_close: Callback function called on each candle close
        """
        pass

    @abstractmethod
    def stop_live_feed(self) -> None:
        """Stop the live data feed and clean up connections."""
        pass

    @abstractmethod
    def get_last_price(self, symbol: str) -> float:
        """
        Get the most recent traded price for a symbol.

        Used by the paper trader to simulate order fills.

        Args:
            symbol: NSE trading symbol

        Returns:
            Last traded price as float
        """
        pass


class DataFeedError(Exception):
    """Raised when a data feed operation fails."""
    pass
