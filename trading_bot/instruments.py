"""
instruments.py — Angel One Instrument Token Loader

WHY THIS FILE EXISTS:
  Angel One's API does NOT accept stock names like "RELIANCE" or "INFY".
  It requires numeric instrument tokens (e.g., RELIANCE = 2885).
  These tokens are in Angel One's "ScripMaster" file — a JSON file they
  publish that maps symbols to tokens.

  This module downloads that file (once, cached locally) and builds a
  symbol → token lookup dict that the rest of the bot uses.

HOW IT WORKS:
  1. On first run, download_scrip_master() fetches the JSON from Angel One.
  2. We save it as scrip_master.json locally (ignored by .gitignore).
  3. load_nifty50_tokens() reads that file and returns only the Nifty 50
     tokens we care about.
  4. Any symbol not found in the file is skipped with a warning.

REFRESH:
  Run `python instruments.py` to re-download the file (do this monthly).
"""

import os
import json
import requests
from loguru import logger
from config import NIFTY_50_SYMBOLS, SCRIP_MASTER_URL, SCRIP_MASTER_FILE


def download_scrip_master(force: bool = False) -> bool:
    """
    Download the Angel One ScripMaster JSON file and save it locally.

    Args:
        force: If True, re-download even if the file already exists.
               Use this to get the latest tokens after index rebalancing.

    Returns:
        True if file was downloaded or already exists.
    """
    if os.path.exists(SCRIP_MASTER_FILE) and not force:
        size_kb = os.path.getsize(SCRIP_MASTER_FILE) / 1024
        logger.info(
            f"ScripMaster file already exists ({size_kb:.0f} KB). "
            f"Using cached version. Run with force=True to refresh."
        )
        return True

    logger.info(f"Downloading ScripMaster from Angel One...")

    try:
        response = requests.get(SCRIP_MASTER_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        raise ConnectionError(
            f"Failed to download ScripMaster file: {e}\n"
            f"URL: {SCRIP_MASTER_URL}\n"
            f"Check your internet connection."
        )

    # The file is a JSON array of instrument records
    data = response.json()
    with open(SCRIP_MASTER_FILE, 'w') as f:
        json.dump(data, f)

    size_kb = os.path.getsize(SCRIP_MASTER_FILE) / 1024
    logger.success(f"ScripMaster downloaded: {len(data):,} instruments ({size_kb:.0f} KB)")
    return True


def load_nifty50_tokens() -> dict:
    """
    Load the Angel One instrument tokens for all Nifty 50 symbols.

    Returns a dict like:
        {
            "RELIANCE":  {"token": "2885",  "exchange": "NSE", "full_name": "RELIANCE INDUSTRIES LTD"},
            "INFY":      {"token": "1594",  "exchange": "NSE", "full_name": "INFOSYS LTD"},
            ...
        }

    Raises:
        FileNotFoundError: If scrip_master.json doesn't exist yet.
                          Call download_scrip_master() first.
    """
    if not os.path.exists(SCRIP_MASTER_FILE):
        raise FileNotFoundError(
            f"'{SCRIP_MASTER_FILE}' not found.\n"
            f"Run instruments.download_scrip_master() first to download it."
        )

    logger.info("Loading instrument tokens from ScripMaster...")

    with open(SCRIP_MASTER_FILE, 'r') as f:
        all_instruments = json.load(f)

    # The ScripMaster has ~200,000+ rows covering NSE, BSE, MCX, etc.
    # Filter for NSE equity stocks only.
    # Each record looks like:
    #   {
    #     "token": "2885",
    #     "symbol": "RELIANCE-EQ",   <-- note the -EQ suffix
    #     "name": "RELIANCE",
    #     "expiry": "",
    #     "strike": "-1.0",
    #     "lotsize": "1",
    #     "instrumenttype": "",      <-- empty string for equities (not "EQ")
    #     "exch_seg": "NSE",
    #     "tick_size": "10.0"
    #   }
    # Key the dict by the base symbol (strip the "-EQ" suffix for easy lookup).
    nse_equities = {}
    for rec in all_instruments:
        if rec.get('exch_seg') == 'NSE' and rec.get('instrumenttype') == '' and rec.get('symbol', '').endswith('-EQ'):
            base_symbol = rec['symbol'][:-3]   # strip "-EQ"
            nse_equities[base_symbol] = rec

    logger.info(f"Found {len(nse_equities):,} NSE equity instruments in ScripMaster.")

    # Build our Nifty 50 token map
    token_map = {}
    not_found = []

    for symbol in NIFTY_50_SYMBOLS:
        if symbol in nse_equities:
            rec = nse_equities[symbol]
            token_map[symbol] = {
                'token':     rec['token'],
                'exchange':  'NSE',
                'full_name': rec.get('name', symbol),
                'tick_size': float(rec.get('tick_size', '5.0')) / 100,  # Convert paisa to rupees
                'lot_size':  int(rec.get('lotsize', '1')),
            }
        else:
            not_found.append(symbol)

    if not_found:
        logger.warning(
            f"These Nifty 50 symbols were NOT found in ScripMaster: {not_found}\n"
            f"Possible causes:\n"
            f"  1. Symbol name changed (e.g., HDFC was merged into HDFCBANK)\n"
            f"  2. Nifty 50 composition changed — update NIFTY_50_SYMBOLS in config.py\n"
            f"  3. ScripMaster is stale — run download_scrip_master(force=True)"
        )

    found_count = len(token_map)
    logger.success(
        f"Loaded {found_count}/{len(NIFTY_50_SYMBOLS)} Nifty 50 tokens. "
        f"Missing: {len(not_found)}"
    )

    if found_count == 0:
        raise RuntimeError(
            "No tokens loaded! ScripMaster may be corrupted or in unexpected format.\n"
            "Delete scrip_master.json and re-run download_scrip_master()."
        )

    return token_map


def get_token(symbol: str, token_map: dict) -> str:
    """
    Safely get the numeric token for a symbol.

    Args:
        symbol:    e.g., "RELIANCE"
        token_map: dict returned by load_nifty50_tokens()

    Returns:
        Token string like "2885"

    Raises:
        KeyError if symbol not in token_map
    """
    if symbol not in token_map:
        raise KeyError(
            f"No token found for '{symbol}'. "
            f"Check that it's in NIFTY_50_SYMBOLS and in the ScripMaster file."
        )
    return token_map[symbol]['token']


# ─────────────────────────────────────────────────────────────
#  Run this file directly to download/refresh the ScripMaster:
#  $ python instruments.py
# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("Downloading Angel One ScripMaster file...")
    download_scrip_master(force=True)

    print("\nLoading Nifty 50 tokens...")
    tokens = load_nifty50_tokens()

    print(f"\n{'Symbol':<15} {'Token':<10} {'Name'}")
    print("-" * 60)
    for sym, info in sorted(tokens.items()):
        print(f"{sym:<15} {info['token']:<10} {info['full_name']}")
