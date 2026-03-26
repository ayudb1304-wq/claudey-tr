"""
claude_agent.py — Claude AI Reasoning Agent

Claude is the final decision-maker for every trade.
The pre-filter sends only high-scoring setups here.
Claude gets the full technical picture and decides: BUY, SELL, or HOLD.

FLOW:
  pre-filter (score >= 2)
      → build_prompt()         assemble indicator + pivot context
      → ask_claude()           call Anthropic API with retry logic
      → parse_response()       validate JSON, check R:R, check conviction
      → return decision dict   used by risk_manager and paper_trader

RESPONSE SCHEMA (Claude must return this exact JSON):
    "decision":    "BUY" | "SELL" | "HOLD",
    "conviction":  1-10,
    "entry_price": float | null,
    "stop_loss":   float | null,
    "target":      float | null,
    "reasoning":   "string (max 150 words)"
  }

FALLBACK:
  On ANY error (network, rate limit, bad JSON, failed validation),
  the function returns a HOLD decision. The bot never crashes on Claude
  failures — it simply skips the trade for that candle.

COST CONTROL:
  max_tokens=512 caps output per call (~150 tokens used in practice).
  At 15 calls/day: ~Rs 3-4/day total Claude cost.
"""

import os
import json
import re
import time

import anthropic
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# ─────────────────────────────────────────────────────────────
#  SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an intraday trading analysis agent for NSE (India) equities.
You analyze 15-minute OHLCV candle data and technical indicators for Nifty 50 stocks.

Context:
- Market: NSE India, intraday only, all positions close by 3:15 PM IST
- Capital: small retail account, risk-averse
- Timeframe: 15-minute candles
- You receive data from a pre-filter that has already identified this as a potential setup

Your job: evaluate the setup and decide whether to trade, and at what levels.

Rules:
- Be conservative. When in doubt, HOLD.
- conviction < 6 must result in HOLD
- If time is 3:00 PM IST or later, always return HOLD (too close to close)
- stop_loss must create a risk:reward ratio of at least 1.5 with your target
- entry_price should be very close to the current price (within 0.5%)
- For BUY: stop_loss < entry_price < target
- For SELL: target < entry_price < stop_loss

You MUST respond with ONLY valid JSON. No explanation text, no markdown, no code blocks.
Exact schema required:
{
  "decision": "BUY" or "SELL" or "HOLD",
  "conviction": integer 1-10,
  "entry_price": number or null,
  "stop_loss": number or null,
  "target": number or null,
  "reasoning": "string under 150 words"
}
If decision is HOLD, set entry_price, stop_loss, and target to null."""

# Lazy-initialised client — created only when first API call is made.
# This avoids crashing at import time if the API key is missing.
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY not set in .env file.\n"
                "Get your key from https://console.anthropic.com/ and add it to .env"
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


# ─────────────────────────────────────────────────────────────
#  PROMPT BUILDER
# ─────────────────────────────────────────────────────────────

def build_prompt(
    symbol:            str,
    direction_hint:    str,       # "long" or "short" — from pre-filter
    filter_score:      int,       # pre-filter score (2-5)
    indicators:        dict,      # from calculate_indicators()
    pivots:            dict,      # from enrich_pivots()
    available_capital: float,
    risk_per_trade:    float,
    current_time_str:  str,       # e.g. "10:30 AM"
) -> str:
    """
    Build the user message for Claude.

    Includes all technical context Claude needs to make a decision.
    The direction_hint tells Claude what the quantitative pre-filter
    found — Claude can agree, disagree, or HOLD.
    """
    price = indicators['price']

    price_vs_ema20 = "ABOVE" if price > indicators['ema20'] else "BELOW"
    ema20_vs_ema50 = (
        "ABOVE (bullish structure)"
        if indicators['ema20'] > indicators['ema50']
        else "BELOW (bearish structure)"
    )

    macd_signal_text = (
        "Bullish crossover this candle"
        if indicators['macd_bullish_cross']
        else "Bearish crossover this candle"
        if indicators['macd_bearish_cross']
        else "No crossover"
    )

    # Format pivot levels for the prompt
    pp  = pivots.get('PP',  'N/A')
    r1  = pivots.get('R1',  'N/A')
    r2  = pivots.get('R2',  'N/A')
    s1  = pivots.get('S1',  'N/A')
    s2  = pivots.get('S2',  'N/A')

    ns  = pivots.get('nearest_support',        'N/A')
    nr  = pivots.get('nearest_resistance',     'N/A')
    sd  = pivots.get('support_dist_pct',       'N/A')
    rd  = pivots.get('resistance_dist_pct',    'N/A')

    return f"""Stock: {symbol} | Exchange: NSE | Timeframe: 15-min
Current time: {current_time_str} IST
Current price: Rs{price}

PRE-FILTER SIGNAL: {direction_hint.upper()} (score {filter_score}/5 — {filter_score} of 5 indicators aligned)

--- TREND ---
EMA 20:  Rs{indicators['ema20']}  (short-term trend)
EMA 50:  Rs{indicators['ema50']}  (medium-term trend)
EMA 200: Rs{indicators['ema200']}  (long-term structural trend — context only)
Price vs EMA20: {price_vs_ema20}
EMA20 vs EMA50: {ema20_vs_ema50}

--- MOMENTUM ---
RSI(14): {indicators['rsi']} (previous candle: {indicators['rsi_prev']})
MACD line: {indicators['macd_line']} | Signal line: {indicators['signal_line']}
MACD: {macd_signal_text}

--- VOLUME ---
This candle: {indicators['volume']:,}
20-candle avg: {indicators['volume_sma20']:,}
Ratio: {indicators['volume_ratio']}x average

--- SUPPORT & RESISTANCE (Classic Pivot Points — today's levels) ---
R2: Rs{r2} | R1: Rs{r1} | PP: Rs{pp} | S1: Rs{s1} | S2: Rs{s2}
Nearest support:    Rs{ns} ({sd}% below current price)
Nearest resistance: Rs{nr} ({rd}% above current price)

--- RISK PARAMETERS ---
Available capital: Rs{available_capital:.0f}
Max risk this trade: Rs{risk_per_trade:.0f}
Minimum R:R required: 1.5"""


# ─────────────────────────────────────────────────────────────
#  RESPONSE PARSER
# ─────────────────────────────────────────────────────────────

def parse_response(response_text: str, current_price: float) -> dict:
    """
    Parse and validate Claude's JSON response.

    Validates:
      - JSON is parseable
      - decision is BUY / SELL / HOLD
      - conviction is 1-10
      - If not HOLD: entry/sl/target are present and numerically correct
      - stop_loss is on the correct side of entry
      - target gives R:R >= 1.4 (slightly below 1.5 threshold to forgive rounding)
      - entry_price is within 1% of current price (no hallucinated far entries)
      - conviction < 6 is forced to HOLD

    Returns:
      Validated decision dict, or a HOLD dict if any check fails.
    """
    # ── Step 1: Extract JSON ──────────────────────────────────
    # Claude sometimes wraps JSON in ```json ... ``` or adds surrounding text.
    # The regex pulls out the first { ... } block.
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if not json_match:
        raise ValueError(f"No JSON object found in response: {response_text[:200]}")

    data = json.loads(json_match.group())

    # ── Step 2: Schema validation ─────────────────────────────
    if data.get('decision') not in ('BUY', 'SELL', 'HOLD'):
        raise ValueError(f"Invalid decision: {data.get('decision')}")

    conviction = int(data.get('conviction', 0))
    if not (1 <= conviction <= 10):
        raise ValueError(f"Conviction out of range: {conviction}")

    # ── Step 3: Low conviction → force HOLD ───────────────────
    if conviction < 6:
        return _hold(f"Low conviction ({conviction}/10) — treating as HOLD")

    # ── Step 4: HOLD — check nulls ────────────────────────────
    if data['decision'] == 'HOLD':
        return {
            "decision":    "HOLD",
            "conviction":  conviction,
            "entry_price": None,
            "stop_loss":   None,
            "target":      None,
            "reasoning":   str(data.get('reasoning', 'Claude returned HOLD')),
        }

    # ── Step 5: BUY/SELL — numeric field checks ───────────────
    for field in ('entry_price', 'stop_loss', 'target'):
        if data.get(field) is None:
            raise ValueError(f"'{field}' is null for {data['decision']} decision")

    entry = float(data['entry_price'])
    sl    = float(data['stop_loss'])
    tgt   = float(data['target'])

    # ── Step 6: Entry price sanity ────────────────────────────
    # Entry should be close to current price — reject if > 1% away.
    # This catches cases where Claude hallucinates a future price target as entry.
    entry_pct_diff = abs(entry - current_price) / current_price * 100
    if entry_pct_diff > 1.0:
        raise ValueError(
            f"Entry Rs{entry} is {entry_pct_diff:.2f}% away from "
            f"current price Rs{current_price} — should be within 1%"
        )

    # ── Step 7: SL on correct side ────────────────────────────
    if data['decision'] == 'BUY':
        if sl >= entry:
            raise ValueError(
                f"BUY stop_loss (Rs{sl}) must be BELOW entry (Rs{entry})"
            )
        if tgt <= entry:
            raise ValueError(
                f"BUY target (Rs{tgt}) must be ABOVE entry (Rs{entry})"
            )
        risk   = entry - sl
        reward = tgt - entry

    else:  # SELL
        if sl <= entry:
            raise ValueError(
                f"SELL stop_loss (Rs{sl}) must be ABOVE entry (Rs{entry})"
            )
        if tgt >= entry:
            raise ValueError(
                f"SELL target (Rs{tgt}) must be BELOW entry (Rs{entry})"
            )
        risk   = sl - entry
        reward = entry - tgt

    # ── Step 8: R:R validation ────────────────────────────────
    # Use 1.4 (not 1.5) to forgive minor rounding in Claude's arithmetic.
    # The risk_manager will apply the strict 1.5 threshold before execution.
    if risk <= 0:
        raise ValueError(f"Risk is zero or negative: {risk}")

    rr = reward / risk
    if rr < 1.4:
        raise ValueError(
            f"R:R ratio {rr:.2f} below minimum 1.4 "
            f"(risk=Rs{risk:.2f}, reward=Rs{reward:.2f})"
        )

    return {
        "decision":    data['decision'],
        "conviction":  conviction,
        "entry_price": round(entry, 2),
        "stop_loss":   round(sl,    2),
        "target":      round(tgt,   2),
        "reasoning":   str(data.get('reasoning', '')),
        "rr_ratio":    round(rr, 2),
    }


# ─────────────────────────────────────────────────────────────
#  MAIN API CALL
# ─────────────────────────────────────────────────────────────

def ask_claude(
    symbol:            str,
    direction_hint:    str,
    filter_score:      int,
    indicators:        dict,
    pivots:            dict,
    available_capital: float,
    risk_per_trade:    float,
    current_time_str:  str,
    max_retries:       int = 3,
) -> dict:
    """
    Send a setup to Claude and get a trading decision.

    Always returns a valid decision dict — never raises.
    On any failure, returns HOLD with a reason in 'reasoning'.

    Args:
        symbol:            NSE symbol e.g. "RELIANCE"
        direction_hint:    "long" or "short" from pre-filter
        filter_score:      Pre-filter score (2-5)
        indicators:        Dict from calculate_indicators()
        pivots:            Dict from enrich_pivots()
        available_capital: Current paper portfolio cash
        risk_per_trade:    Max Rs to risk on this trade
        current_time_str:  e.g. "10:30 AM"
        max_retries:       API call retry attempts

    Returns:
        {
            "decision":    "BUY" | "SELL" | "HOLD",
            "conviction":  int,
            "entry_price": float | None,
            "stop_loss":   float | None,
            "target":      float | None,
            "reasoning":   str,
            "rr_ratio":    float | None,   (present only on BUY/SELL)
        }
    """
    prompt = build_prompt(
        symbol, direction_hint, filter_score,
        indicators, pivots,
        available_capital, risk_per_trade, current_time_str,
    )

    logger.debug(f"[CLAUDE] Asking about {symbol} ({direction_hint.upper()}, score {filter_score})")

    for attempt in range(1, max_retries + 1):
        try:
            client   = _get_client()
            message  = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = message.content[0].text
            logger.debug(f"[CLAUDE] Raw response for {symbol}: {raw_text[:300]}")

            decision = parse_response(raw_text, indicators['price'])
            logger.info(
                f"[CLAUDE] {symbol} → {decision['decision']} "
                f"(conviction={decision['conviction']}/10)"
                + (f" | entry=Rs{decision['entry_price']} "
                   f"sl=Rs{decision['stop_loss']} "
                   f"target=Rs{decision['target']} "
                   f"R:R={decision.get('rr_ratio')}"
                   if decision['decision'] != 'HOLD' else "")
            )
            return decision

        except anthropic.RateLimitError:
            logger.warning(
                f"[CLAUDE] Rate limit hit for {symbol} "
                f"(attempt {attempt}/{max_retries}) — waiting 60s"
            )
            time.sleep(60)

        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            logger.warning(
                f"[CLAUDE] API error for {symbol} "
                f"(attempt {attempt}/{max_retries}): {e}"
            )
            if attempt < max_retries:
                time.sleep(3 * attempt)   # Back off: 3s, 6s, 9s

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(
                f"[CLAUDE] Parse/validation error for {symbol} "
                f"(attempt {attempt}/{max_retries}): {e}"
            )
            if attempt < max_retries:
                time.sleep(2)

        except EnvironmentError as e:
            # API key not configured — no point retrying
            logger.error(f"[CLAUDE] {e}")
            return _hold(str(e))

    logger.warning(f"[CLAUDE] All {max_retries} attempts failed for {symbol} — returning HOLD")
    return _hold(f"All {max_retries} API attempts failed")


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def _hold(reason: str) -> dict:
    """Return a safe HOLD decision with a reason."""
    return {
        "decision":    "HOLD",
        "conviction":  0,
        "entry_price": None,
        "stop_loss":   None,
        "target":      None,
        "reasoning":   reason,
        "rr_ratio":    None,
    }
