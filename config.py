"""
Railway-friendly config – every secret/value comes from env-vars.
No hard-coded credentials. Missing critical vars -> exit early.
"""
import os
import sys
from pathlib import Path

# ---------- Telegram ----------
api_id       = int(os.getenv("API_ID") or 0)
api_hash     = os.getenv("API_HASH")
session_name = os.getenv("SESSION_NAME", "trader_session")  # StringSession will reuse this name for logs
channel_username = os.getenv("CHANNELS")   # can be ID (-100...) or @publichandle

# ---------- Trading ----------
APP               = os.getenv("TRADING_APP", "Wizard").strip()
wizard_chat_id    = os.getenv("WIZARD_CHAT_ID", "@TradeWiz_Solbot")
wallet_address    = os.getenv("WALLET_ADDRESS")
max_mcap          = os.getenv("MAX_MCAP")           # optional, int or None
WEBSOCKET_URL     = os.getenv("WEBSOCKET_URL")
RPC_URL           = os.getenv("RPC_URL")

# ---------- Constants (never changes) ----------
SOL      = "So11111111111111111111111111111111111111112"
USDC     = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
DECIMALS = 6

# ---------- Validation ----------
def _require(var, name):
    if not var:
        print(f"❌ Environment variable {name} is missing")
        sys.exit(1)

_require(api_hash,     "API_HASH")
_require(channel_username, "CHANNELS")
_require(wallet_address,   "WALLET_ADDRESS")
_require(WEBSOCKET_URL,    "WEBSOCKET_URL")
_require(RPC_URL,          "RPC_URL")

if api_id <= 0:
    print("❌ API_ID must be a positive integer")
    sys.exit(1)

# Optional numeric parsing
if max_mcap:
    try:
        max_mcap = int(max_mcap)
    except ValueError:
        max_mcap = None
else:
    max_mcap = None