"""
pivot_points.py — Classic Pivot Point Calculator

Pivot points are DAILY support and resistance levels calculated from the
PREVIOUS trading day's High, Low, and Close. They reset every morning.

WHY CLASSIC PIVOT POINTS:
  - Used by the majority of Indian intraday traders (standard on Kite, Angel One charts)
  - Deterministic: given the same input, everyone gets the same output
  - No parameters to tune — pure formula
  - Proven to act as intraday S/R on NSE/BSE stocks

FORMULAS (Classic / Floor Pivot Points):
  PP = (High + Low + Close) / 3          ← The pivot (central level)
  R1 = (2 × PP) - Low                    ← Resistance 1
  R2 = PP + (High - Low)                 ← Resistance 2
  R3 = High + 2 × (PP - Low)             ← Resistance 3 (strong)
  S1 = (2 × PP) - High                   ← Support 1
  S2 = PP - (High - Low)                 ← Support 2
  S3 = Low - 2 × (High - PP)             ← Support 3 (strong)

USAGE IN THE BOT:
  1. At 9:00 AM each morning, fetch previous day's OHLC via DataFeed.
  2. Call calculate_pivot_points() once per stock.
  3. Store the result — levels are FIXED for the entire trading day.
  4. On each 15-min candle, call get_nearest_levels() to find the
     support/resistance closest to the current price.
  5. Feed these levels into the pre-filter scorer and Claude's prompt.

WHEN DO LEVELS RESET?
  After 3:30 PM each day. At next morning's startup (9:00 AM), fetch the
  previous day's OHLC and recompute. Never recompute mid-session.
"""


def calculate_pivot_points(prev_high: float, prev_low: float,
                            prev_close: float) -> dict:
    """
    Calculate Classic Pivot Point levels from previous day's OHLC.

    Args:
        prev_high:  Previous trading day's high price
        prev_low:   Previous trading day's low price
        prev_close: Previous trading day's close price

    Returns:
        Dict with 7 levels: PP, R1, R2, R3, S1, S2, S3

    Example:
        Previous day: High=1300, Low=1250, Close=1280
        PP  = (1300 + 1250 + 1280) / 3 = 1276.67
        R1  = (2 × 1276.67) - 1250     = 1303.33
        S1  = (2 × 1276.67) - 1300     = 1253.33
    """
    # Input validation
    if prev_high < prev_low:
        raise ValueError(
            f"prev_high ({prev_high}) must be >= prev_low ({prev_low}). "
            f"Check the OHLC data — this indicates corrupt data."
        )
    if not (prev_low <= prev_close <= prev_high):
        # Close can occasionally be exactly at high or low — that's valid.
        # But if close is outside [low, high], the data is wrong.
        raise ValueError(
            f"prev_close ({prev_close}) must be between "
            f"prev_low ({prev_low}) and prev_high ({prev_high})."
        )

    pp = (prev_high + prev_low + prev_close) / 3
    r1 = (2 * pp) - prev_low
    r2 = pp + (prev_high - prev_low)
    r3 = prev_high + 2 * (pp - prev_low)
    s1 = (2 * pp) - prev_high
    s2 = pp - (prev_high - prev_low)
    s3 = prev_low - 2 * (prev_high - pp)

    return {
        "PP": round(pp, 2),
        "R1": round(r1, 2),
        "R2": round(r2, 2),
        "R3": round(r3, 2),
        "S1": round(s1, 2),
        "S2": round(s2, 2),
        "S3": round(s3, 2),
    }


def get_nearest_levels(price: float, pivots: dict) -> dict:
    """
    Find the nearest support level below and resistance level above current price.

    Used by the pre-filter to score whether price is near a key level,
    and by Claude's prompt to provide context about where price is relative
    to known intraday support/resistance.

    Args:
        price:   Current market price
        pivots:  Dict from calculate_pivot_points()

    Returns:
        {
            "nearest_support":        float | None  — closest pivot BELOW price
            "nearest_resistance":     float | None  — closest pivot ABOVE price
            "support_dist_pct":       float | None  — % distance to nearest support
            "resistance_dist_pct":    float | None  — % distance to nearest resistance
        }
        Returns None for a level if price is below all supports or above all resistances.

    Example:
        price = 1280, PP = 1276.67, R1 = 1303.33, S1 = 1253.33
        nearest_support    = 1276.67 (PP is below price)
        support_dist_pct   = (1280 - 1276.67) / 1280 * 100 = 0.26%
        nearest_resistance = 1303.33 (R1 is above price)
        resistance_dist_pct = (1303.33 - 1280) / 1280 * 100 = 1.82%
    """
    all_levels = sorted(pivots.values())

    levels_below = [l for l in all_levels if l < price]
    levels_above = [l for l in all_levels if l > price]

    nearest_support    = max(levels_below) if levels_below else None
    nearest_resistance = min(levels_above) if levels_above else None

    support_dist_pct = (
        round((price - nearest_support) / price * 100, 2)
        if nearest_support is not None else None
    )
    resistance_dist_pct = (
        round((nearest_resistance - price) / price * 100, 2)
        if nearest_resistance is not None else None
    )

    return {
        "nearest_support":        round(nearest_support, 2)    if nearest_support    is not None else None,
        "nearest_resistance":     round(nearest_resistance, 2) if nearest_resistance is not None else None,
        "support_dist_pct":       support_dist_pct,
        "resistance_dist_pct":    resistance_dist_pct,
    }


def enrich_pivots(price: float, pivots: dict) -> dict:
    """
    Combine pivot levels + nearest level lookup into a single dict.

    Convenience function for building Claude's prompt — returns everything
    in one place rather than having to merge two separate dicts.

    Returns:
        The pivots dict (PP, R1, R2, R3, S1, S2, S3) plus nearest support/resistance.
    """
    nearest = get_nearest_levels(price, pivots)
    return {**pivots, **nearest}
