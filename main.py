"""
main.py — Trading Bot Main Orchestration Loop

Wires all components together and runs the 15-minute candle loop.

STARTUP SEQUENCE:
  1. Load config, create components
  2. Pre-load 10 days of historical candles for all affordable stocks
  3. Calculate pivot points from previous day OHLC (done once per morning)
  4. Wait for market open (9:15 AM IST)
  5. Enter the main candle loop

MAIN LOOP (runs every 15 minutes at each candle close):
  For each candle close:
    a. Fetch the latest candle and append to candle store
    b. Check exits for all open positions (SL / target / EOD)
    c. If time >= 3:15 PM, force-close everything and print daily summary
    d. Scan all stocks for pre-filter candidates
    e. For each candidate (highest score first), ask Claude
    f. If Claude says BUY/SELL and risk checks pass, open a paper position
    g. Print a one-line interval summary

DATA SOURCE:
  Controlled by DATA_SOURCE in config.py:
    "mock"     → MockDataFeed (default, works offline)
    "yfinance" → YFinanceDataFeed (free, unreliable for India)
    "angelone" → AngelOneDataFeed (live NSE data, requires API keys)

RUN:
    python main.py

STOP:
    Ctrl+C — triggers graceful shutdown (closes all positions, prints summary)
"""

import sys
import time
from datetime import datetime, date

import pytz
from loguru import logger

from config import (
    IST, DATA_SOURCE, STARTING_CAPITAL,
    NIFTY_50_SYMBOLS, MAX_STOCK_PRICE,
    HISTORICAL_DAYS, MARKET_OPEN, FORCE_EXIT_AT,
    MIN_RISK_REWARD_RATIO,
)
from candle_store import CandleStore
from risk_manager import RiskManager
from paper_trader import PaperTrader
from prefilter import scan_for_candidates, PreFilterTracker
from pivot_points import calculate_pivot_points
from claude_agent import ask_claude
from scheduler import (
    is_trading_day, is_market_open, is_candle_close,
    seconds_until_next_candle, next_candle_time,
)
from db import init_db, insert_trade, insert_daily_summary

# ─────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    "logs/bot_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
)


# ─────────────────────────────────────────────────────────────
#  DATA FEED FACTORY
# ─────────────────────────────────────────────────────────────

def _create_feed():
    if DATA_SOURCE == "mock":
        from mock_feed import MockDataFeed
        logger.info("[MAIN] Using MockDataFeed (synthetic data)")
        return MockDataFeed(seed=42)
    elif DATA_SOURCE == "yfinance":
        from yfinance_feed import YFinanceDataFeed
        logger.info("[MAIN] Using YFinanceDataFeed")
        return YFinanceDataFeed()
    elif DATA_SOURCE == "angelone":
        from auth import login
        from angelone_feed import AngelOneDataFeed
        logger.info("[MAIN] Using AngelOneDataFeed — logging in...")
        login()
        return AngelOneDataFeed()
    else:
        raise ValueError(f"Unknown DATA_SOURCE: {DATA_SOURCE!r}")


# ─────────────────────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────────────────────

def startup():
    """
    One-time initialisation. Returns (feed, store, affordable_symbols, pivots_map, trader, rm).
    """
    feed = _create_feed()

    # Filter to stocks we can afford (price <= MAX_STOCK_PRICE)
    affordable = []
    for sym in NIFTY_50_SYMBOLS:
        try:
            prev = feed.get_previous_day_ohlc(sym)
            if prev['close'] <= MAX_STOCK_PRICE:
                affordable.append(sym)
        except Exception:
            pass    # skip symbols with no data

    logger.info(f"[MAIN] {len(affordable)}/{len(NIFTY_50_SYMBOLS)} symbols affordable (price <= Rs{MAX_STOCK_PRICE})")

    # Pre-load candle history
    store = CandleStore()
    loaded = 0
    for sym in affordable:
        try:
            df = feed.get_historical_candles(sym, days=HISTORICAL_DAYS)
            store.load_historical(sym, df)
            loaded += 1
        except Exception as e:
            logger.warning(f"[MAIN] {sym}: failed to load history — {e}")

    logger.info(f"[MAIN] Loaded candle history for {loaded} symbols")

    # Calculate pivot points (once per morning, from previous day OHLC)
    pivots_map = {}
    for sym in affordable:
        try:
            prev = feed.get_previous_day_ohlc(sym)
            pivots_map[sym] = calculate_pivot_points(
                prev['high'], prev['low'], prev['close']
            )
        except Exception as e:
            logger.warning(f"[MAIN] {sym}: pivot calculation failed — {e}")

    logger.info(f"[MAIN] Pivot points calculated for {len(pivots_map)} symbols")

    # Risk manager and paper trader
    rm     = RiskManager(starting_capital=STARTING_CAPITAL)
    trader = PaperTrader(starting_capital=STARTING_CAPITAL, risk_manager=rm)
    rm.reset_daily(STARTING_CAPITAL)

    return feed, store, affordable, pivots_map, trader, rm


# ─────────────────────────────────────────────────────────────
#  PROCESS ONE CANDLE CLOSE
# ─────────────────────────────────────────────────────────────

def process_candle(
    now:          datetime,
    feed,
    store:        CandleStore,
    affordable:   list,
    pivots_map:   dict,
    trader:       PaperTrader,
    rm:           RiskManager,
    tracker:      PreFilterTracker,
) -> None:
    """
    Everything that happens at each 15-minute candle close.
    """
    now_ist      = now.astimezone(IST)
    time_str     = now_ist.strftime("%I:%M %p")
    is_eod       = now_ist.time() >= FORCE_EXIT_AT
    open_symbols = set(trader.positions.keys())

    # ── 1. Append new candle to store ─────────────────────────
    appended = 0
    for sym in affordable:
        try:
            df = feed.get_historical_candles(sym, days=1)
            if df is not None and len(df) > 0:
                last = df.iloc[-1]
                store.append(sym, {
                    'open':   last['open'],
                    'high':   last['high'],
                    'low':    last['low'],
                    'close':  last['close'],
                    'volume': last['volume'],
                }, now)
                appended += 1
        except Exception:
            pass

    # ── 2. Check exits for all open positions ─────────────────
    for sym in list(open_symbols):
        try:
            df = store.get(sym, n=1)
            if df is None or len(df) == 0:
                continue
            c = df.iloc[-1]
            trade = trader.check_exits(
                sym,
                candle_high=c['high'],
                candle_low=c['low'],
                candle_close=c['close'],
                now=now,
            )
            if trade:
                _log_trade(trade)
        except Exception as e:
            logger.warning(f"[MAIN] Exit check error for {sym}: {e}")

    # ── 3. EOD — no new entries after FORCE_EXIT_AT ───────────
    if is_eod:
        if trader.positions:
            prices = {}
            for sym in list(trader.positions.keys()):
                try:
                    df = store.get(sym, n=1)
                    if df is not None and len(df) > 0:
                        prices[sym] = df.iloc[-1]['close']
                except Exception:
                    pass
            trader.force_close_all(prices, now)
        _print_daily_summary(trader, rm)   # starting_cash defaults to STARTING_CAPITAL
        return

    # ── 4. Pre-filter scan ────────────────────────────────────
    tracker.reset(now)
    candidates = scan_for_candidates(affordable, store, pivots_map, open_symbols, tracker)

    if not candidates:
        logger.info(f"[MAIN] {time_str} — no candidates (open={len(trader.positions)})")
        return

    logger.info(
        f"[MAIN] {time_str} — {len(candidates)} candidate(s): "
        + ", ".join(f"{c['symbol']}({c['score']})" for c in candidates)
    )

    # ── 5. Claude decision loop ────────────────────────────────
    for candidate in candidates:
        sym      = candidate['symbol']
        inds     = candidate['indicators']
        pivots   = candidate['pivots']

        allowed, gate_reason = rm.can_open_new_trade(now)
        if not allowed:
            logger.info(f"[MAIN] Risk gate blocked further entries: {gate_reason}")
            break

        decision = ask_claude(
            symbol            = sym,
            direction_hint    = candidate['direction'],
            filter_score      = candidate['score'],
            indicators        = inds,
            pivots            = pivots,
            available_capital = trader.cash,
            risk_per_trade    = trader.cash * 0.02,
            current_time_str  = time_str,
        )

        tracker.mark_sent(sym)

        if decision['decision'] == "HOLD":
            logger.info(f"[MAIN] {sym}: Claude HOLD — {decision['reasoning'][:60]}")
            continue

        # ── 6. Risk evaluation ────────────────────────────────
        evaluation = rm.evaluate_trade(
            now               = now,
            entry_price       = decision['entry_price'],
            stop_loss         = decision['stop_loss'],
            target            = decision['target'],
            direction         = decision['decision'],
            available_capital = trader.cash,
        )

        if not evaluation['approved']:
            logger.info(f"[MAIN] {sym}: risk rejected — {evaluation['reason']}")
            continue

        # ── 7. Open position ──────────────────────────────────
        ok, reason = trader.open_position(
            symbol      = sym,
            direction   = decision['decision'],
            shares      = evaluation['shares'],
            entry_price = decision['entry_price'],
            stop_loss   = decision['stop_loss'],
            target      = decision['target'],
            now         = now,
        )

        if not ok:
            logger.warning(f"[MAIN] {sym}: open_position failed — {reason}")

    # ── 8. Interval summary line ──────────────────────────────
    summary = trader.get_summary()
    logger.info(
        f"[MAIN] {time_str} summary — "
        f"cash=Rs{summary['cash']:.0f} "
        f"open={summary['open_positions']} "
        f"closed={summary['closed_today']} "
        f"net_pnl=Rs{summary['net_pnl_today']:.2f}"
    )


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def _log_trade(trade: dict) -> None:
    direction = trade['direction']
    symbol    = trade['symbol']
    pnl_sign  = "PROFIT" if trade['net_pnl'] >= 0 else "LOSS"
    logger.info(
        f"[TRADE] {direction} {symbol} x {trade['shares']} "
        f"@ Rs{trade['entry_price']} -> Rs{trade['exit_price']} "
        f"[{trade['exit_reason']}] "
        f"{pnl_sign} Rs{trade['net_pnl']:.2f} (net)"
    )
    try:
        insert_trade(trade)
    except Exception as e:
        logger.warning(f"[DB] Failed to save trade: {e}")


def _print_daily_summary(trader: PaperTrader, rm: RiskManager,
                          starting_cash: float = STARTING_CAPITAL) -> None:
    summary = trader.get_summary()
    wins    = sum(1 for t in trader.closed_trades if t['net_pnl'] > 0)
    losses  = sum(1 for t in trader.closed_trades if t['net_pnl'] <= 0)

    logger.info("=" * 55)
    logger.info("  DAILY SUMMARY")
    logger.info("=" * 55)
    logger.info(f"  Trades closed:   {summary['closed_today']} ({wins}W / {losses}L)")
    logger.info(f"  Net P&L today:   Rs{summary['net_pnl_today']:.2f}")
    logger.info(f"  Cash remaining:  Rs{summary['cash']:.2f}")
    logger.info(f"  Portfolio value: Rs{summary['portfolio_value']:.2f}")
    logger.info("=" * 55)

    try:
        from datetime import date
        insert_daily_summary(
            trade_date    = date.today(),
            trades        = trader.closed_trades,
            starting_cash = starting_cash,
            ending_cash   = summary['cash'],
        )
    except Exception as e:
        logger.warning(f"[DB] Failed to save daily summary: {e}")


# ─────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 55)
    logger.info("  NSE PAPER TRADING BOT — STARTING UP")
    logger.info(f"  Data source:  {DATA_SOURCE.upper()}")
    logger.info(f"  Capital:      Rs{STARTING_CAPITAL:,.0f}")
    logger.info("=" * 55)

    import os
    os.makedirs("logs", exist_ok=True)

    init_db()
    feed, store, affordable, pivots_map, trader, rm = startup()
    tracker = PreFilterTracker()
    _starting_cash = STARTING_CAPITAL

    try:
        # ── Wait for market open ───────────────────────────────
        while True:
            now = datetime.now(tz=IST)
            if not is_trading_day(now):
                logger.info(f"[MAIN] Not a trading day ({now.strftime('%A %d-%b')}). Exiting.")
                return

            if is_market_open(now):
                break

            wait_secs = seconds_until_next_candle(now)
            logger.info(
                f"[MAIN] Market not yet open. "
                f"Next candle at {next_candle_time(now).strftime('%H:%M')} IST. "
                f"Waiting {wait_secs}s..."
            )
            time.sleep(min(wait_secs, 60))

        logger.info("[MAIN] Market is open. Entering main loop.")

        # ── Main candle loop ─────────────────────────────────
        while True:
            now = datetime.now(tz=IST)

            if not is_market_open(now):
                logger.info("[MAIN] Market closed. Exiting loop.")
                break

            if is_candle_close(now):
                process_candle(now, feed, store, affordable,
                               pivots_map, trader, rm, tracker)
                # Sleep 30s to avoid processing the same candle twice
                time.sleep(30)
            else:
                wait_secs = seconds_until_next_candle(now)
                logger.debug(f"[MAIN] Next candle in {wait_secs}s")
                time.sleep(min(wait_secs, 10))

    except KeyboardInterrupt:
        logger.info("[MAIN] Ctrl+C received — graceful shutdown")
        now = datetime.now(tz=IST)

        if trader.positions:
            logger.info(f"[MAIN] Force-closing {len(trader.positions)} open position(s)...")
            prices = {}
            for sym in list(trader.positions.keys()):
                try:
                    df = store.get(sym, n=1)
                    if df is not None and len(df) > 0:
                        prices[sym] = df.iloc[-1]['close']
                except Exception:
                    pass
            trader.force_close_all(prices, now)

        _print_daily_summary(trader, rm, starting_cash=_starting_cash)
        logger.info("[MAIN] Shutdown complete.")


if __name__ == "__main__":
    main()
