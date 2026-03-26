"""
config.py — All constants and configuration for the trading bot.

If you want to change a setting (e.g., risk per trade, max positions),
change it here — never hardcode values inside other files.
"""

import pytz
from datetime import time

# ─────────────────────────────────────────────────────────────
#  TIMEZONE
#  All times in this bot are IST (Indian Standard Time = UTC+5:30)
#  ALWAYS use this when working with datetimes — never use the
#  system clock directly, which may be a different timezone on Windows.
# ─────────────────────────────────────────────────────────────
IST = pytz.timezone('Asia/Kolkata')

# ─────────────────────────────────────────────────────────────
#  MARKET TIMING
# ─────────────────────────────────────────────────────────────
MARKET_OPEN       = time(9, 15, 0)    # NSE opens at 9:15 AM IST
MARKET_CLOSE      = time(15, 30, 0)   # NSE closes at 3:30 PM IST
NO_NEW_ENTRY_AFTER = time(15, 0, 0)   # Stop opening new trades at 3:00 PM
FORCE_EXIT_AT     = time(15, 15, 0)   # Close ALL positions by 3:15 PM
                                       # (Angel One auto-square-off is ~3:20 PM)
DAILY_LOGIN_AT    = time(9, 0, 0)     # Re-login to refresh token at 9:00 AM
SKIP_FIRST_CANDLE = True              # Do not enter trades on the 9:15–9:30 candle
                                       # (gap-open candles are unreliable for signals)

# ─────────────────────────────────────────────────────────────
#  CANDLE SETTINGS
# ─────────────────────────────────────────────────────────────
CANDLE_INTERVAL        = "FIFTEEN_MINUTE"  # Angel One API interval string
CANDLE_INTERVAL_MINUTES = 15
HISTORICAL_DAYS        = 10     # Days of 15-min history to pre-load at startup
                                 # 10 days × ~25 candles/day = ~250 candles
                                 # This is enough to seed EMA 200 (needs 200 bars)

# ─────────────────────────────────────────────────────────────
#  CAPITAL & RISK SETTINGS
# ─────────────────────────────────────────────────────────────
STARTING_CAPITAL       = 25_000.0    # ₹25,000 paper trading capital

RISK_PER_TRADE_PCT     = 0.02        # Risk 2% of available capital per trade
                                      # At ₹10,000 → ₹200 max loss per trade

MAX_DAILY_LOSS_PCT     = 0.03        # Stop trading for the day if total loss
                                      # reaches 3% of starting capital = ₹300

MAX_OPEN_POSITIONS     = 2           # Never hold more than 2 stocks at once
                                      # With ₹10k, more than 2 spreads capital too thin

MAX_POSITION_SIZE_PCT  = 0.50        # No single trade can use more than 50% of
                                      # available capital (₹5,000 max per trade)

MIN_STOCK_PRICE        = 10.0        # Skip penny stocks
MAX_STOCK_PRICE        = 5_000.0     # Skip stocks we can't afford ≥1 share
                                      # 20% of ₹25,000 = ₹5,000 per share max

MIN_RISK_REWARD_RATIO  = 1.5         # Claude's target must be ≥ 1.5× the risk
                                      # e.g. if SL = ₹10 away, target must be ≥ ₹15 away

MIN_CLAUDE_CONVICTION  = 6           # Claude scores conviction 1–10.
                                      # Skip trade if conviction < 6.

# ─────────────────────────────────────────────────────────────
#  PRE-FILTER SETTINGS
#  Before calling Claude, we score each stock 0–5 based on
#  how many indicators align. Only scores ≥ MIN_FILTER_SCORE
#  get sent to Claude (saves API cost).
# ─────────────────────────────────────────────────────────────
MIN_FILTER_SCORE       = 2           # Call Claude only if ≥2 indicators agree
VOLUME_RATIO_THRESHOLD = 1.5         # Volume must be 1.5× the 20-period average
RSI_OVERSOLD           = 35          # RSI below this → potential long signal
RSI_OVERBOUGHT         = 65          # RSI above this → potential short signal
PIVOT_PROXIMITY_PCT    = 0.75        # Price within 0.75% of a pivot level counts

# ─────────────────────────────────────────────────────────────
#  SIMULATION SETTINGS (Paper Trading)
# ─────────────────────────────────────────────────────────────
SLIPPAGE_PCT = 0.0005    # 0.05% slippage on market orders
                          # Realistic for Nifty 50 liquid stocks on NSE

# ─────────────────────────────────────────────────────────────
#  DATA SOURCE SWITCH
#  "mock"      → synthetic data, zero dependencies        ← USE THIS NOW
#  "yfinance"  → free Yahoo Finance data (unreliable for India)
#  "angelone"  → real NSE live data, requires API keys    ← switch when keys arrive
# ─────────────────────────────────────────────────────────────
DATA_SOURCE = "mock"

# ─────────────────────────────────────────────────────────────
#  ANGEL ONE API SETTINGS
# ─────────────────────────────────────────────────────────────
ANGEL_ONE_EXCHANGE     = "NSE"
ANGEL_ONE_PRODUCT_TYPE = "INTRADAY"   # MIS (Margin Intraday Square-off)

# URL to download the Angel One instrument master file.
# This file maps trading symbols (like "RELIANCE") to numeric tokens (like "2885").
# Angel One requires numeric tokens for API calls — symbols alone don't work.
# Download this file once at startup and update monthly.
SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)
SCRIP_MASTER_FILE = "scrip_master.json"   # Saved locally (added to .gitignore)

# ─────────────────────────────────────────────────────────────
#  NIFTY 50 SYMBOLS
#
#  These are the NSE trading symbols for the 50 stocks in the Nifty 50 index.
#  The actual numeric tokens (needed for Angel One API) are fetched at runtime
#  from the scrip master file — see instruments.py.
#
#  IMPORTANT: Nifty 50 composition changes ~twice a year.
#  Verify this list at: https://www.nseindia.com/products/content/equities/indices/nifty50.htm
# ─────────────────────────────────────────────────────────────
NIFTY_50_SYMBOLS = [
    "ADANIENT",    "ADANIPORTS",  "APOLLOHOSP",  "ASIANPAINT",  "AXISBANK",
    "BAJAJ-AUTO",  "BAJFINANCE",  "BAJAJFINSV",  "BPCL",        "BHARTIARTL",
    "BRITANNIA",   "CIPLA",       "COALINDIA",   "DIVISLAB",    "DRREDDY",
    "EICHERMOT",   "GRASIM",      "HCLTECH",     "HDFCBANK",    "HDFCLIFE",
    "HEROMOTOCO",  "HINDALCO",    "HINDUNILVR",  "ICICIBANK",   "INDUSINDBK",
    "INFY",        "ITC",         "JSWSTEEL",    "KOTAKBANK",   "LT",
    "LTIM",        "M&M",         "MARUTI",      "NESTLEIND",   "NTPC",
    "ONGC",        "POWERGRID",   "RELIANCE",    "SBILIFE",     "SBIN",
    "SHRIRAMFIN",  "SUNPHARMA",   "TATACONSUM",  "TATAMOTORS",  "TATASTEEL",
    "TCS",         "TECHM",       "TITAN",       "ULTRACEMCO",  "WIPRO",
]

# ─────────────────────────────────────────────────────────────
#  NSE HOLIDAYS 2026
#  The bot will not start on these dates.
#  Update this list each year from the NSE official holiday calendar:
#  https://www.nseindia.com/products/content/equities/equities/mrkt_timing_holidays.htm
# ─────────────────────────────────────────────────────────────
NSE_HOLIDAYS_2026 = [
    "2026-01-26",   # Republic Day
    "2026-02-26",   # Mahashivratri (verify with NSE)
    "2026-03-25",   # Holi
    "2026-04-02",   # Ram Navami (verify)
    "2026-04-14",   # Dr. Ambedkar Jayanti (verify)
    "2026-05-01",   # Maharashtra Day
    "2026-08-15",   # Independence Day
    "2026-10-02",   # Gandhi Jayanti
    "2026-10-24",   # Dussehra (verify)
    "2026-11-04",   # Diwali Laxmi Puja (verify)
    "2026-11-05",   # Diwali-Balipratipada (verify)
    "2026-11-25",   # Gurunanak Jayanti (verify)
    "2026-12-25",   # Christmas
]
# NOTE: Holiday dates marked "(verify)" should be confirmed against the
# official NSE calendar — exact dates for festivals shift every year.

# ─────────────────────────────────────────────────────────────
#  INDICATOR SETTINGS
# ─────────────────────────────────────────────────────────────
RSI_PERIOD      = 14
EMA_SHORT       = 20
EMA_MEDIUM      = 50
EMA_LONG        = 200
MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIGNAL     = 9
VOLUME_SMA      = 20

# Minimum candles needed before any indicator is valid.
# The bot will not generate signals until this many candles exist.
MIN_CANDLES_REQUIRED = 200   # EMA 200 is the most demanding — sets the bar
