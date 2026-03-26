"""
test_phase5.py — Phase 5 Acceptance Tests: Claude Reasoning Agent

Tests claude_agent.py WITHOUT making real API calls.
All parser/validator tests use hardcoded JSON strings.

If ANTHROPIC_API_KEY is set in .env, an optional live API test runs at the end.

Usage:
    python test_phase5.py
"""

import sys
import os
import json
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="{message}", level="WARNING")

def check(condition, name, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         → {detail}")
        sys.exit(1)

print("\n" + "=" * 52)
print("  PHASE 5 TESTS — Claude Reasoning Agent")
print("=" * 52 + "\n")

# ── Test 1: Imports ────────────────────────────────────────
print("1. Checking imports...")
from claude_agent import build_prompt, parse_response, ask_claude, _hold
check(True, "claude_agent.py imports correctly")
print()

# ── Test 2: _hold() returns correct structure ─────────────
print("2. Testing _hold() fallback structure...")

h = _hold("test reason")
check(h['decision']    == "HOLD",        "HOLD decision")
check(h['conviction']  == 0,             "Conviction = 0")
check(h['entry_price'] is None,          "entry_price is None")
check(h['stop_loss']   is None,          "stop_loss is None")
check(h['target']      is None,          "target is None")
check(h['rr_ratio']    is None,          "rr_ratio is None")
check(h['reasoning']   == "test reason", "Reasoning preserved")
print()

# ── Test 3: build_prompt() output ─────────────────────────
print("3. Testing build_prompt() output content...")

sample_indicators = {
    "price":              1290.0,
    "rsi":                42.5,
    "rsi_prev":           40.1,
    "ema20":              1285.0,
    "ema50":              1275.0,
    "ema200":             1250.0,
    "macd_line":          2.5,
    "signal_line":        2.1,
    "macd_bullish_cross": True,
    "macd_bearish_cross": False,
    "volume":             500_000,
    "volume_sma20":       300_000,
    "volume_ratio":       1.67,
}
sample_pivots = {
    "PP": 1280.0, "R1": 1300.0, "R2": 1320.0, "R3": 1340.0,
    "S1": 1260.0, "S2": 1240.0, "S3": 1220.0,
    "nearest_support":     1280.0,
    "nearest_resistance":  1300.0,
    "support_dist_pct":    0.78,
    "resistance_dist_pct": 0.78,
}

prompt = build_prompt(
    symbol            = "RELIANCE",
    direction_hint    = "long",
    filter_score      = 3,
    indicators        = sample_indicators,
    pivots            = sample_pivots,
    available_capital = 8500.0,
    risk_per_trade    = 170.0,
    current_time_str  = "10:30 AM",
)

check(isinstance(prompt, str),          "build_prompt() returns a string")
check("RELIANCE"     in prompt,         "Symbol present in prompt")
check("1290"         in prompt,         "Current price in prompt")
check("10:30 AM"     in prompt,         "Current time in prompt")
check("LONG"         in prompt,         "Direction hint (uppercased) in prompt")
check("score 3/5"    in prompt,         "Filter score in prompt")
check("RSI"          in prompt,         "RSI indicator in prompt")
check("MACD"         in prompt,         "MACD indicator in prompt")
check("EMA"          in prompt,         "EMA in prompt")
check("volume"       in prompt.lower(), "Volume in prompt")
check("8500"         in prompt,         "Available capital in prompt")
check("170"          in prompt,         "Risk per trade in prompt")
check("R1"           in prompt,         "Pivot R1 in prompt")
check("S1"           in prompt,         "Pivot S1 in prompt")
check("1.5"          in prompt,         "Minimum R:R mentioned in prompt")
print()

# ── Test 4: parse_response() — valid BUY ──────────────────
print("4. Testing parse_response() with valid BUY JSON...")

valid_buy = json.dumps({
    "decision":    "BUY",
    "conviction":  7,
    "entry_price": 1290.0,
    "stop_loss":   1275.0,
    "target":      1315.0,
    "reasoning":   "Bullish MACD crossover with price above EMA20 and EMA50."
})

result = parse_response(valid_buy, current_price=1290.0)
check(result['decision']    == "BUY",    "Decision = BUY")
check(result['conviction']  == 7,        "Conviction = 7")
check(result['entry_price'] == 1290.0,   "Entry price preserved")
check(result['stop_loss']   == 1275.0,   "Stop loss preserved")
check(result['target']      == 1315.0,   "Target preserved")
check('rr_ratio' in result,              "rr_ratio field present")

# R:R = (1315-1290) / (1290-1275) = 25/15 = 1.67
check(result['rr_ratio'] >= 1.4,
      f"R:R ratio {result['rr_ratio']} >= 1.4")
print()

# ── Test 5: parse_response() — valid SELL ─────────────────
print("5. Testing parse_response() with valid SELL JSON...")

valid_sell = json.dumps({
    "decision":    "SELL",
    "conviction":  8,
    "entry_price": 1290.0,
    "stop_loss":   1305.0,
    "target":      1265.0,
    "reasoning":   "Bearish structure confirmed."
})

result_sell = parse_response(valid_sell, current_price=1290.0)
check(result_sell['decision']   == "SELL",   "Decision = SELL")
check(result_sell['stop_loss']  >  1290.0,   "SELL: SL above entry")
check(result_sell['target']     <  1290.0,   "SELL: target below entry")

# R:R = (1290-1265) / (1305-1290) = 25/15 = 1.67
check(result_sell['rr_ratio'] >= 1.4,
      f"SELL R:R {result_sell['rr_ratio']} >= 1.4")
print()

# ── Test 6: parse_response() — valid HOLD ─────────────────
print("6. Testing parse_response() with valid HOLD JSON...")

valid_hold = json.dumps({
    "decision":    "HOLD",
    "conviction":  6,
    "entry_price": None,
    "stop_loss":   None,
    "target":      None,
    "reasoning":   "Setup not clean enough."
})

result_hold = parse_response(valid_hold, current_price=1290.0)
check(result_hold['decision']    == "HOLD", "Decision = HOLD")
check(result_hold['entry_price'] is None,   "entry_price is None")
check(result_hold['stop_loss']   is None,   "stop_loss is None")
check(result_hold['target']      is None,   "target is None")
print()

# ── Test 7: Low conviction → forced HOLD ──────────────────
print("7. Testing conviction < 6 forces HOLD...")

low_conviction = json.dumps({
    "decision":    "BUY",
    "conviction":  5,              # below threshold
    "entry_price": 1290.0,
    "stop_loss":   1275.0,
    "target":      1315.0,
    "reasoning":   "Weak setup."
})

result_low = parse_response(low_conviction, current_price=1290.0)
check(result_low['decision'] == "HOLD",
      f"BUY with conviction=5 forced to HOLD (got {result_low['decision']})")
print()

# ── Test 8: Entry price too far from current price ────────
print("8. Testing entry > 1% from current price is rejected...")

import unittest

far_entry = json.dumps({
    "decision":    "BUY",
    "conviction":  8,
    "entry_price": 1310.0,    # 1.55% above current 1290
    "stop_loss":   1295.0,
    "target":      1340.0,
    "reasoning":   "Future breakout."
})

try:
    parse_response(far_entry, current_price=1290.0)
    check(False, "Should have raised ValueError for far entry")
except ValueError as e:
    check("1%" in str(e) or "away" in str(e).lower(),
          f"ValueError raised correctly for far entry: {str(e)[:60]}")
print()

# ── Test 9: BUY with SL above entry rejected ───────────────
print("9. Testing BUY with SL above entry is rejected...")

bad_buy_sl = json.dumps({
    "decision":    "BUY",
    "conviction":  7,
    "entry_price": 1290.0,
    "stop_loss":   1295.0,    # SL ABOVE entry — invalid for BUY
    "target":      1315.0,
    "reasoning":   "Wrong SL side."
})

try:
    parse_response(bad_buy_sl, current_price=1290.0)
    check(False, "Should have raised ValueError for BUY SL above entry")
except ValueError as e:
    check("BELOW" in str(e) or "stop_loss" in str(e).lower(),
          f"ValueError raised correctly: {str(e)[:60]}")
print()

# ── Test 10: SELL with SL below entry rejected ────────────
print("10. Testing SELL with SL below entry is rejected...")

bad_sell_sl = json.dumps({
    "decision":    "SELL",
    "conviction":  7,
    "entry_price": 1290.0,
    "stop_loss":   1280.0,    # SL BELOW entry — invalid for SELL
    "target":      1265.0,
    "reasoning":   "Wrong SL side."
})

try:
    parse_response(bad_sell_sl, current_price=1290.0)
    check(False, "Should have raised ValueError for SELL SL below entry")
except ValueError as e:
    check("ABOVE" in str(e) or "stop_loss" in str(e).lower(),
          f"ValueError raised correctly: {str(e)[:60]}")
print()

# ── Test 11: R:R below 1.4 is rejected ───────────────────
print("11. Testing R:R below 1.4 is rejected...")

bad_rr = json.dumps({
    "decision":    "BUY",
    "conviction":  8,
    "entry_price": 1290.0,
    "stop_loss":   1280.0,    # risk = 10
    "target":      1300.0,    # reward = 10 → R:R = 1.0, below 1.4
    "reasoning":   "Tight target."
})

try:
    parse_response(bad_rr, current_price=1290.0)
    check(False, "Should have raised ValueError for R:R < 1.4")
except ValueError as e:
    check("R:R" in str(e) or "ratio" in str(e).lower(),
          f"ValueError raised correctly for low R:R: {str(e)[:60]}")
print()

# ── Test 12: Invalid decision value rejected ──────────────
print("12. Testing invalid decision value is rejected...")

bad_decision = json.dumps({
    "decision":    "MAYBE",   # invalid
    "conviction":  7,
    "entry_price": 1290.0,
    "stop_loss":   1275.0,
    "target":      1315.0,
    "reasoning":   "Not sure."
})

try:
    parse_response(bad_decision, current_price=1290.0)
    check(False, "Should have raised ValueError for invalid decision")
except ValueError as e:
    check("decision" in str(e).lower() or "MAYBE" in str(e),
          f"ValueError raised correctly for bad decision: {str(e)[:60]}")
print()

# ── Test 13: Malformed JSON returns ValueError ────────────
print("13. Testing non-JSON response raises ValueError...")

try:
    parse_response("I think you should BUY this stock.", current_price=1290.0)
    check(False, "Should have raised ValueError for non-JSON text")
except ValueError as e:
    check("No JSON" in str(e) or "json" in str(e).lower(),
          f"ValueError raised correctly for no-JSON response: {str(e)[:60]}")
print()

# ── Test 14: JSON wrapped in markdown code block ──────────
print("14. Testing JSON wrapped in markdown code block is parsed...")

wrapped = """Here is my analysis:

```json
{
  "decision": "BUY",
  "conviction": 7,
  "entry_price": 1290.0,
  "stop_loss": 1275.0,
  "target": 1315.0,
  "reasoning": "Momentum confirmed."
}
```"""

result_wrapped = parse_response(wrapped, current_price=1290.0)
check(result_wrapped['decision'] == "BUY",
      "JSON extracted from markdown code block")
print()

# ── Test 15: BUY with target below entry rejected ─────────
print("15. Testing BUY with target below entry is rejected...")

bad_tgt = json.dumps({
    "decision":    "BUY",
    "conviction":  7,
    "entry_price": 1290.0,
    "stop_loss":   1275.0,
    "target":      1280.0,    # target BELOW entry — wrong for BUY
    "reasoning":   "Wrong direction."
})

try:
    parse_response(bad_tgt, current_price=1290.0)
    check(False, "Should have raised ValueError for BUY target below entry")
except ValueError as e:
    check("ABOVE" in str(e) or "target" in str(e).lower(),
          f"ValueError raised correctly for BUY target below entry: {str(e)[:60]}")
print()

# ── Test 16: BUY/SELL with null fields → HOLD fallback ────
print("16. Testing BUY with null entry_price raises ValueError...")

null_fields = json.dumps({
    "decision":    "BUY",
    "conviction":  8,
    "entry_price": None,      # null for a BUY — invalid
    "stop_loss":   1275.0,
    "target":      1315.0,
    "reasoning":   "Missing entry."
})

try:
    parse_response(null_fields, current_price=1290.0)
    check(False, "Should have raised ValueError for null entry_price on BUY")
except ValueError as e:
    check("entry_price" in str(e),
          f"ValueError raised correctly for null entry: {str(e)[:60]}")
print()

# ── Test 17: ask_claude() returns HOLD when no API key ────
print("17. Testing ask_claude() returns HOLD when API key missing...")

# Temporarily unset the key if present, then restore
original_key = os.environ.pop("ANTHROPIC_API_KEY", None)

result_no_key = ask_claude(
    symbol            = "RELIANCE",
    direction_hint    = "long",
    filter_score      = 3,
    indicators        = sample_indicators,
    pivots            = sample_pivots,
    available_capital = 8500.0,
    risk_per_trade    = 170.0,
    current_time_str  = "10:30 AM",
)

check(result_no_key['decision'] == "HOLD",
      f"ask_claude() returns HOLD when no API key (got {result_no_key['decision']})")
check(result_no_key['entry_price'] is None,
      "entry_price is None in fallback HOLD")

# Restore key if it was present
if original_key:
    os.environ["ANTHROPIC_API_KEY"] = original_key
print()

# ── Test 18: Optional live API call ───────────────────────
print("18. Optional: live API call (skipped if no key)...")

from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    print("  [SKIP] ANTHROPIC_API_KEY not set — skipping live API test")
    print("         Add your key to trading_bot/.env to enable this test")
else:
    print("  [INFO] API key found — making a real Claude API call...")
    live_result = ask_claude(
        symbol            = "RELIANCE",
        direction_hint    = "long",
        filter_score      = 3,
        indicators        = sample_indicators,
        pivots            = sample_pivots,
        available_capital = 8500.0,
        risk_per_trade    = 170.0,
        current_time_str  = "10:30 AM",
    )
    check(live_result['decision'] in ("BUY", "SELL", "HOLD"),
          f"Live API returned valid decision: {live_result['decision']}")
    check(isinstance(live_result['conviction'], int),
          f"Live API conviction is int: {live_result['conviction']}")
    check('reasoning' in live_result,
          "Live API response has reasoning field")
    print(f"\n  Live result:")
    print(f"    Decision:   {live_result['decision']}")
    print(f"    Conviction: {live_result['conviction']}/10")
    if live_result['decision'] != 'HOLD':
        print(f"    Entry:      Rs{live_result['entry_price']}")
        print(f"    SL:         Rs{live_result['stop_loss']}")
        print(f"    Target:     Rs{live_result['target']}")
        print(f"    R:R:        {live_result.get('rr_ratio')}")
    print(f"    Reasoning:  {live_result['reasoning'][:100]}...")
print()

# ── Summary ────────────────────────────────────────────────
print("-" * 52)
print("  All Phase 5 tests passed!")
print("  Claude agent verified (parser + validator + fallback).")
print("  Ready to build Phase 6 -- Transaction Costs.")
print("-" * 52 + "\n")
