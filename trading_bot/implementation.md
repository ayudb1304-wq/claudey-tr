# Trading Bot — Implementation Plan

**Capital:** ₹10,000 paper → live
**Market:** NSE Nifty 50 · Intraday · 15-min candles
**Stack:** Python + Angel One SmartAPI + Claude API (`claude-sonnet-4-6`)
**Last updated:** 2026-03-26

---

## Master Progress Tracker

Quick reference — check this before every session to know where we are.

### Build Status

| Phase | Description | Files Written | Tests Passing | Blocked By |
|---|---|---|---|---|
| 1 | Environment & Auth | ✅ | ⏳ pending | Angel One API keys |
| 2 | Market Data Layer | ✅ | ✅ | — |
| 3 | Indicator Engine | ✅ | ✅ | — |
| 4 | Pre-filter Engine | ✅ | ✅ | — |
| 5 | Claude Agent | ✅ | ✅ | — |
| 6 | Transaction Costs | ✅ | ✅ | — |
| 7 | Risk Manager | ✅ | ✅ | — |
| 8 | Paper Trader | ✅ | ✅ | — |
| 9 | Main Loop | ✅ | ✅ | — |
| 10 | Logging & DB | ✅ | ✅ | — |
| 11 | Paper Run (4 wks) | ⬜ | ⬜ | Phase 10 |
| 12 | Live Migration | ⬜ | ⬜ | Phase 11 + API keys |

---

### Phase 1 — Environment & Authentication
- [x] `requirements.txt` written (updated for Python 3.14 — no pinned versions)
- [x] `.env.example` created
- [x] `.gitignore` created
- [x] `config.py` written (all constants, risk rules, Nifty 50 symbol list)
- [x] `auth.py` written (Angel One login, TOTP generation, token management)
- [x] `instruments.py` written (ScripMaster downloader + token loader)
- [x] `setup.py` written (one-time setup script for beginners)
- [x] `test_phase1.py` written
- [ ] **Run `test_phase1.py` — all checks pass** ← BLOCKED: waiting for Angel One API keys
- [ ] Verify TOTP generates correct 6-digit code matching authenticator app
- [ ] Verify daily 9:00 AM re-login is scheduled correctly in `main.py`

### Phase 2 — Market Data Layer
- [x] `data_feed.py` written (abstract base class — shared interface for all data sources)
- [x] `yfinance_feed.py` written (free dev data source, no API keys needed)
- [x] `angelone_feed.py` written (production stub with clear NotImplementedError messages)
- [x] `candle_store.py` written (per-symbol rolling candle buffer, max 300 candles)
- [x] `test_phase2.py` written
- [x] `requirements.txt` fixed for Python 3.14 (`pandas>=2.2.0`, `numpy>=2.0.0`, dropped `pandas-ta`)
- [ ] **Run `test_phase2.py` — all checks pass** ← IN PROGRESS
- [ ] Implement `angelone_feed.py` — `get_historical_candles()` ← BLOCKED: API keys
- [ ] Implement `angelone_feed.py` — `get_previous_day_ohlc()` ← BLOCKED: API keys
- [ ] Implement `angelone_feed.py` — `start_live_feed()` with WebSocket ← BLOCKED: API keys
- [ ] Implement `angelone_feed.py` — WebSocket auto-reconnect (exponential backoff: 1s→2s→4s→30s max)
- [ ] Switch `DATA_SOURCE = "angelone"` in `config.py` when keys arrive

### Phase 3 — Indicator Engine
- [x] Write `indicators.py` using `ta` library (NOT `pandas_ta` — abandoned, breaks on pandas 2.2+)
- [x] Write `pivot_points.py` — classic pivot point calculator (PP, R1, R2, R3, S1, S2, S3)
- [x] Write `test_phase3.py` — validates formulas, ranges, NaN safety, crossover logic
- [x] Update code snippets in Phase 3 section below (currently show `pandas_ta` syntax — wrong library)
- [x] Validate: MACD crossover fires only ONCE per cross event (tested by sliding window)
- [x] Validate: EMA uses `adjust=False` (Wilder's smoothing, not Excel EMA)
- [x] Validate: RSI uses Wilder's RMA smoothing (com=window-1 in ewm = matches TradingView)
- [x] **Run `test_phase3.py` — all checks pass**

### Phase 4 — Pre-filter Engine
- [x] Write `prefilter.py` — score stocks 0–5 (RSI + MACD + EMA trend + Volume + Pivot proximity)
- [x] Write `test_phase4.py`
- [x] Verify: both long and short directions scored independently per stock
- [x] Verify: stocks already in open positions are excluded from scoring
- [x] Verify: same stock not sent to Claude twice in the same 15-min candle window
- [x] **Run `test_phase4.py` — all checks pass** (18 candidates from affordable stocks)

### Phase 5 — Claude Reasoning Agent
- [x] Write `claude_agent.py` — prompt builder, API call, JSON response parser, retry logic
- [x] Write `test_phase5.py` — 18 tests covering all validation paths
- [x] Verify `ANTHROPIC_API_KEY` is set in `.env` and working (live call returned BUY, conviction=6, R:R=1.5)
- [x] Verify parse error fallback returns `HOLD` (never crashes the bot)
- [x] Verify R:R validation catches Claude arithmetic errors independently
- [x] Verify `max_tokens=512` keeps cost low (~₹0.25/call)
- [x] **Run `test_phase5.py` — all 18 checks pass**

### Phase 6 — Transaction Cost Engine
- [x] Write `transaction_costs.py` — STT, NSE exchange fee, SEBI charges, stamp duty, GST
- [x] Write `test_phase6.py`
- [x] Cross-check reference trade: RELIANCE 7 shares Rs1290->Rs1310 = Rs4.31 charges, Rs135.69 net
- [x] Verify: STT on sell side only, stamp duty on buy side only
- [x] Verify: GST applied only on exchange fee + SEBI (brokerage = Rs0)
- [x] **Run `test_phase6.py` — all 17 checks pass**

### Phase 7 — Risk Manager
- [x] Write `risk_manager.py` — daily loss cap, per-trade risk, position sizing, time rules, R:R check
- [x] Write `test_phase7.py` — mocked datetimes to test time-based rules
- [x] Verify: daily loss limit stops all new entries (not just rejects individual trades)
- [x] Verify: position sizing never results in cost > available capital
- [x] Verify: 3:00 PM cutoff blocks new entries (tested 14:59 vs 15:00 vs 15:05)
- [x] Fix: reset_daily() also resets open_count to 0 (all positions force-closed at 3:15 PM daily)
- [x] **Run `test_phase7.py` — all 12 checks pass**

### Phase 8 — Paper Trading Engine
- [x] Write `paper_trader.py` — virtual portfolio, cash tracking, SL/target/EOD exit logic, slippage
- [x] Write `test_phase8.py`
- [x] Verify: SL exit uses SL price (not candle close price)
- [x] Verify: for BUY positions, check candle LOW vs SL; for SELL check candle HIGH
- [x] Verify: slippage applied on both entry AND exit (0.05% per leg)
- [x] Verify: EOD forced close fires at 3:15 PM for all open positions
- [x] Verify: cash balance arithmetic correct (initial + net_pnl = final cash)
- [x] Verify: SL takes priority over target on same candle (conservative)
- [x] **Run `test_phase8.py` — all 15 checks pass**

### Phase 9 — Main Orchestration Loop
- [x] Write `scheduler.py` — market hours check, candle close detection, NSE holiday check
- [x] Write `main.py` — full loop wiring all components together
- [x] Write `test_phase9.py` — end-to-end simulated run with mocked Claude
- [x] Verify: first entry only after 9:30 AM (skip 9:15 candle — 25 candles/day confirmed)
- [x] Verify: EOD blocks new entries at 3:30 PM
- [x] Verify: daily loss cap blocks all entries in process_candle()
- [x] Verify: NSE holidays and weekends correctly excluded
- [x] **Run `test_phase9.py` — all 9 checks pass**

### Phase 10 — Logging & Performance Tracking
- [x] Write `db.py` — SQLite schema (`trades` + `daily_summary` tables), insert/query/summary helpers
- [x] Write `test_phase10.py`
- [x] Verify: `daily_summary.net_pnl` matches `SUM(trades.net_pnl)` for that date
- [x] Verify: INSERT OR REPLACE prevents duplicate daily summary rows
- [x] Verify: `get_performance_summary()` correctly aggregates win rate, avg win/loss, best/worst
- [x] Fix: Windows file lock on test DB cleanup handled with try/except PermissionError
- [x] **Run `test_phase10.py` — all 12 checks pass**

### Phase 11 — Paper Trading Run (4 Weeks)
- [ ] Run bot on live yfinance feed every trading day for 4 weeks
- [ ] Week 1 review: check win rate, avg R:R, any crashes or unexpected exits
- [ ] Week 2 review: tune pre-filter thresholds if Claude HOLD rate < 80% or > 95%
- [ ] Week 3 review: evaluate if daily loss limit triggers too often (reduce risk if >3 times)
- [ ] Week 4 review + go/no-go decision (see metrics table in Phase 11 section below)
- [ ] Fix all bugs found during live paper run before going live

### Phase 12 — Live Trading Migration
- [ ] Switch `DATA_SOURCE = "angelone"` in `config.py`
- [ ] Implement all 4 methods in `angelone_feed.py` (historical, daily OHLC, WebSocket, last price)
- [ ] Add live order placement in `paper_trader.py` (or separate `live_trader.py`)
- [ ] Add order confirmation polling via `getOrderBook()` after every placed order
- [ ] Add duplicate order prevention (track placed order IDs across reconnects)
- [ ] Add `EMERGENCY_STOP=false` flag to `.env` — set to `true` to halt all orders instantly
- [ ] Add 20% portfolio drawdown hard shutdown (portfolio < ₹8,000 → bot stops, requires manual restart)
- [ ] Start live with ₹5,000 (half capital) for first 2 weeks
- [ ] Verify live fills match expected prices (compare to paper fill prices same day)

---

### Known Issues & Tech Debt
- [ ] **`indicators.py` code snippets in this document use `pandas_ta` syntax** — must use `ta` library instead when coding Phase 3
- [ ] **Circuit filter check missing** — before scoring a stock, check it's not at upper/lower circuit (see Appendix C)
- [ ] **NSE holidays 2026** — dates marked "(verify)" in `config.py` need confirmation against official NSE calendar
- [ ] **Nifty 50 composition** — verify current index members at nseindia.com before first live run
- [ ] **Earnings calendar** — Claude has no knowledge of earnings dates; stocks on earnings day have erratic moves. Add a note to the Claude prompt if stock has results that day (future enhancement)
- [ ] **`angelone_feed.py` rate limiting** — add `time.sleep(0.35)` between historical data calls at startup (50 stocks ÷ 3 calls/sec = ~17s minimum)

---

## Critical Design Decisions (Read First)

Before touching code, understand these constraints — they affect every phase:

| Constraint | Impact |
|---|---|
| Angel One JWT token expires every 24h | Must re-authenticate every morning before market open |
| ₹10k capital + no fractional shares | Many Nifty 50 stocks are unaffordable. Filter at runtime. |
| EMA 200 needs 200 × 15-min bars = 8+ trading days | Pre-load 10 days of historical data at startup |
| MACD needs 26+9 = 35 bars minimum | First ~2 hours of data after startup will have invalid MACD |
| Angel One has NO paper trading sandbox | We fully simulate paper trading in code |
| Claude API: 1–5s latency per call | Never block the candle loop on Claude. Call is synchronous but must complete before next candle trigger |
| 9:15–9:30 first candle is gap-driven and unreliable | Skip first candle for new entries |
| NSE auto-square-off at ~3:20 PM | Bot must close all positions by 3:15 PM IST hard deadline |
| Stocks hitting circuit filters can't be traded | Check for circuit limit hits before sending to Claude |

---

## Project Structure

```
trading_bot/
├── .env                        # API keys — NEVER commit this
├── config.py                   # All constants, stock list, thresholds
├── auth.py                     # Angel One login, token management, TOTP
├── data_feed.py                # Historical + live WebSocket data
├── candle_store.py             # In-memory candle buffer per symbol
├── indicators.py               # All TA calculations with validation
├── pivot_points.py             # Classic pivot point calculator
├── prefilter.py                # Signal scoring before Claude call
├── claude_agent.py             # Claude API prompt + response parser
├── risk_manager.py             # All risk rules enforcement
├── transaction_costs.py        # Exact Indian regulatory fee calculations
├── paper_trader.py             # Virtual portfolio and order simulation
├── position_manager.py         # Track open positions, SL/target monitoring
├── logger.py                   # Terminal output + SQLite persistence
├── db.py                       # SQLite schema and queries
├── scheduler.py                # Market hours detection, candle timing
├── main.py                     # Orchestration loop
└── requirements.txt
```

---

## Phase 1 — Environment & Authentication

**Goal:** Python environment runs. Angel One auth works. Tokens refresh automatically.

### 1.1 Dependencies

```
# requirements.txt
smartapi-python==1.3.4      # Angel One official SDK
pandas==2.1.4
ta>=0.11.0                  # TA indicators (Python 3.14 compatible, actively maintained)
anthropic==0.26.0           # Claude API
pyotp==2.9.0                # TOTP for Angel One login
python-dotenv==1.0.0
schedule==1.2.1             # Candle loop timing
websocket-client==1.7.0     # Angel One WebSocket
requests==2.31.0
```

**Critical:** Do NOT use `ta-lib` — it requires binary compilation and will fail on Windows without manual setup. `pandas-ta` is pure Python and covers all required indicators.

### 1.2 `.env` file

```env
ANGEL_ONE_API_KEY=your_api_key
ANGEL_ONE_CLIENT_ID=your_client_id
ANGEL_ONE_PASSWORD=your_mpin
ANGEL_ONE_TOTP_SECRET=your_totp_secret_base32
ANTHROPIC_API_KEY=sk-ant-...
```

**Critical:** `ANGEL_ONE_TOTP_SECRET` is the base32 secret from your authenticator app (not the 6-digit code). This is what `pyotp.TOTP(secret).now()` uses to generate the current 6-digit code programmatically.

### 1.3 `auth.py` — Token Management

```
auth.py responsibilities:
  - login()          → POST to Angel One, store JWT access token + feed token
  - get_token()      → Return current valid token
  - refresh_token()  → Called at 9:00 AM IST daily before market open
  - is_token_valid() → Check token expiry (compare to stored timestamp)
```

**Critical edge cases:**
- Token expiry is 24h from login time, NOT from midnight. Login at 9:00 AM → token valid until 9:00 AM next day. Safe for market hours (9:15–3:30 PM).
- TOTP codes are time-sensitive (30-second windows). If system clock drifts >30s, login will fail. Add NTP sync check.
- Angel One returns HTTP 200 even on auth failure — check `data['status']` field, not HTTP status.

### 1.4 Acceptance Criteria for Phase 1
- [ ] `python auth.py` logs in successfully and prints `{"status": "SUCCESS"}`
- [ ] Token stored in memory (not to disk — security risk)
- [ ] Re-login at 9:00 AM scheduled

---

## Phase 2 — Market Data Layer

**Goal:** Reliable OHLCV data — historical (for seeding indicators) and live (for signals).

### 2.1 Nifty 50 Symbol List + Token Mapping

Angel One's API does NOT use ticker symbols like "RELIANCE". It uses numeric **instrument tokens** (e.g., RELIANCE NSE token = 2885). You need a token-to-symbol mapping file.

```python
# config.py
NIFTY_50_TOKENS = {
    "RELIANCE":   {"token": "2885",  "exchange": "NSE"},
    "INFY":       {"token": "1594",  "exchange": "NSE"},
    "TCS":        {"token": "11536", "exchange": "NSE"},
    # ... all 50 stocks with tokens
    # Tokens are in Angel One's instrument master file
    # Download from: https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json
    # Update monthly — composition and tokens can change
}
```

**Critical:** Download the instrument master file (`OpenAPIScripMaster.json`) from Angel One. Tokens occasionally change when stocks get relisted or corporate actions happen. Re-download monthly.

### 2.2 Historical Data Fetcher

```
data_feed.py → fetch_historical(symbol_token, interval="FIFTEEN_MINUTE", days=10)

Angel One getCandleData parameters:
  exchange:    "NSE"
  symboltoken: "2885"
  interval:    "FIFTEEN_MINUTE"
  fromdate:    "YYYY-MM-DD HH:MM"
  todate:      "YYYY-MM-DD HH:MM"

Returns: [timestamp, open, high, low, close, volume]
```

**Critical issues:**
1. **Rate limiting:** Angel One allows ~3 API calls/second. With 50 stocks at startup, fetching all 50 historical series will take ~17 seconds minimum. Add `time.sleep(0.35)` between calls or batch with rate limiter.
2. **Date format:** Angel One expects `"2026-03-15 09:15"` format. Timezone is IST (UTC+5:30). Use `pytz` for all datetime operations — never use naive datetimes.
3. **Market holidays:** Angel One returns empty data for holidays. Detect this (empty candle list) and skip to next trading day.
4. **Max lookback:** Angel One historical data API supports up to 60 days for 15-min interval. 10 days is well within limit.
5. **Pre-market candle exclusion:** Angel One sometimes includes a 9:00–9:15 pre-open candle. Filter out candles where `timestamp.hour == 9 and timestamp.minute < 15`.

### 2.3 Stock Price Filter

At startup, after fetching historical data, filter the stock universe:

```python
# Only trade stocks where current price ≤ ₹2,000
# (20% of ₹10,000 capital — can afford at least 1 share with ₹2k)
def get_tradeable_stocks(all_stocks, capital):
    tradeable = []
    for stock in all_stocks:
        last_price = get_last_close(stock)
        max_affordable_price = capital * 0.20   # ₹2,000 at ₹10k capital
        if last_price <= max_affordable_price:
            tradeable.append(stock)
    return tradeable
```

**Critical:** This filter runs at startup and is re-evaluated daily. As paper P&L changes, available capital changes, which changes the affordable universe.

**Expected outcome at ₹10k:** Roughly 15–25 of the 50 Nifty stocks will be affordable. HDFC Bank (~₹1,700), ITC (~₹450), NTPC (~₹350), Coal India (~₹400), ONGC (~₹270), Tata Steel (~₹150) will qualify. Maruti, MRF, Eicher, Bajaj Auto will NOT qualify.

### 2.4 Live WebSocket Data

Angel One provides a WebSocket for real-time tick data. We aggregate ticks into 15-minute OHLCV bars.

```
data_feed.py → WebSocket handler:
  on_message(tick):
    - Extract: token, LTP (last traded price), volume
    - Route to candle_store.update(token, ltp, volume, timestamp)

candle_store.py:
  - Per-symbol buffer: current candle (open, high, low, close, volume)
  - on_candle_close(timestamp): finalize candle, append to history, trigger indicator recalc
  - Candle close detection: when current minute crosses 15-min boundary
    e.g., 9:30:00 → finalize 9:15 candle
```

**Critical edge cases:**
1. **WebSocket disconnect:** Angel One WebSocket drops connections. Implement auto-reconnect with exponential backoff (1s → 2s → 4s → max 30s). On reconnect, fetch missed candles via REST API.
2. **Tick gaps:** If no tick arrives for a stock in a candle period, repeat last close as OHLC (common for illiquid periods). Volume = 0.
3. **Subscription limit:** Angel One WebSocket allows subscribing to up to 50 tokens simultaneously. Nifty 50 is exactly at the limit. Stay within it.
4. **First candle (9:15–9:30):** Contains gap-open price, often erratic. Store this candle but **do not generate new entries on it**. Use it only for indicator seeding.

### 2.5 Acceptance Criteria for Phase 2
- [ ] Historical data loads for all 50 stocks without errors
- [ ] Price filter correctly reduces universe (verify by printing filtered list)
- [ ] WebSocket receives live ticks (test with 1 stock first)
- [ ] 15-min candle correctly closes and triggers at right timestamps
- [ ] Reconnect works after manually killing WebSocket connection

---

## Phase 3 — Indicator Engine

**Goal:** All four indicator categories calculated correctly, with explicit validation of minimum candle requirements.

### 3.1 Data Prerequisites (Critical)

| Indicator | Minimum Candles Required | Calculation Note |
|---|---|---|
| RSI(14) | 15 candles | 14 periods + 1 for first delta |
| EMA 20 | 20 candles | |
| EMA 50 | 50 candles | |
| EMA 200 | 200 candles | 10 days × ~25 bars/day = 250. Pre-load covers this. |
| MACD(12,26,9) | 35 candles | EMA26 needs 26 bars; signal EMA9 needs 9 more |
| Volume SMA 20 | 20 candles | |
| Pivot Points | Previous day OHLC | Only requires 1 daily candle from yesterday |

At startup with 10 days of history (~250 bars), **all** indicators are valid from bar 1 of the live session.

### 3.2 `indicators.py` — Calculations

> ⚠️ **NOTE:** The code below uses `pandas_ta` syntax for illustration. The actual `indicators.py` file will use the `ta` library (`import ta`) — see Phase 3 TODO in the tracker above. `pandas_ta` is abandoned and incompatible with Python 3.14 / pandas 2.2+.

```python
import pandas as pd
import pandas_ta as ta   # DO NOT USE — replace with: import ta

def calculate_indicators(df: pd.DataFrame) -> dict:
    """
    df must have columns: open, high, low, close, volume
    df index: DatetimeIndex (IST timezone-aware)
    Returns dict of indicator values for the LATEST candle only
    """
    # Validate minimum length
    if len(df) < 200:
        raise ValueError(f"Need 200 candles minimum, have {len(df)}")

    # RSI(14)
    rsi = ta.rsi(df['close'], length=14)
    rsi_current = rsi.iloc[-1]
    rsi_prev = rsi.iloc[-2]

    # EMAs
    ema20  = ta.ema(df['close'], length=20).iloc[-1]
    ema50  = ta.ema(df['close'], length=50).iloc[-1]
    ema200 = ta.ema(df['close'], length=200).iloc[-1]

    # MACD(12, 26, 9)
    macd_df = ta.macd(df['close'], fast=12, slow=26, signal=9)
    macd_line    = macd_df['MACD_12_26_9'].iloc[-1]
    signal_line  = macd_df['MACDs_12_26_9'].iloc[-1]
    macd_prev    = macd_df['MACD_12_26_9'].iloc[-2]
    signal_prev  = macd_df['MACDs_12_26_9'].iloc[-2]

    macd_bullish_cross = (macd_prev < signal_prev) and (macd_line > signal_line)
    macd_bearish_cross = (macd_prev > signal_prev) and (macd_line < signal_line)

    # Volume analysis
    vol_sma20 = ta.sma(df['volume'], length=20).iloc[-1]
    vol_current = df['volume'].iloc[-1]
    vol_ratio = vol_current / vol_sma20 if vol_sma20 > 0 else 1.0

    return {
        "price":              df['close'].iloc[-1],
        "rsi":                round(rsi_current, 2),
        "rsi_prev":           round(rsi_prev, 2),
        "ema20":              round(ema20, 2),
        "ema50":              round(ema50, 2),
        "ema200":             round(ema200, 2),
        "macd_line":          round(macd_line, 4),
        "signal_line":        round(signal_line, 4),
        "macd_bullish_cross": macd_bullish_cross,
        "macd_bearish_cross": macd_bearish_cross,
        "volume":             int(vol_current),
        "volume_sma20":       int(vol_sma20),
        "volume_ratio":       round(vol_ratio, 2),
    }
```

**Critical RSI note:** `pandas-ta` uses Wilder's smoothing (RMA), which matches TradingView's RSI. If you compare to a different platform that uses simple average for RSI, values will differ slightly. Wilder's is the standard.

**Critical MACD note:** Crossover detection uses the prior candle (`iloc[-2]`) vs current candle (`iloc[-1]`). A crossover must be **fresh** (happened in the last candle), not an ongoing state. Otherwise, the bot will repeatedly signal on the same old crossover.

**Critical EMA note:** `pandas-ta` uses `adjust=False` for EMA, which is Wilder's exponential smoothing (correct for trading). Do not set `adjust=True` (that's the Excel-style EMA — different values).

### 3.3 `pivot_points.py` — Classic Pivot Points

Pivot points are **daily levels** computed from the previous day's OHLC. They reset every trading day.

```python
def calculate_pivot_points(prev_high: float, prev_low: float, prev_close: float) -> dict:
    pp = (prev_high + prev_low + prev_close) / 3
    r1 = (2 * pp) - prev_low
    r2 = pp + (prev_high - prev_low)
    r3 = prev_high + 2 * (pp - prev_low)
    s1 = (2 * pp) - prev_high
    s2 = pp - (prev_high - prev_low)
    s3 = prev_low - 2 * (prev_high - pp)
    return {"PP": pp, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3}

def get_nearest_levels(price: float, pivots: dict) -> dict:
    """Find the nearest support below and resistance above current price"""
    levels = sorted(pivots.values())
    support    = max([l for l in levels if l < price], default=None)
    resistance = min([l for l in levels if l > price], default=None)

    support_dist_pct    = ((price - support) / price * 100) if support else None
    resistance_dist_pct = ((resistance - price) / price * 100) if resistance else None

    return {
        "nearest_support":        round(support, 2) if support else None,
        "nearest_resistance":     round(resistance, 2) if resistance else None,
        "support_dist_pct":       round(support_dist_pct, 2) if support_dist_pct else None,
        "resistance_dist_pct":    round(resistance_dist_pct, 2) if resistance_dist_pct else None,
    }
```

**How to get previous day's OHLC:**
At 9:00 AM each morning, fetch one daily candle from yesterday:
```
getCandleData(symboltoken, interval="ONE_DAY", fromdate=yesterday, todate=yesterday)
```

**Critical:** If today is Monday, "yesterday" is Friday (not Sunday). Your date arithmetic must skip weekends and NSE holidays.

### 3.4 Acceptance Criteria for Phase 3
- [ ] All indicator values match TradingView for the same stock/timeframe (manual spot check on 3 stocks)
- [ ] Bot prints clear error when candle count is insufficient (not silently computes NaN)
- [ ] Pivot points reset correctly at 9:15 AM each new day
- [ ] MACD crossover detection only fires once per cross event (not repeatedly)

---

## Phase 4 — Pre-filter Engine

**Goal:** Reduce Claude API calls from potential 1,250/day to 5–15/day without missing real setups.

### 4.1 Signal Scoring Logic

Each stock gets a score of 0–5 per candle. Only stocks with score ≥ 2 are sent to Claude.

```python
def score_stock(indicators: dict, pivots: dict, direction: str) -> int:
    """
    direction: "long" or "short"
    Returns score 0-5
    """
    score = 0
    price = indicators['price']

    if direction == "long":
        # 1. RSI: oversold OR recovering from oversold
        if indicators['rsi'] < 35:
            score += 1
        elif indicators['rsi_prev'] < 30 and indicators['rsi'] > 30:
            score += 1   # RSI recovering from oversold — stronger signal

        # 2. MACD: fresh bullish crossover
        if indicators['macd_bullish_cross']:
            score += 1

        # 3. EMA trend: price above EMA20, EMA20 above EMA50 (short-term bullish)
        if price > indicators['ema20'] > indicators['ema50']:
            score += 1

        # 4. Volume confirmation
        if indicators['volume_ratio'] >= 1.5:
            score += 1

        # 5. Price near pivot support (within 0.75%)
        if (pivots['nearest_support'] and pivots['support_dist_pct'] is not None
                and pivots['support_dist_pct'] <= 0.75):
            score += 1

    elif direction == "short":
        if indicators['rsi'] > 65:
            score += 1
        elif indicators['rsi_prev'] > 70 and indicators['rsi'] < 70:
            score += 1

        if indicators['macd_bearish_cross']:
            score += 1

        if price < indicators['ema20'] < indicators['ema50']:
            score += 1

        if indicators['volume_ratio'] >= 1.5:
            score += 1

        if (pivots['nearest_resistance'] and pivots['resistance_dist_pct'] is not None
                and pivots['resistance_dist_pct'] <= 0.75):
            score += 1

    return score
```

**Critical design notes:**

1. **Both directions scored independently.** A stock can score 3 for long and 1 for short simultaneously. Only the higher-scoring direction is passed to Claude.

2. **Avoid re-signaling.** Track which stocks were already sent to Claude in the **current candle interval**. Do not send the same stock twice in 15 minutes even if it rescores.

3. **Avoid re-entering a position.** If a position is already open in RELIANCE, do not score RELIANCE again until the position is closed.

4. **RSI values near 50 are noise.** The thresholds (35/65) are intentionally not the textbook 30/70 — at 30/70, RSI signals are lagging and price has often already moved. 35/65 gives slightly earlier signals.

5. **EMA 200 is NOT used as a filter in scoring** — it's provided to Claude as broader trend context. EMA 200 is too slow to generate intraday signals on 15-min bars but gives Claude important structural context.

### 4.2 Acceptance Criteria for Phase 4
- [ ] In backtesting on 1 week of historical data, filter reduces candidates from ~1,200 to under 50 per day
- [ ] No stock with score < 2 ever reaches Claude
- [ ] Re-entry prevention works correctly

---

## Phase 5 — Claude Reasoning Agent

**Goal:** Claude receives structured context and returns a deterministic, parseable trading decision.

### 5.1 Prompt Design

The prompt must be:
- **Structured** — Claude must output valid JSON, not prose
- **Bounded** — Claude cannot invent data not provided (no hallucinating price history)
- **Self-consistent** — Claude must explain its reasoning in the `reasoning` field

```python
SYSTEM_PROMPT = """
You are an intraday trading analysis agent for NSE (India) equities.
You analyze 15-minute candle data and technical indicators for Nifty 50 stocks.
Market hours: 9:15 AM to 3:30 PM IST. All positions must close by 3:15 PM.
Capital is limited. You are conservative — avoid low-conviction trades.

Respond ONLY with valid JSON matching this schema:
{
  "decision": "BUY" | "SELL" | "HOLD",
  "conviction": 1-10,
  "entry_price": float | null,
  "stop_loss": float | null,
  "target": float | null,
  "reasoning": "string (max 150 words)"
}

Rules:
- If decision is HOLD, entry_price/stop_loss/target must be null
- stop_loss must be set such that max loss ≤ stated risk_per_trade
- target must give risk:reward ≥ 1.5 (target gain ≥ 1.5x stop loss distance)
- conviction < 6 → return HOLD regardless
- If time is after 3:00 PM IST, return HOLD (too close to close)
"""

def build_user_prompt(symbol, indicators, pivots, available_capital, risk_per_trade, current_time):
    return f"""
Stock: {symbol} | NSE | 15-min chart
Current time: {current_time} IST
Current price: ₹{indicators['price']}

--- TREND ---
EMA 20:  ₹{indicators['ema20']}   (short-term trend)
EMA 50:  ₹{indicators['ema50']}   (medium-term trend)
EMA 200: ₹{indicators['ema200']}  (long-term structural trend)
Price vs EMA20: {"ABOVE" if indicators['price'] > indicators['ema20'] else "BELOW"}
EMA20 vs EMA50: {"ABOVE (bullish)" if indicators['ema20'] > indicators['ema50'] else "BELOW (bearish)"}

--- MOMENTUM ---
RSI(14): {indicators['rsi']} (prev candle: {indicators['rsi_prev']})
MACD line: {indicators['macd_line']} | Signal line: {indicators['signal_line']}
MACD crossover this candle: {"Bullish cross" if indicators['macd_bullish_cross'] else "Bearish cross" if indicators['macd_bearish_cross'] else "No cross"}

--- VOLUME ---
Current candle volume: {indicators['volume']:,}
20-period avg volume:  {indicators['volume_sma20']:,}
Volume ratio: {indicators['volume_ratio']}x average

--- SUPPORT & RESISTANCE (Classic Pivot Points) ---
R2: ₹{pivots.get('R2')} | R1: ₹{pivots.get('R1')} | PP: ₹{pivots.get('PP')}
S1: ₹{pivots.get('S1')} | S2: ₹{pivots.get('S2')}
Nearest support: ₹{pivots.get('nearest_support')} ({pivots.get('support_dist_pct')}% below price)
Nearest resistance: ₹{pivots.get('nearest_resistance')} ({pivots.get('resistance_dist_pct')}% above price)

--- RISK PARAMETERS ---
Available capital: ₹{available_capital}
Max risk this trade: ₹{risk_per_trade}
"""
```

### 5.2 Response Parsing

```python
import json, re

def parse_claude_response(response_text: str) -> dict:
    # Extract JSON from response (Claude sometimes adds surrounding text)
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if not json_match:
        raise ValueError("No JSON found in Claude response")

    data = json.loads(json_match.group())

    # Validate required fields
    assert data['decision'] in ('BUY', 'SELL', 'HOLD')
    assert 1 <= data['conviction'] <= 10

    if data['decision'] != 'HOLD':
        assert data['entry_price'] is not None
        assert data['stop_loss'] is not None
        assert data['target'] is not None

        # Validate R:R ratio
        if data['decision'] == 'BUY':
            risk   = data['entry_price'] - data['stop_loss']
            reward = data['target'] - data['entry_price']
        else:  # SELL
            risk   = data['stop_loss'] - data['entry_price']
            reward = data['entry_price'] - data['target']

        assert risk > 0, "Stop loss on wrong side of entry"
        assert reward / risk >= 1.4, f"R:R ratio {reward/risk:.2f} below minimum 1.4"

    return data
```

**Critical:** Never trust Claude's arithmetic blindly. Always re-validate stop loss and target prices server-side. Claude can occasionally compute R:R incorrectly. The risk manager (Phase 7) is a second validation layer.

### 5.3 Claude API Call with Retry

```python
import anthropic, time

client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env

def ask_claude(symbol, prompt_context, max_retries=3) -> dict:
    for attempt in range(max_retries):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,    # Decision JSON is small; limit output tokens = lower cost
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt_context}]
            )
            return parse_claude_response(message.content[0].text)

        except anthropic.RateLimitError:
            time.sleep(60)    # Wait 60s on rate limit
        except (json.JSONDecodeError, AssertionError, ValueError) as e:
            if attempt == max_retries - 1:
                print(f"[CLAUDE PARSE ERROR] {symbol}: {e} — defaulting to HOLD")
                return {"decision": "HOLD", "conviction": 0, "reasoning": f"Parse error: {e}"}
            time.sleep(2)

    return {"decision": "HOLD", "conviction": 0, "reasoning": "Max retries exceeded"}
```

**Cost estimation:**
- Input tokens per call: ~350 tokens (prompt)
- Output tokens per call: ~150 tokens (JSON + reasoning)
- Total: ~500 tokens per call
- claude-sonnet-4-6 pricing: ~$0.003 per 1K input tokens, ~$0.015 per 1K output tokens
- Cost per call: ~$0.001 + $0.002 = ~$0.003 (~₹0.25)
- At 15 calls/day: ~₹3.75/day → ~₹75/month. Negligible.

### 5.4 Acceptance Criteria for Phase 5
- [ ] Claude returns valid JSON 100% of the time across 20 test prompts
- [ ] Parse error fallback correctly returns HOLD (never crashes)
- [ ] R:R validation catches at least 1 incorrect Claude response in testing

---

## Phase 6 — Transaction Cost Engine

**Goal:** Accurate P&L simulation that matches what you'd see in a real Angel One statement.

### 6.1 Indian Equity Intraday Cost Breakdown

For **intraday equity (MIS)** on NSE via Angel One (as of 2026):

| Charge | Rate | Applied On | Notes |
|---|---|---|---|
| Brokerage | ₹0 | — | Angel One is zero-commission for equity |
| STT | 0.025% | Sell turnover only | Securities Transaction Tax |
| Exchange fee (NSE) | 0.00297% | Both sides (buy + sell) | NSE transaction charge |
| SEBI charges | 0.0001% | Total turnover | Very small |
| Stamp duty | 0.015% | Buy turnover only | State government levy |
| GST | 18% | On (brokerage + exchange fee + SEBI) | Since brokerage=₹0, only on exchange+SEBI |
| DP charges | ₹0 | — | No delivery, no DP charge for intraday |

```python
def calculate_transaction_costs(entry_price: float, exit_price: float,
                                 quantity: int, direction: str) -> dict:
    buy_price  = entry_price if direction == "BUY" else exit_price
    sell_price = exit_price  if direction == "BUY" else entry_price

    buy_turnover  = buy_price  * quantity
    sell_turnover = sell_price * quantity
    total_turnover = buy_turnover + sell_turnover

    brokerage     = 0.0
    stt           = sell_turnover * 0.00025           # 0.025% on sell
    exchange_fee  = total_turnover * 0.0000297        # 0.00297% both sides
    sebi_charges  = total_turnover * 0.000001         # 0.0001%
    stamp_duty    = buy_turnover  * 0.00015           # 0.015% on buy
    gst           = (brokerage + exchange_fee + sebi_charges) * 0.18

    total_cost = stt + exchange_fee + sebi_charges + stamp_duty + gst

    return {
        "stt":          round(stt, 4),
        "exchange_fee": round(exchange_fee, 4),
        "sebi_charges": round(sebi_charges, 4),
        "stamp_duty":   round(stamp_duty, 4),
        "gst":          round(gst, 4),
        "total_cost":   round(total_cost, 4),
    }
```

**Example for ₹500 stock, 20 shares, round trip:**
- Buy: ₹500 × 20 = ₹10,000 | Sell: ₹510 × 20 = ₹10,200 (assuming 2% profit)
- STT: ₹10,200 × 0.025% = ₹2.55
- Exchange fee: ₹20,200 × 0.00297% = ₹0.60
- SEBI: ₹20,200 × 0.0001% = ₹0.02
- Stamp duty: ₹10,000 × 0.015% = ₹1.50
- GST: (₹0 + ₹0.60 + ₹0.02) × 18% = ₹0.11
- **Total: ₹4.78 on a ₹200 gross profit = 2.4% of profit eaten by fees**

This is why accurate cost simulation matters: a "profitable" trade can be marginally unprofitable after costs at small capital.

### 6.2 Acceptance Criteria for Phase 6
- [ ] Cross-check one trade's fees against Angel One's brokerage calculator (angelbroking.com/brokerage-calculator)
- [ ] Verify: STT applies only to sell side, stamp duty only to buy side

---

## Phase 7 — Risk Manager

**Goal:** No trade executes that violates capital protection rules. This layer is non-negotiable.

### 7.1 Risk Rules

```python
class RiskManager:
    MAX_DAILY_LOSS_PCT    = 0.03    # 3% of starting capital = ₹300
    RISK_PER_TRADE_PCT    = 0.02    # 2% of available capital per trade
    MAX_OPEN_POSITIONS    = 2       # Hard cap
    NO_NEW_ENTRIES_AFTER  = time(15, 0, 0)   # 3:00 PM IST
    MIN_RISK_REWARD       = 1.5     # Target must be 1.5x the risk
    MAX_POSITION_SIZE_PCT = 0.50    # No single position > 50% of capital
```

### 7.2 Pre-Trade Validation

```python
def validate_trade(self, decision: dict, current_capital: float,
                   daily_loss: float, open_positions: int,
                   current_time: time) -> tuple[bool, str]:

    # Rule 1: Daily loss limit
    if daily_loss >= self.MAX_DAILY_LOSS_PCT * self.starting_capital:
        return False, f"Daily loss limit hit: ₹{daily_loss:.2f}"

    # Rule 2: Time restriction
    if current_time >= self.NO_NEW_ENTRIES_AFTER:
        return False, "No new entries after 3:00 PM IST"

    # Rule 3: Max open positions
    if open_positions >= self.MAX_OPEN_POSITIONS:
        return False, f"Max positions ({self.MAX_OPEN_POSITIONS}) already open"

    # Rule 4: Capital sufficiency
    entry = decision['entry_price']
    sl    = decision['stop_loss']
    sl_distance = abs(entry - sl)
    risk_amount = current_capital * self.RISK_PER_TRADE_PCT
    quantity    = int(risk_amount / sl_distance)

    if quantity < 1:
        return False, f"SL distance ₹{sl_distance:.2f} too wide for risk budget ₹{risk_amount:.2f}"

    position_cost = quantity * entry
    if position_cost > current_capital * self.MAX_POSITION_SIZE_PCT:
        quantity = int((current_capital * self.MAX_POSITION_SIZE_PCT) / entry)
        if quantity < 1:
            return False, "Stock too expensive relative to capital"

    # Rule 5: R:R validation (re-check Claude's math)
    if decision['decision'] == 'BUY':
        risk   = entry - sl
        reward = decision['target'] - entry
    else:
        risk   = sl - entry
        reward = entry - decision['target']

    if reward / risk < self.MIN_RISK_REWARD:
        return False, f"R:R ratio {reward/risk:.2f} below minimum {self.MIN_RISK_REWARD}"

    return True, "OK"
```

### 7.3 Position Sizing (Final Quantity)

```python
def calculate_quantity(self, entry: float, stop_loss: float,
                        available_capital: float) -> int:
    sl_distance = abs(entry - stop_loss)
    risk_budget = available_capital * self.RISK_PER_TRADE_PCT      # ₹200 at ₹10k

    qty_by_risk    = int(risk_budget / sl_distance)                 # Risk-based sizing
    qty_by_capital = int((available_capital * 0.50) / entry)       # Capital cap (50% max)

    quantity = min(qty_by_risk, qty_by_capital)
    return max(quantity, 0)    # Never negative
```

**Critical example:** HDFC Bank at ₹1,700, SL at ₹1,680 (₹20 distance):
- Risk-based: ₹200 / ₹20 = 10 shares = ₹17,000 → exceeds capital!
- Capital cap: ₹10,000 × 50% / ₹1,700 = 2 shares
- Final quantity: **2 shares**, cost ₹3,400, max loss = 2 × ₹20 = **₹40** (not ₹200)
- This is safe. The risk per trade is actually LOWER than target, which is acceptable.

### 7.4 Acceptance Criteria for Phase 7
- [ ] Daily loss limit correctly stops all trading when hit
- [ ] Time restriction blocks entries at 3:00 PM (test with mocked time)
- [ ] Position sizing never results in a position cost > available capital

---

## Phase 8 — Paper Trading Engine

**Goal:** Simulate trade execution with realistic market impact. All state persists in memory during the session.

### 8.1 Order Simulation

```python
SLIPPAGE_PCT = 0.0005    # 0.05% market impact — realistic for Nifty 50 liquid stocks

def simulate_fill(price: float, direction: str) -> float:
    """Returns simulated fill price with slippage"""
    if direction == "BUY":
        return round(price * (1 + SLIPPAGE_PCT), 2)    # Pay slightly more
    else:
        return round(price * (1 - SLIPPAGE_PCT), 2)    # Receive slightly less
```

**Why 0.05%?** Nifty 50 stocks have bid-ask spreads of ~0.02–0.1% on NSE. For a market order at market price during normal trading hours, 0.05% is a conservative estimate for mid-large caps. Do not use 0% — that overstates paper trading P&L.

### 8.2 Position State

```python
@dataclass
class Position:
    symbol:         str
    direction:      str       # "BUY" or "SELL"
    quantity:       int
    entry_price:    float     # After slippage
    stop_loss:      float     # Claude's SL
    target:         float     # Claude's target
    entry_time:     datetime
    claude_reasoning: str

    # Computed
    @property
    def unrealized_pnl(self, current_price: float) -> float:
        if self.direction == "BUY":
            return (current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - current_price) * self.quantity
```

### 8.3 Position Monitoring (Per Candle)

On each new 15-min candle close, check all open positions:

```python
def check_exits(position: Position, candle: dict) -> str | None:
    """
    Returns "SL_HIT", "TARGET_HIT", "EOD_CLOSE", or None
    candle: {open, high, low, close, timestamp}
    """
    # EOD close — must exit before 3:15 PM
    if candle['timestamp'].time() >= time(15, 15):
        return "EOD_CLOSE"

    if position.direction == "BUY":
        # On a candle, low is the worst-case price — SL checks against low
        if candle['low'] <= position.stop_loss:
            return "SL_HIT"
        if candle['high'] >= position.target:
            return "TARGET_HIT"
    else:
        # For short: high is worst-case
        if candle['high'] >= position.stop_loss:
            return "SL_HIT"
        if candle['low'] <= position.target:
            return "TARGET_HIT"

    return None
```

**Critical exit price logic:**
- `SL_HIT` → exit at `stop_loss` price (assume SL was triggered at exactly that price, plus slippage)
- `TARGET_HIT` → exit at `target` price (minus slippage for buy, plus for sell)
- `EOD_CLOSE` → exit at candle's `close` price (with slippage)
- **Do NOT use candle close for SL/target** — a candle can hit both SL and target in the same bar. Check low first for buy positions (worst case first).

### 8.4 Portfolio State

```python
@dataclass
class Portfolio:
    starting_capital: float = 10_000.0
    cash:             float = 10_000.0
    open_positions:   list  = field(default_factory=list)
    closed_trades:    list  = field(default_factory=list)

    @property
    def daily_pnl(self) -> float:
        return sum(t['net_pnl'] for t in self.closed_trades if t['date'] == today)

    @property
    def total_equity(self) -> float:
        return self.cash + sum(p.unrealized_pnl for p in self.open_positions)
```

### 8.5 Acceptance Criteria for Phase 8
- [ ] SL hit correctly closes position at SL price (not candle close price)
- [ ] EOD close fires at 3:15 PM on all remaining positions
- [ ] Cash balance decreases on open, increases on close
- [ ] Slippage is applied on both open and close

---

## Phase 9 — Main Orchestration Loop

**Goal:** All components wired together. Bot runs autonomously during market hours.

### 9.1 Daily Startup Sequence

```
9:00 AM IST:
  1. re-login to Angel One (token refresh)
  2. Fetch previous day OHLC for all 50 stocks → calculate pivot points
  3. Fetch 10 days historical 15-min data for all 50 stocks (rate-limited)
  4. Calculate all indicators on historical data → validate all indicator series ready
  5. Filter tradeable stocks (price ≤ ₹2,000)
  6. Start WebSocket, subscribe to all tradeable tokens
  7. Reset daily loss counter, open positions list

9:15 AM IST:
  8. Market open — loop begins
  9. First candle (9:15–9:30): receive ticks, build candle, NO entries yet
```

### 9.2 Per-Candle Loop (Every 15 Minutes, 9:30 AM → 3:15 PM)

```
On each 15-minute candle close (9:30, 9:45, ..., 3:15):

FOR each open position:
  1. check_exits(position, new_candle)
  2. If exit triggered → paper_trader.close(position, reason, exit_price)
  3. Log closed trade

CHECK daily loss limit → if hit, skip to end of loop

IF current time >= 3:15 PM:
  → force-close remaining positions, stop loop

FOR each tradeable stock:
  4. Update candle_store with new candle
  5. Recalculate indicators
  6. Score long + short independently
  7. If max(long_score, short_score) >= 2 AND no open position in this stock:
       direction = "long" if long_score > short_score else "short"
       prompt = build_user_prompt(...)
       claude_decision = ask_claude(symbol, prompt)
       If decision != HOLD and conviction >= 6:
         valid, reason = risk_manager.validate_trade(...)
         If valid:
           quantity = risk_manager.calculate_quantity(...)
           paper_trader.open(symbol, direction, quantity, claude_decision)
           log_trade_entry(...)

8. Print loop summary to terminal
```

### 9.3 Market Hours Detection

```python
import pytz
from datetime import datetime, time

IST = pytz.timezone('Asia/Kolkata')

def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    market_open  = time(9, 15, 0)
    market_close = time(15, 30, 0)
    return market_open <= now.time() <= market_close

def is_candle_close_time() -> bool:
    """Returns True at exactly :15, :30, :45, :00 minutes"""
    now = datetime.now(IST)
    return now.second < 5 and now.minute % 15 == 0    # 5-second window
```

**Critical:** Use `pytz` timezone-aware datetimes throughout. Never use `datetime.now()` (naive, assumes local system timezone). Windows system timezone may not be IST.

### 9.4 Acceptance Criteria for Phase 9
- [ ] Bot starts, loads data, and prints `"Ready. Waiting for market open."` by 9:10 AM
- [ ] First entry only after 9:30 AM (second candle)
- [ ] Loop prints summary line every 15 minutes
- [ ] Ctrl+C gracefully closes all positions and prints final P&L

---

## Phase 10 — Logging & Performance Tracking

**Goal:** Every trade is logged. Daily summary gives enough data to evaluate the strategy.

### 10.1 SQLite Schema

```sql
CREATE TABLE trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,              -- YYYY-MM-DD
    symbol          TEXT NOT NULL,
    direction       TEXT NOT NULL,              -- BUY / SELL
    quantity        INTEGER NOT NULL,
    entry_price     REAL NOT NULL,
    exit_price      REAL NOT NULL,
    stop_loss       REAL NOT NULL,
    target          REAL NOT NULL,
    entry_time      TEXT NOT NULL,              -- ISO timestamp IST
    exit_time       TEXT NOT NULL,
    exit_reason     TEXT NOT NULL,              -- SL_HIT / TARGET_HIT / EOD_CLOSE
    gross_pnl       REAL NOT NULL,
    transaction_costs REAL NOT NULL,
    net_pnl         REAL NOT NULL,
    claude_conviction INTEGER NOT NULL,
    claude_reasoning TEXT,
    pre_filter_score INTEGER,
    rsi_at_entry    REAL,
    macd_cross      TEXT,
    volume_ratio    REAL
);

CREATE TABLE daily_summary (
    date            TEXT PRIMARY KEY,
    starting_capital REAL,
    ending_capital  REAL,
    total_trades    INTEGER,
    winning_trades  INTEGER,
    losing_trades   INTEGER,
    gross_pnl       REAL,
    total_costs     REAL,
    net_pnl         REAL,
    max_drawdown    REAL,
    win_rate        REAL,
    avg_rr_achieved REAL
);
```

### 10.2 Terminal Output Format

```
[09:30] CANDLE CLOSE — Scanning 23 stocks
[09:30] RELIANCE  | Long score: 3 | Short score: 1 → Sending to Claude
[09:30] CLAUDE    | RELIANCE → BUY @ ₹2,450 | SL: ₹2,435 | Target: ₹2,473 | Conviction: 7
[09:30] TRADE     | OPENED RELIANCE BUY × 13 shares @ ₹2,451.23 (slippage applied)
[09:30] RISK      | Cost: ₹195/trade | R:R: 1.51 | Daily loss used: ₹0/₹300
[09:45] CANDLE CLOSE — 1 open position
[09:45] POSITION  | RELIANCE +₹47.35 unrealized
[10:30] TRADE     | CLOSED RELIANCE TARGET_HIT @ ₹2,473 | Net P&L: +₹263.11 (after ₹4.88 fees)
──────────────────────────────────────────────────────
[15:15] EOD CLOSE — No open positions
[15:15] DAILY SUMMARY | Trades: 3 | Win: 2 | Loss: 1 | Net P&L: +₹347.22 | Capital: ₹10,347.22
```

### 10.3 Acceptance Criteria for Phase 10
- [ ] Every trade written to SQLite immediately on close (not batched)
- [ ] Daily summary printed and written at 3:30 PM
- [ ] P&L in daily_summary matches sum of trades table for that date

---

## Phase 11 — Paper Trading Run & Validation (4 Weeks)

**Goal:** Validate that the bot works correctly and the strategy has positive expectancy before risking real money.

### 11.1 Minimum Paper Trading Duration

**Do not go live before completing 4 weeks (20 trading days) of paper trading.**

Reasons:
- Need statistical significance: aim for at least 40+ trades before judging the strategy
- Edge cases only appear in real market conditions (gap-ups, circuit hits, illiquid periods)
- 1–2 weeks is not enough — you need to see the strategy across different market regimes (trending, ranging, volatile)

### 11.2 Key Metrics to Track Weekly

| Metric | Acceptable for Going Live |
|---|---|
| Win rate | ≥ 45% (with 1.5:1 R:R, breakeven is 40%) |
| Average R:R achieved | ≥ 1.2 (accounting for real exits vs targets) |
| Max single-day loss | Never exceeds ₹300 daily limit |
| Cost drag | Total fees < 15% of gross profit |
| Claude HOLD rate | 80–90% HOLD expected (healthy) |
| Bot uptime | No crashes during a full trading day |

### 11.3 What to Fix Before Going Live

- If average R:R achieved < 1.0: tighten stop losses or take partial profits
- If win rate < 40% over 40 trades: revisit pre-filter thresholds or Claude prompt
- If daily loss limit triggers >3 times in 4 weeks: reduce RISK_PER_TRADE_PCT to 1%

---

## Phase 12 — Live Trading Migration

**Goal:** Swap paper execution layer for real Angel One order execution. Minimum code change.

### 12.1 What Changes

| Component | Paper Mode | Live Mode |
|---|---|---|
| `paper_trader.open()` | Update in-memory portfolio | Call Angel One `placeOrder()` |
| `paper_trader.close()` | Update in-memory portfolio | Call Angel One `placeOrder()` |
| Fill price | Simulated (last price + slippage) | Actual fill from Angel One order response |
| SL monitoring | Checked on candle close | Replace with Angel One SL bracket order |
| EOD close | Forced in code at 3:15 | Keep (belt and suspenders) |

### 12.2 Angel One Order API

```python
# Live order placement
order_params = {
    "variety":          "NORMAL",
    "tradingsymbol":    "RELIANCE-EQ",
    "symboltoken":      "2885",
    "transactiontype":  "BUY",
    "exchange":         "NSE",
    "ordertype":        "MARKET",
    "producttype":      "INTRADAY",    # MIS equivalent
    "duration":         "DAY",
    "quantity":         str(quantity),
}
response = smart_api.placeOrder(order_params)
order_id = response['data']['orderid']
```

**Critical live trading safeguards:**
1. **Capital hard cap:** Add a check — if total portfolio value drops below ₹8,000 (20% drawdown), bot shuts down completely and requires manual restart
2. **Order confirmation:** After placing, poll `getOrderBook()` to confirm fill price before updating position state
3. **Duplicate order prevention:** Track placed order IDs. On reconnect/restart, check open orders before placing new ones
4. **Emergency stop:** Add a `EMERGENCY_STOP=true` flag in `.env` that halts all new orders immediately
5. **Start with ₹5,000 live, not ₹10,000:** Trade at half capital for the first 2 weeks live

---

## Appendix A — NSE Trading Calendar

The bot must not run on NSE holidays. Maintain a `NSE_HOLIDAYS_2026` list in `config.py`:

```python
NSE_HOLIDAYS_2026 = [
    "2026-01-26",   # Republic Day
    "2026-03-25",   # Holi
    # ... (update from NSE official calendar each year)
]

def is_trading_day() -> bool:
    today = datetime.now(IST).strftime("%Y-%m-%d")
    return today not in NSE_HOLIDAYS_2026 and datetime.now(IST).weekday() < 5
```

## Appendix B — Angel One Instrument Token File

Download monthly from:
```
https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json
```
Filter for `exch_seg == "NSE"` and `symbol` in your Nifty 50 list. Extract the `token` field.

## Appendix C — Known Limitations (Paper vs Live)

| Limitation | Impact |
|---|---|
| Paper fills assume market liquidity | In live, large orders in illiquid windows may get partial fills |
| No circuit filter check in paper mode | Add this in Phase 2: skip stocks at upper/lower circuit |
| Single-threaded design | Adequate for 15-min candles; would fail for tick-level trading |
| No news/earnings calendar | Claude may trade on earnings day without knowing → add to prompt |
| EMA recalculation every candle is O(n) | At 250 bars × 50 stocks = 12,500 ops per cycle. Still fast (<1s). |
