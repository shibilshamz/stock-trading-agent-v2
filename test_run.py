"""
test_run.py — End-to-end smoke test for every module.
Runs each component independently without starting the scheduler.

Usage:
    python test_run.py
"""

import logging
import sys
import textwrap
import traceback

# Force UTF-8 output so box-drawing chars and ₹ render on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Logging: quiet noisy third-party libs, keep our modules visible
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
for noisy in ("yfinance", "urllib3", "peewee", "curl_cffi", "httpx"):
    logging.getLogger(noisy).setLevel(logging.ERROR)
for ours in ("data", "indicators", "sentiment", "brain", "risk", "portfolio"):
    logging.getLogger(ours).setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def header(title: str):
    bar = "─" * 60
    print(f"\n{bar}")
    print(f"  STEP {title}")
    print(bar)


def ok(label: str, value):
    print(f"  ✓  {label}: {value}")


def fail(label: str, exc: Exception):
    print(f"  ✗  {label} FAILED")
    print(textwrap.indent(traceback.format_exc(), "     "))


def section(label: str):
    print(f"\n  [{label}]")


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
try:
    import pandas as pd
    from config import (
        EMA_FAST, EMA_SLOW, MOMENTUM_RSI_PERIOD,
        PAPER_BALANCE, SIGNAL_THRESHOLD,
        STOP_LOSS_ATR_MULT, TAKE_PROFIT_RR,
    )
    from data.universe import get_trading_universe
    from data.market_data import fetch_candles
    from indicators.technical import (
        calc_atr, calc_ema, calc_rsi, calc_vwap,
        composite_score,
    )
    from sentiment.news import get_sentiment
    from brain.ai_engine import AIEngine
    from risk.sizing import calculate_position
except Exception as e:
    print(f"\n[FATAL] Import error — did you activate the venv?\n  {e}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# STEP 1 — Universe scan
# ---------------------------------------------------------------------------
header("1 of 6 — Morning Universe Scan")

universe = []
try:
    universe = get_trading_universe()

    section("Top 20 stocks selected by morning scan score")
    for rank, sym in enumerate(universe, 1):
        print(f"  {rank:>2}. {sym}")

    ok("Universe size", len(universe))
    ok("First stock (used in next steps)", universe[0] if universe else "N/A")

except Exception as exc:
    fail("Universe scan", exc)
    print("\n[ABORT] Cannot continue without a universe.")
    sys.exit(1)

SYMBOL = universe[0]

# ---------------------------------------------------------------------------
# STEP 2 — 15-minute candles
# ---------------------------------------------------------------------------
header(f"2 of 6 — Fetch 15-min Candles  ({SYMBOL})")

df = None
try:
    df = fetch_candles(SYMBOL)

    if df is None or df.empty:
        raise RuntimeError("fetch_candles returned empty DataFrame")

    section("DataFrame info")
    ok("Rows (candles)", len(df))
    ok("Columns", list(df.columns))
    ok("Date range", f"{df.index[0]}  →  {df.index[-1]}")
    ok("Candle interval", "15 min")

    section("Last 3 candles (OHLCV)")
    # Format nicely: reset index so Datetime shows as a column
    display = df.tail(3).copy()
    display.index = display.index.strftime("%Y-%m-%d %H:%M")
    print(display.to_string())

except Exception as exc:
    fail("Candle fetch", exc)
    print("\n[ABORT] Cannot calculate indicators without candle data.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# STEP 3 — Technical indicators
# ---------------------------------------------------------------------------
header(f"3 of 6 — Technical Indicators  ({SYMBOL})")

tech = {}
try:
    # Individual indicator series (last value of each)
    vwap_series  = calc_vwap(df)
    ema_fast_s   = calc_ema(df["Close"], EMA_FAST)
    ema_slow_s   = calc_ema(df["Close"], EMA_SLOW)
    rsi_series   = calc_rsi(df["Close"], MOMENTUM_RSI_PERIOD)
    atr_series   = calc_atr(df)

    last_close    = float(df["Close"].iloc[-1])
    last_vwap     = float(vwap_series.iloc[-1])
    last_ema_fast = float(ema_fast_s.iloc[-1])
    last_ema_slow = float(ema_slow_s.iloc[-1])
    last_rsi      = float(rsi_series.iloc[-1])
    last_atr      = float(atr_series.iloc[-1])

    section("Latest indicator values")
    ok(f"Close price", f"₹{last_close:.2f}")
    ok(f"VWAP (intraday anchor)", f"₹{last_vwap:.2f}  ({'above' if last_close > last_vwap else 'below'} VWAP)")
    ok(f"EMA {EMA_FAST} (fast)", f"₹{last_ema_fast:.2f}")
    ok(f"EMA {EMA_SLOW} (slow)", f"₹{last_ema_slow:.2f}  ({'fast > slow ↑' if last_ema_fast > last_ema_slow else 'fast < slow ↓'})")
    ok(f"RSI ({MOMENTUM_RSI_PERIOD})", f"{last_rsi:.2f}  ({'overbought' if last_rsi > 70 else 'oversold' if last_rsi < 30 else 'neutral'})")
    ok(f"ATR ({14})", f"₹{last_atr:.2f}  ({last_atr / last_close * 100:.2f}% of price)")

    # Composite signal
    tech = composite_score(df)
    section("Composite signal")
    ok("ORB signal     (-1/0/+1)", tech["orb_signal"])
    ok("VWAP signal    (-1/0/+1)", tech["vwap_signal"])
    ok("Momentum signal(-1/0/+1)", tech["momentum_signal"])
    ok("Composite score (weighted)", f"{tech['composite_score']:+.4f}  (threshold ±{SIGNAL_THRESHOLD})")
    ok("Signal action", f">>> {tech['action']} <<<")

except Exception as exc:
    fail("Technical indicators", exc)
    tech = {"composite_score": 0, "orb_signal": 0, "vwap_signal": 0,
            "momentum_signal": 0, "atr": None, "last_close": float(df["Close"].iloc[-1]),
            "action": "HOLD"}

# ---------------------------------------------------------------------------
# STEP 4 — News sentiment
# ---------------------------------------------------------------------------
header(f"4 of 6 — News Sentiment  ({SYMBOL})")

sentiment = {"score": 0, "label": "neutral", "articles": []}
try:
    sentiment = get_sentiment(SYMBOL)

    section("Sentiment result")
    ok("Score (-1 = very negative, +1 = very positive)", f"{sentiment['score']:+.3f}")
    ok("Label", sentiment["label"].upper())
    ok("Articles fetched", len(sentiment["articles"]))
    ok("Cached", sentiment["cached"])

    if sentiment["articles"]:
        section("Headlines")
        for i, art in enumerate(sentiment["articles"], 1):
            score_tag = f"[{art['sentiment']:+.2f}]"
            headline  = art["title"][:90] + ("…" if len(art["title"]) > 90 else "")
            print(f"  {i}. {score_tag}  {headline}")

except Exception as exc:
    fail("News sentiment", exc)

# ---------------------------------------------------------------------------
# STEP 5 — AI engine decision
# ---------------------------------------------------------------------------
header(f"5 of 6 — AI Engine Decision  ({SYMBOL})")

decision = {}
try:
    portfolio_state = {
        "open_positions": 0,
        "cash":           PAPER_BALANCE,
        "daily_pnl":      0.0,
    }

    with AIEngine() as ai:
        decision = ai.decide(SYMBOL, tech, sentiment, portfolio_state)

    section("Raw decision from Groq (llama-3.1-8b-instant)")
    ok("Action",     decision.get("action", "N/A"))
    ok("Confidence", f"{decision.get('confidence', 0):.0%}")
    ok("Reason",     decision.get("reason", "N/A"))
    ok("Risk note",  decision.get("risk_note", "N/A"))

except Exception as exc:
    fail("AI engine", exc)
    decision = {"action": "BUY", "confidence": 0.5,
                "reason": "fallback for sizing test", "risk_note": "N/A"}

# ---------------------------------------------------------------------------
# STEP 6 — Position sizing
# ---------------------------------------------------------------------------
header(f"6 of 6 — Position Sizing  ({SYMBOL}  •  forced BUY for demo)")

try:
    entry = tech.get("last_close", 0)
    atr   = tech.get("atr") or 0

    if not entry or not atr:
        raise ValueError(f"Missing entry (₹{entry}) or ATR (₹{atr})")

    params = calculate_position(
        symbol=SYMBOL,
        action="BUY",
        entry_price=entry,
        atr=atr,
        available_cash=PAPER_BALANCE,
        current_balance=PAPER_BALANCE,
        daily_pnl=0.0,
        open_positions=0,
    )

    if params is None:
        print("  ⚠  Sizer returned None — risk guards blocked the trade")
        print(f"     (entry=₹{entry:.2f}, ATR=₹{atr:.2f}, balance=₹{PAPER_BALANCE:,})")
    else:
        stop_dist = atr * STOP_LOSS_ATR_MULT
        section("Trade parameters")
        ok("Symbol",          params.symbol)
        ok("Action",          params.action)
        ok("Entry price",     f"₹{params.entry_price:.2f}")
        ok("Stop loss",       f"₹{params.stop_loss:.2f}  (entry − {STOP_LOSS_ATR_MULT}×ATR = ₹{stop_dist:.2f})")
        ok("Take profit",     f"₹{params.take_profit:.2f}  (RR {TAKE_PROFIT_RR}:1)")
        ok("Quantity",        f"{params.quantity} shares")
        ok("Position value",  f"₹{params.position_value:,.2f}  ({params.position_value / PAPER_BALANCE * 100:.1f}% of balance)")
        ok("Max risk",        f"₹{params.risk_amount:.2f}  ({params.risk_amount / PAPER_BALANCE * 100:.2f}% of balance)")
        ok("ATR used",        f"₹{atr:.2f}")

except Exception as exc:
    fail("Position sizing", exc)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
bar = "═" * 60
print(f"\n{bar}")
print("  ALL STEPS COMPLETE")
print(f"{bar}\n")
print("  Next step: copy .env.example → .env with real credentials")
print("  Then run:  python main.py")
print()
