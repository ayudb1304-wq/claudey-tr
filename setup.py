"""
setup.py — One-time setup script for the trading bot.

Run this ONCE when setting up the project for the first time.
It installs dependencies and copies the .env template.

Usage:
    python setup.py
"""

import os
import sys
import subprocess
import shutil

print("\n" + "=" * 55)
print("  TRADING BOT — First-Time Setup")
print("=" * 55)

# ── Step 1: Check Python version ──────────────────────────
print("\n[1/4] Checking Python version...")
major, minor = sys.version_info[:2]
if major < 3 or (major == 3 and minor < 10):
    print(f"  ERROR: Python 3.10+ required. You have {major}.{minor}")
    print("  Download from: https://www.python.org/downloads/")
    sys.exit(1)
print(f"  OK — Python {major}.{minor}")

# ── Step 2: Install dependencies ──────────────────────────
print("\n[2/4] Installing dependencies from requirements.txt...")
print("  This may take 1–3 minutes on first run.\n")

result = subprocess.run(
    [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'],
    capture_output=False,
)
if result.returncode != 0:
    print("\n  ERROR: pip install failed.")
    print("  Try running manually: pip install -r requirements.txt")
    sys.exit(1)
print("\n  Dependencies installed successfully.")

# ── Step 3: Create .env from template ─────────────────────
print("\n[3/4] Setting up .env file...")

if os.path.exists('.env'):
    print("  .env already exists — skipping (will not overwrite).")
else:
    shutil.copy('.env.example', '.env')
    print("  Created .env from .env.example")
    print()
    print("  *** ACTION REQUIRED ***")
    print("  Open the .env file and fill in your real credentials:")
    print("    - ANGEL_ONE_API_KEY")
    print("    - ANGEL_ONE_CLIENT_ID")
    print("    - ANGEL_ONE_PASSWORD    (your MPIN)")
    print("    - ANGEL_ONE_TOTP_SECRET (base32 key from authenticator app)")
    print("    - ANTHROPIC_API_KEY")

# ── Step 4: Create logs directory ─────────────────────────
print("\n[4/4] Creating logs directory...")
os.makedirs('logs', exist_ok=True)
print("  logs/ directory ready.")

# ── Done ──────────────────────────────────────────────────
print()
print("─" * 55)
print("  Setup complete!")
print()
print("  Next steps:")
print("  1. Fill in your credentials in the .env file")
print("  2. Run: python instruments.py")
print("     (Downloads the Angel One instrument master file)")
print("  3. Run: python test_phase1.py")
print("     (Verifies everything works before building further)")
print("─" * 55 + "\n")
