"""
paper_trader.py — Paper Trading Engine

Simulates trade execution, position tracking, SL/target monitoring,
and EOD force-close entirely in Python — no real orders are placed.

SLIPPAGE MODEL:
  0.05% per leg (entry and exit), always in the direction against us:
  - BUY entry:   price × 1.0005  (we pay slightly above mid)
  - BUY exit:    price × 0.9995  (we receive slightly below mid)
  - SELL entry:  price × 0.9995  (we sell slightly below mid)
  - SELL exit:   price × 1.0005  (we buy-to-cover slightly above mid)

CASH MANAGEMENT:
  When a position is opened, cost_basis (shares × entry_price) is reserved
  from cash. On close, cost_basis is returned plus net_pnl (after charges).
  This keeps cash always non-negative for valid sized positions.

EXIT PRIORITY (per candle):
  1. SL hit  — checked against candle LOW (BUY) or HIGH (SELL)
  2. Target  — checked against candle HIGH (BUY) or LOW (SELL)
  3. EOD     — force close at candle CLOSE price at/after 3:15 PM IST
  SL takes priority over target on the same candle (conservative).

USAGE:
  trader = PaperTrader(starting_capital=10_000.0, risk_manager=rm)
  trader.open_position("RELIANCE", "BUY", shares=7, entry_price=1290.0,
                        stop_loss=1275.0, target=1315.0, now=datetime_obj)
  trade = trader.check_exits("RELIANCE", candle_high=1316.0,
                              candle_low=1291.0, candle_close=1314.0, now=now)
  summary = trader.get_summary()
"""

from datetime import datetime

import pytz
from loguru import logger

from config import IST, FORCE_EXIT_AT
from transaction_costs import calculate_charges, charges_summary
from risk_manager import RiskManager

SLIPPAGE_PCT = 0.0005    # 0.05% per leg


# ─────────────────────────────────────────────────────────────
#  SLIPPAGE HELPERS
# ─────────────────────────────────────────────────────────────

def _apply_entry_slippage(price: float, direction: str) -> float:
    """Apply slippage at position open (works against us)."""
    if direction == "BUY":
        return round(price * (1 + SLIPPAGE_PCT), 2)
    else:  # SELL (short) — we get a slightly lower sell price
        return round(price * (1 - SLIPPAGE_PCT), 2)


def _apply_exit_slippage(price: float, direction: str) -> float:
    """Apply slippage at position close (works against us)."""
    if direction == "BUY":   # selling to close — get slightly less
        return round(price * (1 - SLIPPAGE_PCT), 2)
    else:                    # buying-to-cover — pay slightly more
        return round(price * (1 + SLIPPAGE_PCT), 2)


# ─────────────────────────────────────────────────────────────
#  PAPER TRADER
# ─────────────────────────────────────────────────────────────

class PaperTrader:

    def __init__(self, starting_capital: float, risk_manager: RiskManager):
        if starting_capital <= 0:
            raise ValueError("starting_capital must be positive")

        self.cash:           float = starting_capital
        self.positions:      dict  = {}    # symbol → position dict
        self.closed_trades:  list  = []    # full history for logging/DB
        self._risk_manager          = risk_manager

    # ─────────────────────────────────────────────────────────
    #  OPEN POSITION
    # ─────────────────────────────────────────────────────────

    def open_position(
        self,
        symbol:      str,
        direction:   str,    # "BUY" or "SELL"
        shares:      int,
        entry_price: float,  # mid-price from Claude's decision
        stop_loss:   float,
        target:      float,
        now:         datetime,
    ) -> tuple[bool, str]:
        """
        Simulate opening a position.

        Args:
            symbol:      NSE symbol
            direction:   "BUY" or "SELL"
            shares:      From risk_manager.size_position()
            entry_price: Claude's entry_price (before slippage)
            stop_loss:   Claude's stop_loss
            target:      Claude's target
            now:         Current datetime (timezone-aware)

        Returns:
            (success: bool, reason: str)
        """
        if symbol in self.positions:
            return False, f"Position in {symbol} already open"

        if shares <= 0:
            return False, "Shares must be > 0"

        actual_entry = _apply_entry_slippage(entry_price, direction)
        cost_basis   = actual_entry * shares

        if cost_basis > self.cash:
            return False, (
                f"Insufficient cash: need Rs{cost_basis:.2f}, "
                f"have Rs{self.cash:.2f}"
            )

        self.cash -= cost_basis

        self.positions[symbol] = {
            "symbol":      symbol,
            "direction":   direction,
            "shares":      shares,
            "entry_price": actual_entry,   # after slippage — used for charge calc
            "stop_loss":   stop_loss,
            "target":      target,
            "cost_basis":  cost_basis,
            "entry_time":  now,
        }

        self._risk_manager.update_open_count(+1)

        logger.info(
            f"[PAPER] OPENED {direction} {symbol} × {shares} "
            f"@ Rs{actual_entry} (mid Rs{entry_price} + slippage) "
            f"| SL=Rs{stop_loss} target=Rs{target} "
            f"| cash left=Rs{self.cash:.2f}"
        )

        return True, ""

    # ─────────────────────────────────────────────────────────
    #  CLOSE POSITION
    # ─────────────────────────────────────────────────────────

    def close_position(
        self,
        symbol:      str,
        exit_price:  float,   # price level that triggered the exit
        exit_reason: str,     # "SL" | "TARGET" | "EOD" | "MANUAL"
        now:         datetime,
    ) -> dict | None:
        """
        Simulate closing a position.

        Returns a closed-trade dict (for logging), or None if symbol not open.
        """
        pos = self.positions.pop(symbol, None)
        if pos is None:
            logger.warning(f"[PAPER] close_position called for {symbol} but no open position")
            return None

        actual_exit = _apply_exit_slippage(exit_price, pos['direction'])

        # Calculate all NSE transaction charges
        charges = calculate_charges(
            entry_price = pos['entry_price'],
            exit_price  = actual_exit,
            quantity    = pos['shares'],
            direction   = pos['direction'],
        )

        # Return cost basis + net P&L to cash
        self.cash += pos['cost_basis'] + charges['net_pnl']
        self.cash  = round(self.cash, 2)

        # Update risk manager
        self._risk_manager.update_daily_pnl(charges['net_pnl'])
        self._risk_manager.update_open_count(-1)

        trade = {
            "symbol":      symbol,
            "direction":   pos['direction'],
            "shares":      pos['shares'],
            "entry_price": pos['entry_price'],
            "exit_price":  actual_exit,
            "stop_loss":   pos['stop_loss'],
            "target":      pos['target'],
            "entry_time":  pos['entry_time'],
            "exit_time":   now,
            "exit_reason": exit_reason,
            **charges,    # gross_pnl, net_pnl, total_charges, stt, etc.
        }

        self.closed_trades.append(trade)

        emoji = "+" if charges['net_pnl'] >= 0 else "-"
        logger.info(
            f"[PAPER] CLOSED {pos['direction']} {symbol} × {pos['shares']} "
            f"@ Rs{actual_exit} [{exit_reason}] "
            f"| {charges_summary(charges)} "
            f"| cash=Rs{self.cash:.2f}"
        )

        return trade

    # ─────────────────────────────────────────────────────────
    #  CHECK EXITS (called each candle close)
    # ─────────────────────────────────────────────────────────

    def check_exits(
        self,
        symbol:       str,
        candle_high:  float,
        candle_low:   float,
        candle_close: float,
        now:          datetime,
    ) -> dict | None:
        """
        Check whether a candle triggers SL, target, or EOD exit.

        Call this for every open position after each 15-min candle closes.

        Exit priority: SL > TARGET > EOD (conservative — SL always checked first).

        Returns closed-trade dict if an exit fired, else None.
        """
        pos = self.positions.get(symbol)
        if pos is None:
            return None

        now_ist = now.astimezone(IST).time()

        # ── EOD force-close ────────────────────────────────────
        # Checked FIRST so we always exit by 3:15 PM regardless of SL/target.
        # In real NSE intraday, Angel One auto-squares-off at ~3:20 PM.
        if now_ist >= FORCE_EXIT_AT:
            logger.info(f"[PAPER] {symbol}: EOD force-close at Rs{candle_close}")
            return self.close_position(symbol, candle_close, "EOD", now)

        direction = pos['direction']

        if direction == "BUY":
            # SL: candle went low enough to touch stop-loss
            if candle_low <= pos['stop_loss']:
                logger.info(
                    f"[PAPER] {symbol}: SL hit "
                    f"(low=Rs{candle_low} <= sl=Rs{pos['stop_loss']})"
                )
                return self.close_position(symbol, pos['stop_loss'], "SL", now)

            # Target: candle went high enough to touch target
            if candle_high >= pos['target']:
                logger.info(
                    f"[PAPER] {symbol}: TARGET hit "
                    f"(high=Rs{candle_high} >= target=Rs{pos['target']})"
                )
                return self.close_position(symbol, pos['target'], "TARGET", now)

        else:  # SELL (short)
            # SL: candle went high enough to touch stop-loss
            if candle_high >= pos['stop_loss']:
                logger.info(
                    f"[PAPER] {symbol}: SL hit "
                    f"(high=Rs{candle_high} >= sl=Rs{pos['stop_loss']})"
                )
                return self.close_position(symbol, pos['stop_loss'], "SL", now)

            # Target: candle went low enough to touch target
            if candle_low <= pos['target']:
                logger.info(
                    f"[PAPER] {symbol}: TARGET hit "
                    f"(low=Rs{candle_low} <= target=Rs{pos['target']})"
                )
                return self.close_position(symbol, pos['target'], "TARGET", now)

        return None   # position still open

    # ─────────────────────────────────────────────────────────
    #  EOD FORCE-CLOSE ALL
    # ─────────────────────────────────────────────────────────

    def force_close_all(self, prices: dict, now: datetime) -> list[dict]:
        """
        Force-close all open positions at given prices.

        Args:
            prices: {symbol: current_price}  — use candle close prices
            now:    Current datetime

        Returns:
            List of closed-trade dicts for all positions that were closed.
        """
        closed = []
        for symbol in list(self.positions.keys()):
            price = prices.get(symbol)
            if price is None:
                logger.warning(f"[PAPER] force_close_all: no price for {symbol} — skipping")
                continue
            trade = self.close_position(symbol, price, "EOD", now)
            if trade:
                closed.append(trade)
        return closed

    # ─────────────────────────────────────────────────────────
    #  PORTFOLIO SUMMARY
    # ─────────────────────────────────────────────────────────

    def get_summary(self, current_prices: dict | None = None) -> dict:
        """
        Return current portfolio state.

        Args:
            current_prices: {symbol: price} — if provided, includes unrealised P&L.

        Returns:
            {
                "cash":           float,
                "open_positions": int,
                "unrealised_pnl": float,   (0.0 if current_prices not provided)
                "portfolio_value": float,  (cash + unrealised, or just cash)
                "closed_today":   int,
                "net_pnl_today":  float,
            }
        """
        unrealised = 0.0
        if current_prices:
            for symbol, pos in self.positions.items():
                price = current_prices.get(symbol, pos['entry_price'])
                if pos['direction'] == "BUY":
                    unrealised += (price - pos['entry_price']) * pos['shares']
                else:
                    unrealised += (pos['entry_price'] - price) * pos['shares']

        net_pnl_today = sum(t['net_pnl'] for t in self.closed_trades)

        return {
            "cash":            round(self.cash, 2),
            "open_positions":  len(self.positions),
            "unrealised_pnl":  round(unrealised, 2),
            "portfolio_value": round(self.cash + unrealised, 2),
            "closed_today":    len(self.closed_trades),
            "net_pnl_today":   round(net_pnl_today, 2),
        }
