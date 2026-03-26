"""
test_phase1.py — Phase 1 Acceptance Tests

Run this file to verify that Phase 1 is working correctly before moving on.

Usage:
    python test_phase1.py

What it tests:
    1. .env file exists and has all required keys
    2. Angel One login succeeds
    3. Token is marked as valid after login
    4. SmartConnect object works (can fetch your own profile)
    5. Feed token is available (needed for WebSocket in Phase 2)
    6. ScripMaster file can be downloaded
    7. Nifty 50 tokens load correctly

Expected output on success:
    [PASS] .env file loaded
    [PASS] Login to Angel One succeeded
    [PASS] Token is valid
    [PASS] Profile fetched: YOUR_NAME
    [PASS] Feed token available
    [PASS] ScripMaster downloaded
    [PASS] Nifty 50 tokens loaded: 50 symbols
    ─────────────────────────────────
    All Phase 1 tests passed! Ready for Phase 2.
"""

import os
import sys
from loguru import logger

# Configure loguru to show only our output
logger.remove()
logger.add(sys.stdout, format="{message}", level="DEBUG")


def check(condition: bool, name: str, detail: str = ""):
    """Print pass/fail for a test."""
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         → {detail}")
        sys.exit(1)   # Stop on first failure so error is obvious


print("\n" + "=" * 50)
print("  PHASE 1 TESTS — Environment & Authentication")
print("=" * 50 + "\n")

# ── Test 1: .env file exists and has all required keys ────
print("1. Checking .env file...")

env_file_exists = os.path.exists('.env')
check(env_file_exists, ".env file exists",
      "Copy .env.example to .env and fill in your credentials.")

from dotenv import load_dotenv
load_dotenv()

required_keys = [
    'ANGEL_ONE_API_KEY',
    'ANGEL_ONE_CLIENT_ID',
    'ANGEL_ONE_PASSWORD',
    'ANGEL_ONE_TOTP_SECRET',
    'ANTHROPIC_API_KEY',
]
for key in required_keys:
    val = os.getenv(key)
    check(
        bool(val and val != f'your_{key.lower()}_here' and 'your_' not in val.lower()),
        f".env has {key}",
        f"Set {key} in your .env file (not the placeholder value)"
    )

print()

# ── Test 2: Login to Angel One ────────────────────────────
print("2. Testing Angel One login...")

import auth

try:
    success = auth.login()
    check(success, "Login to Angel One succeeded")
except ValueError as e:
    check(False, "Login to Angel One", str(e))
except ConnectionError as e:
    check(False, "Login to Angel One", str(e))

print()

# ── Test 3: Token validity ────────────────────────────────
print("3. Checking token validity...")

check(auth.is_token_valid(), "Token is valid after login")

print()

# ── Test 4: Fetch account profile ─────────────────────────
print("4. Fetching your Angel One profile...")

try:
    smart_api = auth.get_smart_api()
    profile_response = smart_api.getProfile(auth._session['refresh_token'])

    if profile_response.get('status'):
        data = profile_response.get('data', {})
        name = data.get('name', 'Unknown')
        email = data.get('email', '')
        check(True, f"Profile fetched: {name} ({email})")
    else:
        check(False, "Profile fetch",
              f"Response: {profile_response.get('message', 'Unknown error')}")
except Exception as e:
    check(False, "Profile fetch", str(e))

print()

# ── Test 5: Feed token ────────────────────────────────────
print("5. Checking feed token (needed for WebSocket)...")

try:
    feed_token = auth.get_feed_token()
    check(bool(feed_token), "Feed token available",
          "Feed token is empty — login may have partially failed")
    check(len(feed_token) > 10, "Feed token has valid length")
except RuntimeError as e:
    check(False, "Feed token", str(e))

print()

# ── Test 6: ScripMaster download ──────────────────────────
print("6. Testing ScripMaster download...")

from instruments import download_scrip_master
import os

try:
    # Only download if it doesn't exist yet (avoid re-downloading every test run)
    if not os.path.exists('scrip_master.json'):
        print("   Downloading ScripMaster (this may take 10–20 seconds)...")
        download_scrip_master()
    else:
        print("   ScripMaster already exists — skipping download.")

    check(os.path.exists('scrip_master.json'), "ScripMaster file exists")
    size_kb = os.path.getsize('scrip_master.json') / 1024
    check(size_kb > 500, f"ScripMaster file has content ({size_kb:.0f} KB)",
          "File is too small — may be corrupted. Delete it and re-run.")
except Exception as e:
    check(False, "ScripMaster download", str(e))

print()

# ── Test 7: Nifty 50 tokens ───────────────────────────────
print("7. Loading Nifty 50 instrument tokens...")

from instruments import load_nifty50_tokens
from config import NIFTY_50_SYMBOLS

try:
    token_map = load_nifty50_tokens()
    count = len(token_map)

    check(count > 0, f"Nifty 50 tokens loaded: {count} symbols")
    check(count >= 40, f"At least 40 of 50 symbols found (got {count})",
          "If fewer than 40, update NIFTY_50_SYMBOLS in config.py or refresh ScripMaster")

    # Spot-check a few well-known symbols
    for expected_symbol in ['RELIANCE', 'INFY', 'SBIN', 'ITC']:
        if expected_symbol in token_map:
            token = token_map[expected_symbol]['token']
            check(token.isdigit(), f"  {expected_symbol} token is numeric: {token}")
        else:
            print(f"  [WARN] {expected_symbol} not in token_map — may need to update symbol list")

    # Print full token table
    print(f"\n   {'Symbol':<15} {'Token':<10} {'Name'}")
    print("   " + "-" * 55)
    for sym, info in sorted(token_map.items()):
        print(f"   {sym:<15} {info['token']:<10} {info['full_name'][:30]}")

except Exception as e:
    check(False, "Nifty 50 tokens", str(e))

print()

# ── Test 8: Logout ────────────────────────────────────────
print("8. Testing logout...")
auth.logout()
check(auth._session['smart_api'] is None, "Session cleared after logout")

print()
print("─" * 50)
print("  All Phase 1 tests passed!")
print("  Ready to build Phase 2 — Market Data Layer.")
print("─" * 50 + "\n")
