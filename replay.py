"""
replay.py — Fast Replay Mode (Development & Testing)

Simulates a full trading day using MockDataFeed without waiting for real
market hours. Processes all 25 candles of synthetic data instantly.

Use this to:
  - Test the full pipeline end-to-end at any time of day
  - Verify Claude decisions on realistic mock data
  - Check that P&L, charges, and DB writes all work correctly

The real bot (main.py) requires actual NSE market hours (9:15-3:30 PM IST).
This script ignores real time entirely.

Usage:
    python replay.py
    python replay.py --seed 123     (different market scenario)
    python replay.py --no-claude    (skip real API calls, use mock decisions)
"""

import argparse
import sys
from datetime import datetime, date, timedelta

import pytz
from loguru import logger

from config import IST, STARTING_CAPITAL, NIFTY_50_SYMBOLS, MAX_STOCK_PRICE, HISTORICAL_DAYS
from mock_feed import MockDataFeed, SEED_PRICES
from candle_store import CandleStore
from risk_manager import RiskManager
from paper_trader import PaperTrader
from prefilter import scan_for_candidates, PreFilterTracker
from pivot_points import calculate_pivot_points
from scheduler import candle_times_for_day
from db import init_db, insert_trade, insert_daily_summary

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    level="INFO",
    colorize=True,
)


def run_replay(seed: int = 42, use_claude: bool = True) -> None:

    logger.info("=" * 55)
    logger.info("  REPLAY MODE — simulating full trading day")
    logger.info(f"  Seed: {seed} | Claude: {'LIVE API' if use_claude else 'MOCKED (HOLD)'}")
    logger.info(f"  Capital: Rs{STARTING_CAPITAL:,.0f}")
    logger.info("=" * 55)

    init_db()

    # ── Setup ──────────────────────────────────────────────
    feed       = MockDataFeed(seed=seed)
    affordable = [s for s in NIFTY_50_SYMBOLS
                  if s in SEED_PRICES and SEED_PRICES[s] <= MAX_STOCK_PRICE]

    store      = CandleStore()
    pivots_map = {}

    for sym in affordable:
        df   = feed.get_historical_candles(sym, days=HISTORICAL_DAYS)
        store.load_historical(sym, df)
        prev = feed.get_previous_day_ohlc(sym)
        pivots_map[sym] = calculate_pivot_points(prev['high'], prev['low'], prev['close'])

    rm      = RiskManager(starting_capital=STARTING_CAPITAL)
    trader  = PaperTrader(starting_capital=STARTING_CAPITAL, risk_manager=rm)
    tracker = PreFilterTracker()

    # Use "today" as simulated trading date
    today = datetime.now(IST).date()
    # If today is a weekend, step back to Friday
    while today.weekday() >= 5:
        today -= timedelta(days=1)

    rm.reset_daily(STARTING_CAPITAL)
    starting_cash = STARTING_CAPITAL

    candle_times = candle_times_for_day(today)
    logger.info(f"  Simulating {len(candle_times)} candles for {today}")
    logger.info("")

    # ── Candle loop ────────────────────────────────────────
    from config import FORCE_EXIT_AT

    for candle_time in candle_times:
        time_str = candle_time.strftime("%I:%M %p")
        is_eod   = candle_time.time() >= FORCE_EXIT_AT
        open_syms = set(trader.positions.keys())

        # Check exits for open positions
        for sym in list(open_syms):
            df = store.get(sym, n=1)
            if df is None or len(df) == 0:
                continue
            c = df.iloc[-1]
            trade = trader.check_exits(
                sym,
                candle_high=c['high'],
                candle_low=c['low'],
                candle_close=c['close'],
                now=candle_time,
            )
            if trade:
                pnl_tag = "PROFIT" if trade['net_pnl'] >= 0 else "LOSS"
                logger.info(
                    f"[TRADE] {trade['direction']} {sym} x{trade['shares']} "
                    f"[{trade['exit_reason']}] {pnl_tag} Rs{trade['net_pnl']:.2f}"
                )
                try:
                    insert_trade(trade)
                except Exception as e:
                    logger.warning(f"[DB] {e}")

        # EOD — no new entries
        if is_eod:
            if trader.positions:
                prices = {}
                for sym in list(trader.positions.keys()):
                    df = store.get(sym, n=1)
                    if df is not None and len(df) > 0:
                        prices[sym] = df.iloc[-1]['close']
                closed = trader.force_close_all(prices, candle_time)
                for trade in closed:
                    pnl_tag = "PROFIT" if trade['net_pnl'] >= 0 else "LOSS"
                    logger.info(
                        f"[TRADE] {trade['direction']} {trade['symbol']} x{trade['shares']} "
                        f"[EOD] {pnl_tag} Rs{trade['net_pnl']:.2f}"
                    )
                    try:
                        insert_trade(trade)
                    except Exception as e:
                        logger.warning(f"[DB] {e}")
            break

        # Pre-filter scan
        tracker.reset(candle_time)
        candidates = scan_for_candidates(affordable, store, pivots_map, open_syms, tracker)

        if not candidates:
            logger.info(f"[{time_str}] No candidates")
            continue

        logger.info(
            f"[{time_str}] {len(candidates)} candidate(s): "
            + ", ".join(f"{c['symbol']}({c['score']})" for c in candidates[:5])
            + ("..." if len(candidates) > 5 else "")
        )

        # Claude / mock decisions
        for candidate in candidates:
            sym = candidate['symbol']

            allowed, reason = rm.can_open_new_trade(candle_time)
            if not allowed:
                logger.info(f"  Risk gate: {reason}")
                break

            if use_claude:
                from claude_agent import ask_claude
                decision = ask_claude(
                    symbol            = sym,
                    direction_hint    = candidate['direction'],
                    filter_score      = candidate['score'],
                    indicators        = candidate['indicators'],
                    pivots            = candidate['pivots'],
                    available_capital = trader.cash,
                    risk_per_trade    = trader.cash * 0.02,
                    current_time_str  = time_str,
                )
            else:
                decision = {"decision": "HOLD", "conviction": 0,
                            "entry_price": None, "stop_loss": None,
                            "target": None, "reasoning": "Mock mode", "rr_ratio": None}

            tracker.mark_sent(sym)

            if decision['decision'] == "HOLD":
                logger.info(f"  {sym}: HOLD")
                continue

            evaluation = rm.evaluate_trade(
                now               = candle_time,
                entry_price       = decision['entry_price'],
                stop_loss         = decision['stop_loss'],
                target            = decision['target'],
                direction         = decision['decision'],
                available_capital = trader.cash,
            )

            if not evaluation['approved']:
                logger.info(f"  {sym}: rejected — {evaluation['reason'][:60]}")
                continue

            ok, reason = trader.open_position(
                symbol      = sym,
                direction   = decision['decision'],
                shares      = evaluation['shares'],
                entry_price = decision['entry_price'],
                stop_loss   = decision['stop_loss'],
                target      = decision['target'],
                now         = candle_time,
            )
            if ok:
                logger.info(
                    f"  {sym}: OPENED {decision['decision']} x{evaluation['shares']} "
                    f"@ Rs{decision['entry_price']} "
                    f"SL=Rs{decision['stop_loss']} T=Rs{decision['target']} "
                    f"R:R={evaluation['rr_ratio']}"
                )

    # ── EOD Summary ────────────────────────────────────────
    summary = trader.get_summary()
    wins    = sum(1 for t in trader.closed_trades if t['net_pnl'] > 0)
    losses  = len(trader.closed_trades) - wins

    logger.info("")
    logger.info("=" * 55)
    logger.info("  REPLAY COMPLETE — DAILY SUMMARY")
    logger.info("=" * 55)
    logger.info(f"  Trades:     {summary['closed_today']} ({wins}W / {losses}L)")
    logger.info(f"  Net P&L:    Rs{summary['net_pnl_today']:.2f}")
    logger.info(f"  Cash:       Rs{summary['cash']:.2f}")
    logger.info(f"  Return:     {summary['net_pnl_today'] / starting_cash * 100:.2f}%")
    logger.info("=" * 55)

    try:
        insert_daily_summary(
            trade_date    = today,
            trades        = trader.closed_trades,
            starting_cash = starting_cash,
            ending_cash   = summary['cash'],
        )
        logger.info(f"  Results saved to trades.db")
    except Exception as e:
        logger.warning(f"[DB] {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay a simulated trading day")
    parser.add_argument("--seed",      type=int,  default=42,   help="Random seed for mock data")
    parser.add_argument("--no-claude", action="store_true",     help="Skip Claude API calls (all HOLD)")
    args = parser.parse_args()

    run_replay(seed=args.seed, use_claude=not args.no_claude)
