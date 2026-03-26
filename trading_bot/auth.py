"""
auth.py — Angel One SmartAPI Authentication

Handles login, token storage, and daily token refresh.

HOW ANGEL ONE AUTH WORKS:
  1. You call generateSession() with your client ID, MPIN, and a TOTP code.
  2. The TOTP code is a 6-digit number that changes every 30 seconds.
     It's generated from your TOTP secret (the base32 key from your
     authenticator app). We generate it automatically using pyotp.
  3. Angel One returns a JWT token valid for 24 hours.
  4. Every API call uses this JWT token — without it, requests fail.
  5. The bot re-logs in every morning at 9:00 AM to get a fresh token.

SECURITY:
  - Tokens are stored in memory only (the _session dict below).
  - They are NEVER written to disk or printed to terminal.
  - The .env file with your credentials must never be committed to git.
"""

import os
import time as time_module
import pyotp
import pytz
from datetime import datetime, timedelta
from loguru import logger
from dotenv import load_dotenv

# Load .env file into environment variables
# This must be called before reading any os.getenv() values
load_dotenv()

from SmartApi import SmartConnect

IST = pytz.timezone('Asia/Kolkata')

# ─────────────────────────────────────────────────────────────
#  In-memory session storage
#  We store everything in this dict — never in a file.
#  The session is reset when the program exits.
# ─────────────────────────────────────────────────────────────
_session = {
    'smart_api':     None,    # SmartConnect object (the main API client)
    'jwt_token':     None,    # JWT access token from Angel One
    'refresh_token': None,    # Refresh token (used to extend session)
    'feed_token':    None,    # Separate token for WebSocket live feed
    'login_time':    None,    # When we last logged in (IST datetime)
    'client_id':     None,    # Stored to allow logout
}


def login() -> bool:
    """
    Log in to Angel One SmartAPI and store the session tokens.

    Returns:
        True if login succeeded.

    Raises:
        ValueError:      If any required env variable is missing from .env
        ConnectionError: If Angel One rejects the login (wrong credentials,
                         expired TOTP, network issue)

    Usage:
        import auth
        auth.login()
        smart_api = auth.get_smart_api()
    """
    # ── Step 1: Read credentials from .env ────────────────────
    api_key      = os.getenv('ANGEL_ONE_API_KEY')
    client_id    = os.getenv('ANGEL_ONE_CLIENT_ID')
    password     = os.getenv('ANGEL_ONE_PASSWORD')    # Your MPIN, not login password
    totp_secret  = os.getenv('ANGEL_ONE_TOTP_SECRET') # Base32 key, not the 6-digit code

    missing = [k for k, v in {
        'ANGEL_ONE_API_KEY':      api_key,
        'ANGEL_ONE_CLIENT_ID':    client_id,
        'ANGEL_ONE_PASSWORD':     password,
        'ANGEL_ONE_TOTP_SECRET':  totp_secret,
    }.items() if not v]

    if missing:
        raise ValueError(
            f"Missing in .env file: {', '.join(missing)}\n"
            f"Copy .env.example to .env and fill in your credentials."
        )

    # ── Step 2: Generate TOTP code ─────────────────────────────
    # pyotp uses your secret to compute the current 6-digit code.
    # This is the same code your Google Authenticator app shows.
    # TOTP codes change every 30 seconds, so we generate fresh each login.
    totp_code = pyotp.TOTP(totp_secret).now()
    logger.debug(f"Generated TOTP code: {totp_code} (valid for ~{30 - (int(datetime.now().timestamp()) % 30)}s)")

    # ── Step 3: Create SmartConnect client ────────────────────
    smart_api = SmartConnect(api_key=api_key)

    # ── Step 4: Call generateSession ──────────────────────────
    logger.info(f"Logging in to Angel One as {client_id}...")

    try:
        response = smart_api.generateSession(
            clientCode=client_id,
            password=password,
            totp=totp_code,
        )
    except Exception as e:
        raise ConnectionError(
            f"Network error connecting to Angel One: {e}\n"
            f"Check your internet connection."
        )

    # ── Step 5: Validate response ──────────────────────────────
    # IMPORTANT: Angel One always returns HTTP 200, even on login failure.
    # The actual success/failure is inside response['status'].
    # A response of True means success; False or missing means failure.
    if not response.get('status'):
        error_msg = response.get('message', 'Unknown error')
        error_code = response.get('errorcode', '')
        raise ConnectionError(
            f"Angel One rejected login: {error_msg} (code: {error_code})\n"
            f"Common causes:\n"
            f"  - Wrong MPIN (ANGEL_ONE_PASSWORD in .env)\n"
            f"  - Wrong TOTP secret (ANGEL_ONE_TOTP_SECRET in .env)\n"
            f"  - Account locked after multiple failed attempts\n"
            f"  - API key inactive — check https://smartapi.angelbroking.com/"
        )

    # ── Step 6: Store tokens in memory ────────────────────────
    data = response['data']
    _session['smart_api']     = smart_api
    _session['jwt_token']     = data['jwtToken']
    _session['refresh_token'] = data['refreshToken']
    _session['feed_token']    = data['feedToken']
    _session['login_time']    = datetime.now(IST)
    _session['client_id']     = client_id

    logger.success(
        f"Angel One login successful | "
        f"Client: {client_id} | "
        f"Time: {_session['login_time'].strftime('%H:%M:%S IST')} | "
        f"Token valid until: {(_session['login_time'] + timedelta(hours=23)).strftime('%H:%M IST')}"
    )
    return True


def get_smart_api() -> SmartConnect:
    """
    Returns the authenticated SmartConnect object for making API calls.

    Automatically re-logs in if the token has expired (shouldn't happen
    during a single trading day, but handled just in case).

    Usage:
        smart_api = auth.get_smart_api()
        profile = smart_api.getProfile(refresh_token)
    """
    if _session['smart_api'] is None:
        raise RuntimeError(
            "Not logged in. Call auth.login() first.\n"
            "Typically login() is called at startup in main.py."
        )

    if not is_token_valid():
        logger.warning("JWT token expired — re-logging in automatically...")
        login()

    return _session['smart_api']


def get_feed_token() -> str:
    """
    Returns the feed token required for the WebSocket live data connection.

    The feed token is separate from the main JWT token.
    It's used exclusively for subscribing to live tick data.
    """
    if _session['feed_token'] is None:
        raise RuntimeError("Not logged in. Call auth.login() first.")
    return _session['feed_token']


def get_client_id() -> str:
    """Returns the Angel One client ID (used for some API calls)."""
    if _session['client_id'] is None:
        raise RuntimeError("Not logged in. Call auth.login() first.")
    return _session['client_id']


def is_token_valid() -> bool:
    """
    Returns True if the JWT token is still usable.

    Angel One tokens are valid for 24 hours from login time.
    We use a 23-hour limit to give a 1-hour safety buffer.

    In practice, the bot logs in at 9:00 AM and only runs until 3:30 PM,
    so the token never expires during a trading session.
    """
    if _session['login_time'] is None:
        return False

    elapsed = datetime.now(IST) - _session['login_time']
    valid   = elapsed < timedelta(hours=23)

    if not valid:
        logger.warning(
            f"JWT token expired. Login was {elapsed.total_seconds() / 3600:.1f} hours ago."
        )
    return valid


def refresh_token() -> bool:
    """
    Attempt to extend the session using the refresh token.
    Falls back to a full re-login if refresh fails.

    Returns True on success.
    """
    if _session['smart_api'] is None or _session['refresh_token'] is None:
        logger.warning("No active session to refresh. Performing full login.")
        return login()

    try:
        response = _session['smart_api'].generateToken(
            _session['refresh_token']
        )
        if response.get('status'):
            _session['jwt_token']     = response['data']['jwtToken']
            _session['feed_token']    = response['data']['feedToken']
            _session['login_time']    = datetime.now(IST)
            logger.success("Session token refreshed successfully.")
            return True
    except Exception as e:
        logger.warning(f"Token refresh failed ({e}). Attempting full re-login...")

    # Refresh failed — do a full login
    return login()


def logout():
    """
    Cleanly terminate the Angel One session.

    Call this when shutting down the bot to free up the API session slot.
    (Angel One limits concurrent sessions per account.)
    """
    if _session['smart_api'] and _session['client_id']:
        try:
            _session['smart_api'].terminateSession(_session['client_id'])
            logger.info(f"Angel One session terminated for {_session['client_id']}.")
        except Exception as e:
            logger.warning(f"Session termination error (non-critical): {e}")

    # Wipe all tokens from memory
    for key in _session:
        _session[key] = None

    logger.info("Logged out. All tokens cleared.")
