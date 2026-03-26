"""
mock_feed.py — Synthetic Market Data Feed (No Internet Required)

Generates realistic NSE stock candle data using geometric Brownian motion
(the same mathematical model used by professional quant systems for testing).

WHY THIS EXISTS:
  Yahoo Finance is unreliable for Indian stocks and blocks automated requests.
  Angel One requires API keys we don't have yet.
  Rather than fight external services, we generate our own data that:
    - Uses real Nifty 50 approximate price levels
    - Produces realistic volatility (0.3% per 15-min candle — typical for large caps)
    - Generates proper OHLCV relationships (high ≥ open,close ≥ low always holds)
    - Simulates realistic intraday volume patterns (high at open, dip midday, spike at close)
    - Works 100% offline, instantly, no rate limits

  This is the standard approach in professional algo trading development.
  The risk manager, indicators, Claude agent, paper trader — all behave
  identically whether data comes from here or from Angel One.

WHEN TO MOVE AWAY FROM THIS:
  When Angel One API keys arrive, switch DATA_SOURCE = "angelone" in config.py.
  This file can remain for backtesting and strategy research.
"""

import time
import threading
import numpy as np
import pandas as pd
import pytz
from datetime import datetime, timedelta, date
from loguru import logger

from data_feed import DataFeed, DataFeedError
from config import IST

# ─────────────────────────────────────────────────────────────
#  APPROXIMATE PRICE LEVELS FOR NIFTY 50 STOCKS
#
#  These are approximate prices as of early 2026 (INR per share).
#  Used as the starting point for the random walk.
#  The bot's price filter (≤₹2,000) uses these to decide which
#  stocks are tradeable — so these need to be roughly realistic.
# ─────────────────────────────────────────────────────────────
SEED_PRICES = {
    # Prices are approximate 2026-27 projections (INR per share).
    # Stocks above Rs2,000 are filtered out by MAX_STOCK_PRICE in config.py.
    "ADANIENT":    2820,   # conglomerate recovery, infra push
    "ADANIPORTS":  1580,   # port volumes growing
    "APOLLOHOSP":  7250,   # healthcare premium, pan-India expansion
    "ASIANPAINT":  2090,   # margin pressure from competition
    "AXISBANK":    1355,   # credit growth, retail push
    "BAJAJ-AUTO":  10200,  # EV transition, export momentum
    "BAJFINANCE":  8150,   # NBFC tightening, valuation reset
    "BAJAJFINSV":  1885,   # insurance + lending synergy
    "BPCL":         262,   # OMC margins under pressure
    "BHARTIARTL":  1975,   # ARPU expansion, 5G monetisation
    "BRITANNIA":   5180,   # FMCG pricing power
    "CIPLA":       1725,   # US generics + chronic therapies
    "COALINDIA":    392,   # energy transition headwinds
    "DIVISLAB":    5380,   # API exports recovery
    "DRREDDY":     1415,   # biosimilars pipeline
    "EICHERMOT":   5520,   # Royal Enfield global sales
    "GRASIM":      2910,   # paints business scaling
    "HCLTECH":     1830,   # IT services demand stabilising
    "HDFCBANK":    1940,   # merged entity NIM expansion
    "HDFCLIFE":     685,   # insurance penetration growth
    "HEROMOTOCO":  4580,   # rural demand + EV scooter launch
    "HINDALCO":     795,   # aluminium cycle upturn
    "HINDUNILVR":  2470,   # premium FMCG mix shift
    "ICICIBANK":   1475,   # ROA expansion, retail dominance
    "INDUSINDBK":   975,   # microfinance stress, cautious
    "INFY":        1945,   # deal wins, GenAI services
    "ITC":          515,   # cigarette cash + FMCG scale
    "JSWSTEEL":    1125,   # capacity addition, export growth
    "KOTAKBANK":   2290,   # succession resolved, re-rating
    "LT":          4210,   # mega order book, Middle East
    "LTIM":        5820,   # LTIMindtree synergies
    "M&M":         3360,   # SUV market leader, EV traction
    "MARUTI":      14600,  # new launches, CNG dominance
    "NESTLEIND":   2360,   # premiumisation steady
    "NTPC":         415,   # renewable capacity addition
    "ONGC":         298,   # oil price sensitive
    "POWERGRID":    348,   # regulated returns, stable
    "RELIANCE":    1485,   # retail + Jio + new energy
    "SBILIFE":     1645,   # VNB growth, bancassurance
    "SBIN":         875,   # NPA normalised, ROE improving
    "SHRIRAMFIN":  3590,   # CV financing cycle up
    "SUNPHARMA":   1955,   # specialty pharma US + India
    "TATACONSUM":  1155,   # Starbucks + Tata Salt synergy
    "TATAMOTORS":   825,   # JLR recovery, Nexon EV
    "TATASTEEL":    182,   # Europe drag vs India growth
    "TCS":         4420,   # large deal momentum
    "TECHM":       1765,   # telecom vertical recovery
    "TITAN":       3720,   # jewellery SSSG, Caratlane
    "ULTRACEMCO":  11900,  # capacity + pricing power
    "WIPRO":        332,   # restructuring benefits, margin stable
}

# Per-candle volatility (standard deviation of returns).
# 0.3% per 15-min candle ≈ 1.5% daily vol — typical for Nifty 50 large caps.
CANDLE_VOLATILITY = 0.003

# How many 15-min candles in a trading day (9:15 AM → 3:30 PM = 375 min / 15 = 25)
CANDLES_PER_DAY = 25


class MockDataFeed(DataFeed):
    """
    Synthetic data feed using geometric Brownian motion.
    Generates realistic OHLCV candles for all Nifty 50 stocks.
    No internet, no API keys, no rate limits.
    """

    def __init__(self, seed: int = 42):
        """
        Args:
            seed: Random seed for reproducibility.
                  Use the same seed to get identical data across runs —
                  useful when debugging a specific scenario.
                  Change the seed to get a different market scenario.
        """
        np.random.seed(seed)
        self._live_thread  = None
        self._live_running = False
        self._last_prices  = {}

        # Pre-generate and cache historical data at construction time
        # so repeated calls to get_historical_candles() return the same data.
        self._cache: dict[str, pd.DataFrame] = {}

        logger.info(
            f"MockDataFeed initialised (seed={seed}, "
            f"offline synthetic data — no API keys required)"
        )

    # ─────────────────────────────────────────────────────────
    #  HISTORICAL CANDLES
    # ─────────────────────────────────────────────────────────

    def get_historical_candles(self, symbol: str, days: int = 10) -> pd.DataFrame:
        """
        Generate N trading days of synthetic 15-min OHLCV candles.

        The first call for a symbol generates and caches the data.
        Subsequent calls return the same cached data (consistent within a session).
        """
        cache_key = f"{symbol}_{days}"
        if cache_key in self._cache:
            return self._cache[cache_key].copy()

        if symbol not in SEED_PRICES:
            raise DataFeedError(
                f"No seed price defined for '{symbol}'. "
                f"Add it to SEED_PRICES in mock_feed.py."
            )

        start_price = SEED_PRICES[symbol]
        df = self._generate_history(symbol, start_price, days)

        self._cache[cache_key] = df
        self._last_prices[symbol] = float(df['close'].iloc[-1])

        logger.debug(
            f"{symbol}: {len(df)} synthetic candles generated "
            f"(start ₹{start_price} → last ₹{self._last_prices[symbol]:.2f})"
        )
        return df.copy()

    def get_previous_day_ohlc(self, symbol: str) -> dict:
        """
        Return the synthetic 'previous day' OHLC for pivot point calculation.
        Uses the second-to-last trading day from the cached history.
        """
        # Fetch history (uses cache if already generated)
        df = self.get_historical_candles(symbol, days=10)

        # Get all unique trading dates
        unique_dates = df.index.normalize().unique()
        if len(unique_dates) < 2:
            raise DataFeedError(f"Not enough history to get previous day OHLC for {symbol}")

        # Second-to-last date = "yesterday"
        prev_date = unique_dates[-2]
        prev_day  = df[df.index.normalize() == prev_date]

        return {
            "open":  round(float(prev_day['open'].iloc[0]),   2),
            "high":  round(float(prev_day['high'].max()),     2),
            "low":   round(float(prev_day['low'].min()),      2),
            "close": round(float(prev_day['close'].iloc[-1]), 2),
            "date":  str(prev_date.date()),
        }

    # ─────────────────────────────────────────────────────────
    #  LIVE FEED (Replay + New Synthetic Candles)
    # ─────────────────────────────────────────────────────────

    def start_live_feed(self, symbols: list[str], on_candle_close) -> None:
        """
        Simulate live trading by generating new synthetic candles in real time.

        Fires one candle per symbol every 2 seconds (instead of every 15 minutes).
        This lets you test the full bot loop in ~2 minutes.

        The candles continue from where the historical data left off,
        so indicators stay valid and the bot behaves exactly as it would live.
        """
        if self._live_running:
            logger.warning("Live feed already running.")
            return

        # Prime the cache for all symbols
        live_state = {}
        for symbol in symbols:
            try:
                df = self.get_historical_candles(symbol, days=10)
                last_price = float(df['close'].iloc[-1])
                last_ts    = df.index[-1]
                live_state[symbol] = {
                    'last_price': last_price,
                    'last_ts':    last_ts,
                }
            except DataFeedError as e:
                logger.warning(f"Skipping {symbol} from live feed: {e}")

        if not live_state:
            raise DataFeedError("No symbols available for live feed.")

        logger.info(
            f"Starting synthetic live feed for {len(live_state)} symbols. "
            f"New candle fires every 2s per symbol."
        )

        self._live_running = True
        self._live_thread  = threading.Thread(
            target=self._live_loop,
            args=(live_state, on_candle_close),
            daemon=True,
        )
        self._live_thread.start()

    def _live_loop(self, live_state: dict, on_candle_close) -> None:
        """
        Background thread: generates and fires new synthetic candles continuously.
        Stops when stop_live_feed() is called.
        """
        candle_num = 0
        while self._live_running:
            candle_num += 1
            for symbol, state in live_state.items():
                if not self._live_running:
                    break

                # Generate the next candle continuing from last price
                candle_data = _generate_single_candle(
                    state['last_price'],
                    CANDLE_VOLATILITY,
                    candle_num,  # Used to simulate intraday volume pattern
                )

                # Advance timestamp by 15 minutes
                next_ts = state['last_ts'] + timedelta(minutes=15)
                # Wrap around to next day if past 3:30 PM
                if next_ts.time() > pd.Timestamp('15:30', tz=IST).time():
                    next_ts = next_ts.replace(
                        hour=9, minute=15, second=0, microsecond=0
                    ) + timedelta(days=1)
                    # Skip weekends
                    while next_ts.weekday() >= 5:
                        next_ts += timedelta(days=1)

                state['last_price'] = candle_data['close']
                state['last_ts']    = next_ts

                candle = {
                    "timestamp": next_ts.to_pydatetime(),
                    **candle_data,
                }

                self._last_prices[symbol] = candle_data['close']

                try:
                    on_candle_close(symbol, candle)
                except Exception as e:
                    logger.error(f"Callback error for {symbol}: {e}")

            time.sleep(2)

    def stop_live_feed(self) -> None:
        self._live_running = False
        if self._live_thread and self._live_thread.is_alive():
            self._live_thread.join(timeout=5)
        logger.info("Live feed stopped.")

    def get_last_price(self, symbol: str) -> float:
        if symbol in self._last_prices:
            return self._last_prices[symbol]
        # If not cached yet, generate history to get a price
        df = self.get_historical_candles(symbol, days=1)
        return float(df['close'].iloc[-1])

    # ─────────────────────────────────────────────────────────
    #  DATA GENERATION INTERNALS
    # ─────────────────────────────────────────────────────────

    def _generate_history(self, symbol: str, start_price: float,
                           days: int) -> pd.DataFrame:
        """
        Generate `days` trading days of 15-min synthetic OHLCV data.

        Returns DataFrame with IST DatetimeIndex and
        columns [open, high, low, close, volume], sorted oldest-first.
        """
        candles    = []
        timestamps = []
        price      = start_price

        # Generate trading days going backwards from today,
        # then reverse so data is oldest-first
        today = datetime.now(IST).date()
        trading_days = _get_past_trading_days(today, days)
        trading_days.reverse()  # oldest first

        for day_num, trading_day in enumerate(trading_days):
            # 25 candles per day: 9:15, 9:30, ..., 15:15
            for candle_idx in range(CANDLES_PER_DAY):
                minutes_offset = candle_idx * 15
                ts = IST.localize(datetime(
                    trading_day.year, trading_day.month, trading_day.day,
                    9, 15
                )) + timedelta(minutes=minutes_offset)

                candle_data = _generate_single_candle(
                    price, CANDLE_VOLATILITY, candle_idx
                )
                price = candle_data['close']

                candles.append(candle_data)
                timestamps.append(ts)

        df = pd.DataFrame(candles, index=pd.DatetimeIndex(timestamps, tz=IST))
        return df.sort_index()


# ─────────────────────────────────────────────────────────────
#  MODULE-LEVEL HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────

def _generate_single_candle(prev_close: float, volatility: float,
                              candle_idx: int) -> dict:
    """
    Generate one OHLCV candle using geometric Brownian motion.

    Geometric Brownian Motion: price = prev * exp(return)
    This ensures prices are always positive and returns are normally distributed —
    the same model used by Black-Scholes and most financial simulations.

    Args:
        prev_close: Previous candle's closing price
        volatility: Per-candle standard deviation (0.003 = 0.3%)
        candle_idx: Position in day (0=open, 24=last) — used for volume pattern
    """
    # ── Price generation ──────────────────────────────────
    # Drift is 0 for intraday (no directional bias within a day)
    log_return  = np.random.normal(0, volatility)
    close       = round(prev_close * np.exp(log_return), 2)

    # Open has a tiny gap from prev close (realistic microstructure)
    open_gap    = np.random.normal(0, volatility * 0.2)
    open_       = round(prev_close * np.exp(open_gap), 2)

    # High is the max of open/close plus a random positive excursion
    excursion   = abs(np.random.normal(0, volatility * 0.6))
    high        = round(max(open_, close) * (1 + excursion), 2)

    # Low is the min of open/close minus a random positive excursion
    low         = round(min(open_, close) * (1 - excursion), 2)

    # ── Volume generation ─────────────────────────────────
    # Intraday volume pattern: U-shaped (high at open and close, low midday)
    # candle_idx 0-4 = opening surge, 10-14 = lunch lull, 20-24 = closing surge
    if candle_idx <= 3 or candle_idx >= 21:
        vol_multiplier = np.random.uniform(2.0, 4.0)   # Opening/closing surge
    elif 10 <= candle_idx <= 14:
        vol_multiplier = np.random.uniform(0.4, 0.8)   # Lunch lull
    else:
        vol_multiplier = np.random.uniform(0.8, 1.5)   # Normal trading

    base_volume = int(np.random.lognormal(13.5, 0.8))  # ~700k base, log-normal
    volume      = int(base_volume * vol_multiplier)

    return {
        "open":   open_,
        "high":   high,
        "low":    low,
        "close":  close,
        "volume": volume,
    }


def _get_past_trading_days(from_date: date, count: int) -> list[date]:
    """
    Return the last `count` trading days (Mon-Fri, excluding weekends).
    Does not check NSE holidays for simplicity — close enough for testing.
    """
    days   = []
    cursor = from_date

    # If today itself might be a trading day, exclude it
    # (we want completed days only)
    cursor -= timedelta(days=1)

    while len(days) < count:
        if cursor.weekday() < 5:   # 0=Mon, 4=Fri, 5=Sat, 6=Sun
            days.append(cursor)
        cursor -= timedelta(days=1)

    return days
