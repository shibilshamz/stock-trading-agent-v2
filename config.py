"""
Central configuration for stock-trading-agent-v2.
All tuneable parameters live here; secrets are loaded from .env.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paper trading
# ---------------------------------------------------------------------------
PAPER_BALANCE = 50_000          # ₹ starting capital
MAX_OPEN_POSITIONS = 5          # concurrent trades
# Cash cap upper bound per trade — primary sizing is ATR risk-based (MAX_RISK_PER_TRADE_PCT).
# This only binds when the ATR method would exceed it, or when stock price is high
# relative to balance (e.g. ₹3,200 stock on ₹50,000 balance needs ≥20% to get >1 share).
POSITION_SIZE_PCT = 0.20        # 20 % of balance per trade (cash cap)
MAX_DAILY_LOSS_PCT = 0.03       # halt after -3 % drawdown on the day

# Cooldown — re-entry prevention after stop loss
COOLDOWN_HOURS = 4              # hours to block re-entry after a SL hit; 0 = disabled

# Market regime — crash detection
NIFTY_CRASH_PCT = 1.0           # if Nifty is down more than this % today → defensive mode
NIFTY_CRASH_DAYS = 2            # OR this many consecutive down-days → defensive mode

# Stale position guard
STALE_POSITION_HOURS = 6        # force-close any position held longer than this; 0 = disabled

# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
NIFTY50_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "HINDUNILVR",
    "INFY", "SBIN", "BHARTIARTL", "KOTAKBANK", "ITC",
    "LT", "HCLTECH", "AXISBANK", "ASIANPAINT", "MARUTI",
    "SUNPHARMA", "TITAN", "BAJFINANCE", "WIPRO", "ULTRACEMCO",
    "NTPC", "POWERGRID", "ONGC", "COALINDIA", "JSWSTEEL",
    "TATAMOTORS-BE", "TATASTEEL", "ADANIENT", "ADANIPORTS", "BAJAJFINSV",
    "BPCL", "BRITANNIA", "CIPLA", "DIVISLAB", "DRREDDY",
    "EICHERMOT", "GRASIM", "HEROMOTOCO", "INDUSINDBK", "NESTLEIND",
    "SBILIFE", "SHREECEM", "TECHM", "TATACONSUM", "UPL",
    "HDFCLIFE", "HINDALCO", "M&M", "APOLLOHOSP", "BAJAJ-AUTO",
]
UNIVERSE_TOP_N = 20             # pick top N by morning scan score

# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------
CANDLE_INTERVAL = "15m"         # yfinance interval
CANDLE_LOOKBACK_DAYS = 5        # days of history to fetch
MARKET_OPEN_TIME  = "09:15"     # IST
MARKET_CLOSE_TIME = "15:30"     # IST
NSE_SUFFIX = ".NS"              # appended to symbols for yfinance

# ---------------------------------------------------------------------------
# Strategy parameters
# ---------------------------------------------------------------------------

# Opening Range Breakout
ORB_MINUTES = 30                # first 30-min candles define the range

# VWAP
VWAP_BAND_STD = 1.0             # ±1 σ bands around VWAP

# Momentum
MOMENTUM_RSI_PERIOD = 14
MOMENTUM_RSI_OVERBOUGHT = 70
MOMENTUM_RSI_OVERSOLD  = 30
EMA_FAST = 9
EMA_SLOW = 21

# Signal weights for composite score
WEIGHT_ORB      = 0.40
WEIGHT_VWAP     = 0.30
WEIGHT_MOMENTUM = 0.30

# Minimum composite score to enter a trade
SIGNAL_THRESHOLD = 0.55

# ---------------------------------------------------------------------------
# Risk / sizing
# ---------------------------------------------------------------------------
STOP_LOSS_ATR_MULT  = 1.5       # stop = entry ± 1.5 × ATR
TAKE_PROFIT_RR      = 2.0       # target = risk × 2
ATR_PERIOD          = 14
MAX_RISK_PER_TRADE_PCT = 0.01   # max 1 % of balance at risk per trade

# ---------------------------------------------------------------------------
# AI brain (Groq)
# ---------------------------------------------------------------------------
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL     = "llama-3.1-8b-instant"
GROQ_BASE_URL  = "https://api.groq.com/openai/v1"
AI_MAX_TOKENS  = 512
AI_TEMPERATURE = 0.2

# ---------------------------------------------------------------------------
# News / sentiment
# ---------------------------------------------------------------------------
NEWS_RSS_TEMPLATE = (
    "https://news.google.com/rss/search?q={query}+NSE+stock&hl=en-IN&gl=IN&ceid=IN:en"
)
NEWS_MAX_ARTICLES  = 5          # articles per symbol
NEWS_CACHE_MINUTES = 30         # re-fetch after this many minutes

# ---------------------------------------------------------------------------
# Telegram alerts
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
SCAN_INTERVAL_SECONDS  = 900    # 15-min candle → scan every 15 min
MORNING_SCAN_TIME      = "09:20"  # IST, after market opens
EOD_SUMMARY_TIME       = "15:30"  # IST — matches 10:00 UTC final cron trigger

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR   = "logs"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
