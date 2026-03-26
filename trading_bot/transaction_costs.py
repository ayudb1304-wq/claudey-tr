"""
transaction_costs.py — NSE India Transaction Cost Calculator

Calculates all real regulatory and exchange charges for a trade so that
P&L tracking is accurate.  Zero-commission broker model (like Zerodha/Angel One
intraday equity) — brokerage is ₹0.

CHARGE BREAKDOWN (intraday equity, NSE):
  STT (Securities Transaction Tax):
    - Sell side only: 0.025% of turnover
    - Buy side:       ZERO for intraday (STT is waived on buy leg of intraday)

  NSE Exchange Transaction Charge:
    - Both sides: 0.00297% of turnover

  SEBI Turnover Charge:
    - Both sides: 0.0001% of turnover (₹10 per crore)

  Stamp Duty:
    - Buy side only: 0.015% of turnover
    - Sell side:     ZERO

  GST (Goods & Services Tax):
    - 18% on (exchange fee + SEBI charge) — brokerage is ₹0 so excluded
    - Applied on both buy and sell legs independently

IMPORTANT NOTES:
  - All rates are as of 2024-2026 NSE regulations — cross-check annually
  - DP charges (₹15.93 for delivery only) are ZERO for intraday
  - Brokerage: ₹0 assumed (Angel One free intraday equity)
  - These charges are small individually but compound over many trades.
    On a ₹10,000 capital base they add up to ~0.05-0.08% round-trip.

USAGE:
    from transaction_costs import calculate_charges

    charges = calculate_charges(entry_price=1290.0, exit_price=1310.0,
                                 quantity=7, direction="BUY")
    net_pnl = charges['gross_pnl'] - charges['total_charges']
"""

# ─────────────────────────────────────────────────────────────
#  CHARGE RATES
# ─────────────────────────────────────────────────────────────

# STT — Securities Transaction Tax
STT_SELL_RATE       = 0.00025    # 0.025% on sell turnover only (intraday equity)

# NSE Exchange Transaction Charge
NSE_EXCHANGE_RATE   = 0.0000297  # 0.00297% on both legs

# SEBI Turnover Charge
SEBI_RATE           = 0.000001   # 0.0001% on both legs

# Stamp Duty (Maharashtra-based; varies by state but ₹0 on sell intraday)
STAMP_DUTY_BUY_RATE = 0.00015    # 0.015% on buy turnover only

# GST on exchange fees + SEBI (NOT on brokerage since it's ₹0)
GST_RATE            = 0.18       # 18%


# ─────────────────────────────────────────────────────────────
#  MAIN FUNCTION
# ─────────────────────────────────────────────────────────────

def calculate_charges(
    entry_price: float,
    exit_price:  float,
    quantity:    int,
    direction:   str,    # "BUY" or "SELL" (the direction of the opening trade)
) -> dict:
    """
    Calculate all NSE intraday transaction charges for a completed round-trip trade.

    Args:
        entry_price:  Price at which the position was opened (after slippage)
        exit_price:   Price at which the position was closed (after slippage)
        quantity:     Number of shares traded
        direction:    "BUY" (went long) or "SELL" (went short)

    Returns:
        {
            "gross_pnl":      float,   raw P&L before charges (positive = profit)
            "buy_turnover":   float,   total value of the buy leg
            "sell_turnover":  float,   total value of the sell leg
            "stt":            float,   STT charge
            "exchange_fee":   float,   NSE exchange fee (both legs)
            "sebi_charge":    float,   SEBI turnover charge (both legs)
            "stamp_duty":     float,   stamp duty (buy leg only)
            "gst":            float,   GST on exchange fee + SEBI
            "total_charges":  float,   sum of all charges
            "net_pnl":        float,   gross_pnl - total_charges
        }

    Raises:
        ValueError: if direction is not "BUY" or "SELL", or prices/qty <= 0
    """
    if direction not in ("BUY", "SELL"):
        raise ValueError(f"direction must be 'BUY' or 'SELL', got: {direction!r}")
    if entry_price <= 0 or exit_price <= 0:
        raise ValueError("Prices must be positive")
    if quantity <= 0:
        raise ValueError("Quantity must be positive")

    # ── Turnover values ────────────────────────────────────────
    # For a BUY position: entry is the buy leg, exit is the sell leg.
    # For a SELL position: entry is the sell leg, exit is the buy leg.
    if direction == "BUY":
        buy_turnover  = entry_price * quantity
        sell_turnover = exit_price  * quantity
        gross_pnl     = sell_turnover - buy_turnover
    else:  # SELL (short)
        sell_turnover = entry_price * quantity
        buy_turnover  = exit_price  * quantity
        gross_pnl     = sell_turnover - buy_turnover

    # ── STT: sell side only ────────────────────────────────────
    stt = sell_turnover * STT_SELL_RATE

    # ── Exchange fee: both sides ───────────────────────────────
    exchange_fee = (buy_turnover + sell_turnover) * NSE_EXCHANGE_RATE

    # ── SEBI charge: both sides ────────────────────────────────
    sebi_charge = (buy_turnover + sell_turnover) * SEBI_RATE

    # ── Stamp duty: buy side only ──────────────────────────────
    stamp_duty = buy_turnover * STAMP_DUTY_BUY_RATE

    # ── GST: on exchange fee + SEBI (brokerage = ₹0) ──────────
    gst = (exchange_fee + sebi_charge) * GST_RATE

    # ── Total ──────────────────────────────────────────────────
    total_charges = stt + exchange_fee + sebi_charge + stamp_duty + gst

    return {
        "gross_pnl":     round(gross_pnl,     2),
        "buy_turnover":  round(buy_turnover,  2),
        "sell_turnover": round(sell_turnover, 2),
        "stt":           round(stt,           4),
        "exchange_fee":  round(exchange_fee,  4),
        "sebi_charge":   round(sebi_charge,   4),
        "stamp_duty":    round(stamp_duty,    4),
        "gst":           round(gst,           4),
        "total_charges": round(total_charges, 4),
        "net_pnl":       round(gross_pnl - total_charges, 2),
    }


# ─────────────────────────────────────────────────────────────
#  CONVENIENCE HELPERS
# ─────────────────────────────────────────────────────────────

def charges_summary(charges: dict) -> str:
    """Return a compact one-line string for logging."""
    return (
        f"gross=Rs{charges['gross_pnl']:.2f} "
        f"charges=Rs{charges['total_charges']:.2f} "
        f"net=Rs{charges['net_pnl']:.2f} "
        f"[STT={charges['stt']:.2f} "
        f"exch={charges['exchange_fee']:.2f} "
        f"stamp={charges['stamp_duty']:.2f} "
        f"gst={charges['gst']:.2f}]"
    )
