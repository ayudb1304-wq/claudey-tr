"""
risk_manager.py — Trade Risk & Position Sizing Engine

This module is the gatekeeper before any trade is placed.
It answers three questions:
  1. Are we allowed to trade at all right now? (daily cap, time, position count)
  2. How many shares should we buy given our risk budget?
  3. Does this specific setup meet our minimum R:R requirement?

RULES (from config.py):
  - Max 2% capital at risk per trade (RISK_PER_TRADE_PCT = 0.02)
  - Max 3% daily loss cap — no new entries once hit (MAX_DAILY_LOSS_PCT = 0.03)
  - Max 2 open positions simultaneously (MAX_OPEN_POSITIONS = 2)
  - No new entries at or after 3:00 PM IST (positions opened earlier still run)
  - Minimum R:R of 1.5 (confirmed here — claude_agent also checks at 1.4 threshold)
  - Minimum 1 share required — if position sizing returns 0, skip the trade

POSITION SIZING:
  shares = floor(risk_budget / distance_to_stop)
  Where:
    risk_budget      = available_capital × RISK_PER_TRADE_PCT
    distance_to_stop = abs(entry_price - stop_loss)

  Then verify: entry_price × shares <= available_capital
  (We can't spend more than we have, even if risk math allows it)

IMPORTANT:
  The RiskManager is stateful — it tracks:
    - `daily_pnl`    (updated by paper_trader on every trade close)
    - `open_count`   (updated by paper_trader on open/close)
  Call `reset_daily()` at the start of each trading day (9:15 AM).
"""

import math
from datetime import datetime, time as dt_time

import pytz
from loguru import logger

from config import (
    IST,
    RISK_PER_TRADE_PCT,
    MAX_DAILY_LOSS_PCT,
    MAX_OPEN_POSITIONS,
    MIN_RISK_REWARD_RATIO,
    NO_NEW_ENTRY_AFTER,
)


class RiskManager:
    """
    Stateful risk gatekeeper.

    State is reset each morning via reset_daily().
    Paper trader calls update_daily_pnl() and update_open_count()
    after each trade open/close.
    """

    def __init__(self, starting_capital: float):
        """
        Args:
            starting_capital: Initial portfolio value (e.g. 10000.0).
                              Used to calculate daily loss cap in rupees.
        """
        if starting_capital <= 0:
            raise ValueError("starting_capital must be positive")

        self._starting_capital = starting_capital
        self._daily_pnl:   float = 0.0    # running net P&L for today
        self._open_count:  int   = 0      # number of currently open positions

    # ─────────────────────────────────────────────────────────
    #  STATE UPDATES (called by paper_trader)
    # ─────────────────────────────────────────────────────────

    def reset_daily(self, current_capital: float) -> None:
        """
        Reset state for a new trading day.
        Call at 9:15 AM IST every morning.

        Args:
            current_capital: Portfolio value at day open (used for loss cap calc).
        """
        self._starting_capital = current_capital
        self._daily_pnl        = 0.0
        self._open_count       = 0
        logger.info(
            f"[RISK] Daily reset. Starting capital: Rs{current_capital:.2f}. "
            f"Daily loss cap: Rs{self.daily_loss_cap:.2f}"
        )

    def update_daily_pnl(self, trade_net_pnl: float) -> None:
        """Add a completed trade's net P&L to today's running total."""
        self._daily_pnl += trade_net_pnl
        logger.debug(f"[RISK] Daily P&L updated: Rs{self._daily_pnl:.2f}")

    def update_open_count(self, delta: int) -> None:
        """
        Adjust the open position count.
        delta = +1 when a position opens, -1 when it closes.
        """
        self._open_count = max(0, self._open_count + delta)
        logger.debug(f"[RISK] Open positions: {self._open_count}")

    # ─────────────────────────────────────────────────────────
    #  COMPUTED PROPERTIES
    # ─────────────────────────────────────────────────────────

    @property
    def daily_loss_cap(self) -> float:
        """Max loss allowed today in rupees (3% of day-open capital)."""
        return self._starting_capital * MAX_DAILY_LOSS_PCT

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def open_count(self) -> int:
        return self._open_count

    # ─────────────────────────────────────────────────────────
    #  GATE CHECKS
    # ─────────────────────────────────────────────────────────

    def is_daily_loss_cap_hit(self) -> bool:
        """
        True if today's losses have reached or exceeded the daily cap.
        Note: daily_pnl is negative for losses; cap is positive.
        """
        return self._daily_pnl <= -self.daily_loss_cap

    def is_too_late_to_trade(self, now: datetime) -> bool:
        """
        True if current time is at or after the no-new-entry cutoff (3:00 PM IST).
        Positions already open continue to run until MARKET_CLOSE_TIME (3:15 PM).
        """
        now_ist = now.astimezone(IST).time()
        return now_ist >= NO_NEW_ENTRY_AFTER

    def is_max_positions_reached(self) -> bool:
        """True if we already hold the maximum allowed open positions."""
        return self._open_count >= MAX_OPEN_POSITIONS

    def can_open_new_trade(self, now: datetime) -> tuple[bool, str]:
        """
        Master gate check — call this before sizing any position.

        Returns:
            (True, "")          — trade is allowed
            (False, reason_str) — trade is blocked, reason explains why

        Checks in order:
          1. Daily loss cap hit
          2. Too late in the day
          3. Too many open positions
        """
        if self.is_daily_loss_cap_hit():
            reason = (
                f"Daily loss cap hit "
                f"(P&L=Rs{self._daily_pnl:.2f}, "
                f"cap=-Rs{self.daily_loss_cap:.2f})"
            )
            logger.warning(f"[RISK] Blocked: {reason}")
            return False, reason

        if self.is_too_late_to_trade(now):
            reason = (
                f"Too late to open new trades "
                f"(cutoff={NO_NEW_ENTRY_AFTER.strftime('%H:%M')} IST)"
            )
            logger.debug(f"[RISK] Blocked: {reason}")
            return False, reason

        if self.is_max_positions_reached():
            reason = (
                f"Max open positions reached ({self._open_count}/{MAX_OPEN_POSITIONS})"
            )
            logger.debug(f"[RISK] Blocked: {reason}")
            return False, reason

        return True, ""

    # ─────────────────────────────────────────────────────────
    #  POSITION SIZING
    # ─────────────────────────────────────────────────────────

    def size_position(
        self,
        entry_price:       float,
        stop_loss:         float,
        available_capital: float,
    ) -> int:
        """
        Calculate the number of shares to trade.

        Uses: shares = floor(risk_budget / distance_to_stop)
        Then caps at: floor(available_capital / entry_price) — can't overspend.

        Args:
            entry_price:       Proposed entry price
            stop_loss:         Proposed stop-loss price
            available_capital: Current cash in the paper portfolio

        Returns:
            int — number of shares (0 means "skip this trade — too small to fit")
        """
        distance = abs(entry_price - stop_loss)
        if distance <= 0:
            logger.warning("[RISK] SL equals entry — cannot size position")
            return 0

        risk_budget  = available_capital * RISK_PER_TRADE_PCT
        shares_by_risk     = math.floor(risk_budget / distance)
        shares_by_capital  = math.floor(available_capital / entry_price)

        shares = min(shares_by_risk, shares_by_capital)

        logger.debug(
            f"[RISK] Sizing: entry=Rs{entry_price} sl=Rs{stop_loss} "
            f"distance=Rs{distance:.2f} "
            f"risk_budget=Rs{risk_budget:.2f} "
            f"shares_by_risk={shares_by_risk} "
            f"shares_by_capital={shares_by_capital} "
            f"→ {shares} shares"
        )

        return max(0, shares)

    # ─────────────────────────────────────────────────────────
    #  R:R VALIDATION
    # ─────────────────────────────────────────────────────────

    def check_rr_ratio(
        self,
        entry_price: float,
        stop_loss:   float,
        target:      float,
        direction:   str,     # "BUY" or "SELL"
    ) -> tuple[bool, float]:
        """
        Verify the risk-to-reward ratio meets the minimum threshold.

        claude_agent already validates at 1.4 (forgiving rounding).
        This is the strict 1.5 check before actual order placement.

        Args:
            entry_price: Proposed entry
            stop_loss:   Proposed SL
            target:      Proposed target
            direction:   "BUY" or "SELL"

        Returns:
            (passes: bool, rr_ratio: float)
        """
        if direction == "BUY":
            risk   = entry_price - stop_loss
            reward = target - entry_price
        else:  # SELL
            risk   = stop_loss - entry_price
            reward = entry_price - target

        if risk <= 0:
            return False, 0.0

        rr = reward / risk
        passes = rr >= MIN_RISK_REWARD_RATIO
        return passes, round(rr, 2)

    # ─────────────────────────────────────────────────────────
    #  FULL TRADE EVALUATION
    # ─────────────────────────────────────────────────────────

    def evaluate_trade(
        self,
        now:               datetime,
        entry_price:       float,
        stop_loss:         float,
        target:            float,
        direction:         str,
        available_capital: float,
    ) -> dict:
        """
        Full pre-trade evaluation combining all checks and position sizing.

        Returns a dict the paper_trader uses directly:
        {
            "approved":  bool,
            "shares":    int,       (0 if not approved)
            "rr_ratio":  float,
            "risk_Rs":   float,     (shares × distance_to_SL)
            "reason":    str,       (why rejected, or "" if approved)
        }
        """
        # ── Gate check ────────────────────────────────────────
        allowed, gate_reason = self.can_open_new_trade(now)
        if not allowed:
            return _rejected(gate_reason)

        # ── R:R check ─────────────────────────────────────────
        rr_ok, rr_ratio = self.check_rr_ratio(entry_price, stop_loss, target, direction)
        if not rr_ok:
            reason = (
                f"R:R {rr_ratio:.2f} below minimum {MIN_RISK_REWARD_RATIO} "
                f"(entry=Rs{entry_price} sl=Rs{stop_loss} target=Rs{target})"
            )
            logger.debug(f"[RISK] Blocked: {reason}")
            return _rejected(reason, rr_ratio=rr_ratio)

        # ── Position sizing ────────────────────────────────────
        shares = self.size_position(entry_price, stop_loss, available_capital)
        if shares == 0:
            reason = (
                f"Position size = 0 shares "
                f"(capital=Rs{available_capital:.2f} "
                f"entry=Rs{entry_price} sl=Rs{stop_loss})"
            )
            logger.debug(f"[RISK] Blocked: {reason}")
            return _rejected(reason, rr_ratio=rr_ratio)

        risk_rs = abs(entry_price - stop_loss) * shares

        logger.info(
            f"[RISK] APPROVED: {direction} {shares} shares @ Rs{entry_price} "
            f"sl=Rs{stop_loss} target=Rs{target} "
            f"R:R={rr_ratio} risk=Rs{risk_rs:.2f}"
        )

        return {
            "approved": True,
            "shares":   shares,
            "rr_ratio": rr_ratio,
            "risk_Rs":  round(risk_rs, 2),
            "reason":   "",
        }


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def _rejected(reason: str, rr_ratio: float = 0.0) -> dict:
    return {
        "approved": False,
        "shares":   0,
        "rr_ratio": rr_ratio,
        "risk_Rs":  0.0,
        "reason":   reason,
    }
