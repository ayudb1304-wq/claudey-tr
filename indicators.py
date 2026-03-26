"""
indicators.py — Technical Indicator Engine

Calculates all required indicators for a single stock on every candle close.
Returns a flat dict of values for the latest candle only — everything the
pre-filter and Claude agent need to make a decision.

LIBRARY: We use the `ta` library (pip install ta).
  - Actively maintained, works on Python 3.14 + pandas 2.2+ + numpy 2.x
  - Do NOT use pandas_ta — it is abandoned and incompatible with modern pandas
  - Do NOT use TA-Lib — requires a C compiler binary, fails on Windows easily

INDICATORS CALCULATED:
  1. RSI(14)             — momentum oscillator, range 0–100
  2. EMA 20              — short-term trend
  3. EMA 50              — medium-term trend
  4. EMA 200             — long-term structural trend (context only, not a signal)
  5. MACD(12, 26, 9)     — momentum + trend change detection
  6. Volume SMA(20)      — baseline for volume confirmation

EMA METHOD:
  Uses `adjust=False` in pandas ewm — this is Wilder's exponential smoothing,
  which matches TradingView's EMA exactly. Never use `adjust=True` (Excel-style).

RSI METHOD:
  Uses `com = window - 1` in pandas ewm which equals alpha = 1/window.
  This IS Wilder's RMA (Running Moving Average), matching TradingView's RSI.

MACD CROSSOVER:
  Detected by comparing iloc[-2] (previous candle) vs iloc[-1] (current).
  A crossover fires on the EXACT candle it happens — not on any subsequent candle.
  This is critical: without this check, the bot would re-signal every candle
  after a cross happened.
"""

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD

from config import (
    RSI_PERIOD,
    EMA_SHORT, EMA_MEDIUM, EMA_LONG,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    VOLUME_SMA,
    MIN_CANDLES_REQUIRED,
)


class InsufficientDataError(Exception):
    """
    Raised when there aren't enough candles to compute all indicators.

    This is expected at startup before 200 historical candles are loaded.
    The main loop should catch this and skip the stock — never crash on it.
    """
    pass


def calculate_indicators(df: pd.DataFrame) -> dict:
    """
    Calculate all technical indicators for a stock using its candle history.

    Args:
        df: DataFrame with columns [open, high, low, close, volume]
            Index: DatetimeIndex (IST, timezone-aware)
            Must be sorted oldest-first (earliest row = index 0)
            Minimum 200 rows required (for EMA 200)

    Returns:
        Dict with indicator values for the LATEST candle only:
        {
            "price":               float  — latest close price
            "rsi":                 float  — RSI(14), 0–100
            "rsi_prev":            float  — RSI(14) of previous candle
            "ema20":               float  — EMA(20)
            "ema50":               float  — EMA(50)
            "ema200":              float  — EMA(200)
            "macd_line":           float  — MACD line (EMA12 - EMA26)
            "signal_line":         float  — MACD signal (EMA9 of MACD line)
            "macd_bullish_cross":  bool   — True only on the candle the cross happens
            "macd_bearish_cross":  bool   — True only on the candle the cross happens
            "volume":              int    — current candle volume
            "volume_sma20":        int    — 20-period volume SMA
            "volume_ratio":        float  — volume / volume_sma20
        }

    Raises:
        InsufficientDataError: If df has fewer than MIN_CANDLES_REQUIRED rows
                               or if any critical indicator produces NaN.
    """
    n = len(df)
    if n < MIN_CANDLES_REQUIRED:
        raise InsufficientDataError(
            f"Need {MIN_CANDLES_REQUIRED} candles, have {n}. "
            f"Waiting for more historical data to load."
        )

    close  = df['close']
    volume = df['volume'].astype(float)

    # ── RSI(14) ───────────────────────────────────────────────
    # RSIIndicator uses Wilder's RMA internally (com=window-1, adjust=False)
    # This matches TradingView's RSI exactly.
    rsi_series  = RSIIndicator(close=close, window=RSI_PERIOD).rsi()
    rsi_current = float(rsi_series.iloc[-1])
    rsi_prev    = float(rsi_series.iloc[-2])

    # ── EMAs ──────────────────────────────────────────────────
    # EMAIndicator uses ewm(span=window, adjust=False) — standard EMA.
    ema20  = float(EMAIndicator(close=close, window=EMA_SHORT).ema_indicator().iloc[-1])
    ema50  = float(EMAIndicator(close=close, window=EMA_MEDIUM).ema_indicator().iloc[-1])
    ema200 = float(EMAIndicator(close=close, window=EMA_LONG).ema_indicator().iloc[-1])

    # ── MACD(12, 26, 9) ───────────────────────────────────────
    macd_obj    = MACD(
        close=close,
        window_fast=MACD_FAST,
        window_slow=MACD_SLOW,
        window_sign=MACD_SIGNAL,
    )
    macd_series   = macd_obj.macd()
    signal_series = macd_obj.macd_signal()

    macd_curr   = float(macd_series.iloc[-1])
    macd_prev_v = float(macd_series.iloc[-2])
    sig_curr    = float(signal_series.iloc[-1])
    sig_prev    = float(signal_series.iloc[-2])

    # Crossover: did MACD cross signal BETWEEN the previous and current candle?
    # Bullish: MACD was below signal, now above.  Bearish: opposite.
    # Using strict inequality on both sides ensures a true cross (not just touching).
    macd_bullish_cross = (macd_prev_v < sig_prev) and (macd_curr > sig_curr)
    macd_bearish_cross = (macd_prev_v > sig_prev) and (macd_curr < sig_curr)

    # ── Volume SMA(20) ────────────────────────────────────────
    # Using raw pandas rolling — simpler and faster than going through ta library
    # for a plain SMA on volume.
    vol_sma_series = volume.rolling(window=VOLUME_SMA, min_periods=VOLUME_SMA).mean()
    vol_sma_val    = float(vol_sma_series.iloc[-1])
    vol_current    = int(volume.iloc[-1])
    vol_ratio      = round(vol_current / vol_sma_val, 2) if vol_sma_val > 0 else 1.0

    # ── NaN validation ────────────────────────────────────────
    # NaN can appear if there are gaps in the candle history or on the very
    # first candles before enough data exists for an indicator.
    # We treat NaN as a hard error — the bot must not trade on broken data.
    critical = {
        "rsi":        rsi_current,
        "rsi_prev":   rsi_prev,
        "ema20":      ema20,
        "ema50":      ema50,
        "ema200":     ema200,
        "macd_line":  macd_curr,
        "signal":     sig_curr,
        "vol_sma":    vol_sma_val,
    }
    nan_fields = [k for k, v in critical.items() if np.isnan(v)]
    if nan_fields:
        raise InsufficientDataError(
            f"NaN in indicator(s): {nan_fields}. "
            f"Candle history may have gaps. Need more clean data."
        )

    return {
        "price":              round(float(close.iloc[-1]), 2),
        "rsi":                round(rsi_current, 2),
        "rsi_prev":           round(rsi_prev, 2),
        "ema20":              round(ema20, 2),
        "ema50":              round(ema50, 2),
        "ema200":             round(ema200, 2),
        "macd_line":          round(macd_curr, 4),
        "signal_line":        round(sig_curr, 4),
        "macd_bullish_cross": macd_bullish_cross,
        "macd_bearish_cross": macd_bearish_cross,
        "volume":             vol_current,
        "volume_sma20":       int(vol_sma_val),
        "volume_ratio":       vol_ratio,
    }
