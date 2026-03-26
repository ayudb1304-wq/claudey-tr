"""
prefilter.py — Signal Pre-filter Engine

Scores every stock 0–5 before deciding whether to call Claude.
Only stocks with score >= MIN_FILTER_SCORE get sent to Claude.

WHY THIS EXISTS:
  Without pre-filtering, the bot could make up to 1,250 Claude API calls per day
  (50 stocks × 25 candles). At ~₹0.25/call that's ₹312/day — wasteful.
  Pre-filtering keeps it to 5–15 calls/day by only escalating setups
  where multiple independent indicators agree.

SCORING LOGIC:
  Each stock is scored independently for LONG and SHORT direction.
  Score range: 0 (no signal) to 5 (all indicators aligned).

  LONG score += 1 for each of:
    1. RSI oversold (< 35) OR recovering from oversold (crossed back above 30)
    2. MACD fresh bullish crossover this candle
    3. Price above EMA20 AND EMA20 above EMA50 (short-term uptrend)
    4. Volume >= 1.5× the 20-period average (confirms move)
    5. Price within 0.75% above a pivot support level

  SHORT score += 1 for each of:
    1. RSI overbought (> 65) OR cooling from overbought (crossed back below 70)
    2. MACD fresh bearish crossover this candle
    3. Price below EMA20 AND EMA20 below EMA50 (short-term downtrend)
    4. Volume >= 1.5× the 20-period average
    5. Price within 0.75% below a pivot resistance level

  The direction with the higher score is the candidate direction.
  If both are tied, LONG takes precedence (Indian markets are long-biased intraday).

DESIGN DECISIONS:
  - EMA 200 is NOT a scoring criterion — it's too slow for 15-min intraday
    signals. It's passed to Claude as context only.
  - RSI thresholds are 35/65 (not the textbook 30/70) because at 30/70
    the move has usually already happened. 35/65 gives earlier signals.
  - Volume threshold 1.5× is intentionally conservative — low-volume
    moves often reverse quickly on NSE intraday.
"""

from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger

from config import MIN_FILTER_SCORE, VOLUME_RATIO_THRESHOLD, RSI_OVERSOLD, RSI_OVERBOUGHT, PIVOT_PROXIMITY_PCT
from indicators import calculate_indicators, InsufficientDataError
from pivot_points import enrich_pivots
from candle_store import CandleStore


# ─────────────────────────────────────────────────────────────
#  SCORING
# ─────────────────────────────────────────────────────────────

def score_stock(indicators: dict, pivots: dict, direction: str) -> int:
    """
    Score a single stock in one direction (long or short).

    Args:
        indicators: Dict from calculate_indicators()
        pivots:     Dict from enrich_pivots() — includes nearest S/R levels
        direction:  "long" or "short"

    Returns:
        int 0–5 (higher = more indicators aligned = stronger setup)
    """
    score = 0
    price = indicators['price']

    if direction == "long":

        # ── 1. RSI ────────────────────────────────────────────
        # Oversold (potential bounce) OR just recovered from oversold (confirmed bounce)
        if indicators['rsi'] < RSI_OVERSOLD:
            score += 1
        elif indicators['rsi_prev'] < 30 and indicators['rsi'] >= 30:
            # RSI crossed back above 30 — historically a stronger long signal than
            # simply being oversold, because it confirms the selling pressure has eased.
            score += 1

        # ── 2. MACD ───────────────────────────────────────────
        # Fresh bullish crossover only (fires on the exact candle of the cross)
        if indicators['macd_bullish_cross']:
            score += 1

        # ── 3. EMA trend alignment ────────────────────────────
        # Price above EMA20 AND EMA20 above EMA50 = short-term bullish structure
        if price > indicators['ema20'] > indicators['ema50']:
            score += 1

        # ── 4. Volume confirmation ────────────────────────────
        # High volume on the signal candle confirms institutional participation
        if indicators['volume_ratio'] >= VOLUME_RATIO_THRESHOLD:
            score += 1

        # ── 5. Pivot support proximity ────────────────────────
        # Price bouncing near a known support level adds structural confirmation
        if (pivots.get('nearest_support') is not None
                and pivots.get('support_dist_pct') is not None
                and pivots['support_dist_pct'] <= PIVOT_PROXIMITY_PCT):
            score += 1

    elif direction == "short":

        # ── 1. RSI ────────────────────────────────────────────
        if indicators['rsi'] > RSI_OVERBOUGHT:
            score += 1
        elif indicators['rsi_prev'] > 70 and indicators['rsi'] <= 70:
            # RSI crossed back below 70 — confirmed cooldown from overbought
            score += 1

        # ── 2. MACD ───────────────────────────────────────────
        if indicators['macd_bearish_cross']:
            score += 1

        # ── 3. EMA trend alignment ────────────────────────────
        # Price below EMA20 AND EMA20 below EMA50 = short-term bearish structure
        if price < indicators['ema20'] < indicators['ema50']:
            score += 1

        # ── 4. Volume confirmation ────────────────────────────
        if indicators['volume_ratio'] >= VOLUME_RATIO_THRESHOLD:
            score += 1

        # ── 5. Pivot resistance proximity ─────────────────────
        if (pivots.get('nearest_resistance') is not None
                and pivots.get('resistance_dist_pct') is not None
                and pivots['resistance_dist_pct'] <= PIVOT_PROXIMITY_PCT):
            score += 1

    return score


# ─────────────────────────────────────────────────────────────
#  CANDLE-INTERVAL DEDUPLICATION TRACKER
# ─────────────────────────────────────────────────────────────

class PreFilterTracker:
    """
    Prevents the same stock from being sent to Claude twice in a single
    15-minute candle interval.

    HOW IT WORKS:
      - Call reset() at the start of every candle interval (every 15 min).
      - Call mark_sent(symbol) after sending a stock to Claude.
      - Call was_sent(symbol) before scoring to skip already-escalated stocks.

    WHY THIS MATTERS:
      Without this, if a stock scores ≥ 2 on candle N and Claude returns HOLD,
      the same stock could score ≥ 2 again on the very next iteration of the
      scan loop within the same candle interval (if the loop runs multiple times).
      This wastes Claude API calls and can produce duplicate positions.
    """

    def __init__(self):
        self._sent_this_interval: set[str] = set()
        self._interval_start: datetime | None = None

    def reset(self, interval_timestamp: datetime | None = None) -> None:
        """
        Clear the sent-set for the new candle interval.
        Call this once at the beginning of every 15-minute loop cycle.
        """
        self._sent_this_interval.clear()
        self._interval_start = interval_timestamp
        logger.debug("PreFilterTracker reset for new candle interval.")

    def mark_sent(self, symbol: str) -> None:
        """Record that `symbol` has been sent to Claude this interval."""
        self._sent_this_interval.add(symbol)

    def was_sent(self, symbol: str) -> bool:
        """Returns True if this symbol was already sent to Claude this interval."""
        return symbol in self._sent_this_interval

    def sent_count(self) -> int:
        """How many stocks were sent to Claude this interval."""
        return len(self._sent_this_interval)


# ─────────────────────────────────────────────────────────────
#  MAIN SCAN FUNCTION
# ─────────────────────────────────────────────────────────────

def scan_for_candidates(
    symbols:               list[str],
    candle_store:          CandleStore,
    pivots_map:            dict,
    open_position_symbols: set[str],
    tracker:               PreFilterTracker,
) -> list[dict]:
    """
    Scan all watchlist stocks and return those that pass the pre-filter.

    Called once per 15-minute candle close by the main loop.

    Args:
        symbols:               List of tradeable NSE symbols (price-filtered)
        candle_store:          CandleStore with current candle history
        pivots_map:            {symbol: pivot_dict} — computed once per morning
        open_position_symbols: Set of symbols already in an open position
        tracker:               PreFilterTracker for this candle interval

    Returns:
        List of candidate dicts, sorted by score descending:
        [
            {
                "symbol":      str,
                "direction":   "long" | "short",
                "score":       int (2–5),
                "long_score":  int,
                "short_score": int,
                "indicators":  dict,   ← full indicator dict, passed to Claude
                "pivots":      dict,   ← enriched pivot dict, passed to Claude
            },
            ...
        ]
        Empty list if no candidates pass the filter.
    """
    candidates = []

    for symbol in symbols:

        # ── Guard 1: skip if already has open position ────────
        if symbol in open_position_symbols:
            logger.debug(f"  {symbol}: skipped — position already open")
            continue

        # ── Guard 2: skip if already sent to Claude this interval
        if tracker.was_sent(symbol):
            logger.debug(f"  {symbol}: skipped — already escalated this candle")
            continue

        # ── Guard 3: skip if not enough candle history ────────
        if not candle_store.is_ready(symbol):
            logger.debug(
                f"  {symbol}: skipped — only {candle_store.get_candle_count(symbol)} "
                f"candles (need {200})"
            )
            continue

        # ── Guard 4: skip if no pivot data ────────────────────
        if symbol not in pivots_map or not pivots_map[symbol]:
            logger.debug(f"  {symbol}: skipped — no pivot point data")
            continue

        # ── Calculate indicators ──────────────────────────────
        try:
            df         = candle_store.get(symbol)
            indicators = calculate_indicators(df)
        except InsufficientDataError as e:
            logger.debug(f"  {symbol}: skipped — {e}")
            continue
        except Exception as e:
            logger.warning(f"  {symbol}: indicator error — {e}")
            continue

        # ── Enrich pivots with nearest S/R ────────────────────
        enriched_pivots = enrich_pivots(indicators['price'], pivots_map[symbol])

        # ── Score both directions ─────────────────────────────
        long_score  = score_stock(indicators, enriched_pivots, "long")
        short_score = score_stock(indicators, enriched_pivots, "short")
        best_score  = max(long_score, short_score)

        # ── Apply threshold ───────────────────────────────────
        if best_score < MIN_FILTER_SCORE:
            logger.debug(
                f"  {symbol}: score {best_score} < {MIN_FILTER_SCORE} threshold — skip"
            )
            continue

        # When tied, prefer long (Indian intraday markets are long-biased)
        direction = "long" if long_score >= short_score else "short"

        candidates.append({
            "symbol":      symbol,
            "direction":   direction,
            "score":       best_score,
            "long_score":  long_score,
            "short_score": short_score,
            "indicators":  indicators,
            "pivots":      enriched_pivots,
        })

        logger.debug(
            f"  {symbol}: CANDIDATE | {direction.upper()} score={best_score} "
            f"(long={long_score} short={short_score})"
        )

    # Sort highest-conviction first
    candidates.sort(key=lambda x: x['score'], reverse=True)

    return candidates
