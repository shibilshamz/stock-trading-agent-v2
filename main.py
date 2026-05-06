"""
Stock Trading Agent v2 — Main Entry Point
NSE intraday day-trading with ORB + VWAP + Momentum + Groq AI
"""

import logging
import os
import signal
import sys
import time
from datetime import datetime, time as dtime

import pytz

from alerts.telegram_bot import (
    alert_daily_summary,
    alert_error,
    alert_risk_halt,
    alert_signal,
    alert_startup,
    alert_trade_closed,
    alert_trade_opened,
)
from brain.ai_engine import AIEngine
from config import (
    EOD_SUMMARY_TIME,
    LOG_DIR,
    LOG_LEVEL,
    MARKET_CLOSE_TIME,
    MARKET_OPEN_TIME,
    MORNING_SCAN_TIME,
    PAPER_BALANCE,
    SCAN_INTERVAL_SECONDS,
)
from data.market_data import fetch_all, latest_price
from data.universe import get_trading_universe
from indicators.technical import composite_score
from portfolio.paper_trader import PaperTrader
from risk.sizing import calculate_position
from sentiment.news import batch_sentiment

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(LOG_DIR, "agent.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

IST = pytz.timezone("Asia/Kolkata")


def ist_now() -> datetime:
    return datetime.now(IST)


def parse_ist_time(t: str) -> dtime:
    h, m = map(int, t.split(":"))
    return dtime(h, m)


def is_market_open() -> bool:
    now   = ist_now().time()
    open_ = parse_ist_time(MARKET_OPEN_TIME)
    close = parse_ist_time(MARKET_CLOSE_TIME)
    weekday = ist_now().weekday()  # 0=Mon … 4=Fri
    return weekday < 5 and open_ <= now <= close


# ---------------------------------------------------------------------------
# Core scan-and-trade loop
# ---------------------------------------------------------------------------

def run_scan(trader: PaperTrader, ai: AIEngine, universe: list[str]):
    """Fetch data, score signals, run AI, and execute paper trades."""
    logger.info("--- Scan started (%d symbols) ---", len(universe))

    candles   = fetch_all(universe)
    sentiments = batch_sentiment(universe)

    prices: dict[str, float] = {}
    for sym, df in candles.items():
        if df is not None and not df.empty:
            prices[sym] = float(df["Close"].iloc[-1])

    # Auto-close any SL/TP hits first
    closed = trader.check_positions(prices)
    for trade in closed:
        alert_trade_closed(
            symbol=trade["symbol"],
            action=trade["action"],
            qty=trade["quantity"],
            entry=trade["entry_price"],
            exit_price=trade["exit_price"],
            pnl=trade["pnl"],
            reason=trade["reason"],
        )

    snapshot = trader.portfolio_snapshot(prices)

    for sym in universe:
        df = candles.get(sym)
        if df is None or df.empty:
            logger.debug("No candles for %s — skipping", sym)
            continue

        try:
            tech      = composite_score(df)
            sentiment = sentiments.get(sym, {"score": 0, "label": "neutral", "articles": []})

            portfolio_state = {
                "open_positions": snapshot["open_positions"],
                "cash":           snapshot["cash"],
                "daily_pnl":      snapshot["daily_pnl"],
            }

            decision = ai.decide(sym, tech, sentiment, portfolio_state)
            action   = decision["action"]

            alert_signal(
                symbol=sym,
                score=tech["composite_score"],
                action=action,
                confidence=decision["confidence"],
                ai_reason=decision["reason"],
            )

            if action in ("BUY", "SELL") and sym not in trader.positions:
                entry = prices.get(sym, tech["last_close"])
                params = calculate_position(
                    symbol=sym,
                    action=action,
                    entry_price=entry,
                    atr=tech["atr"] or 0,
                    available_cash=snapshot["cash"],
                    current_balance=PAPER_BALANCE,
                    daily_pnl=snapshot["daily_pnl"],
                    open_positions=snapshot["open_positions"],
                )

                if params:
                    opened = trader.open_position(params)
                    if opened:
                        alert_trade_opened(
                            symbol=sym,
                            action=action,
                            qty=params.quantity,
                            entry=params.entry_price,
                            stop=params.stop_loss,
                            target=params.take_profit,
                            reason=decision["reason"],
                        )
                        snapshot["open_positions"] += 1
                        snapshot["cash"] -= params.position_value

        except Exception as exc:
            logger.error("Error processing %s: %s", sym, exc)
            alert_error(f"scan:{sym}", str(exc))


# ---------------------------------------------------------------------------
# Single-cycle mode (GitHub Actions)
# ---------------------------------------------------------------------------

def run_once():
    """
    Execute exactly one scan cycle and exit.
    Called when GITHUB_ACTIONS=true — the cron schedule is handled externally.
    No persistent state between runs: universe is refreshed each invocation,
    and paper_state.json is not cached across Actions jobs.
    """
    now        = ist_now()
    now_time   = now.time()
    market_day = now.weekday() < 5

    logger.info("GitHub Actions mode — single scan cycle (%s IST)", now.strftime("%H:%M"))

    if not market_day:
        logger.info("Weekend — no trading. Exiting.")
        return

    if not is_market_open():
        logger.info("Market closed at %s IST — no action. Exiting.", now.strftime("%H:%M"))
        return

    trader = PaperTrader(PAPER_BALANCE)

    try:
        universe = get_trading_universe()
    except Exception as exc:
        logger.error("Universe scan failed: %s", exc)
        alert_error("universe_scan", str(exc))
        return

    # Morning reset: first 15-minute window after market open (09:15–09:30 IST)
    morning_open_t = parse_ist_time(MARKET_OPEN_TIME)
    morning_end_t  = parse_ist_time("09:30")
    if morning_open_t <= now_time <= morning_end_t:
        trader.reset_daily_pnl()
        alert_startup(universe, trader.cash)

    with AIEngine() as ai:
        try:
            run_scan(trader, ai, universe)
        except Exception as exc:
            logger.error("Scan error: %s", exc)
            alert_error("run_scan", str(exc))

        # EOD: close all open positions on the final scan of the day
        eod_t = parse_ist_time(EOD_SUMMARY_TIME)
        if now_time >= eod_t and trader.positions:
            logger.info("EOD: force-closing all positions")
            prices = {}
            for sym in list(trader.positions.keys()):
                p = latest_price(sym)
                if p:
                    prices[sym] = p
            trader.close_all_positions(prices, reason="EOD")
            alert_daily_summary(trader.portfolio_snapshot({}))

    logger.info("GitHub Actions scan complete — exiting cleanly.")


# ---------------------------------------------------------------------------
# Main loop (Railway / local)
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 60)
    logger.info("Stock Trading Agent v2 starting up …")

    # GitHub Actions runs one scan cycle per invocation; scheduling is external
    if os.getenv("GITHUB_ACTIONS") == "true":
        run_once()
        return

    trader = PaperTrader(PAPER_BALANCE)
    ai     = AIEngine()

    universe: list[str] = []
    last_scan_date = None

    def handle_shutdown(sig, frame):
        logger.info("Shutdown signal received — closing AI client")
        ai.close()
        sys.exit(0)

    signal.signal(signal.SIGINT,  handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    while True:
        now        = ist_now()
        today      = now.date()
        now_time   = now.time()
        market_day = now.weekday() < 5   # Mon–Fri

        # ---- Morning universe refresh ----
        morning_scan_t = parse_ist_time(MORNING_SCAN_TIME)
        if (
            market_day
            and last_scan_date != today
            and now_time >= morning_scan_t
        ):
            try:
                trader.reset_daily_pnl()
                universe = get_trading_universe()
                last_scan_date = today
                alert_startup(universe, trader.cash)
            except Exception as exc:
                logger.error("Universe scan failed: %s", exc)
                alert_error("universe_scan", str(exc))

        # ---- Intraday scan ----
        if is_market_open() and universe:
            try:
                run_scan(trader, ai, universe)
            except Exception as exc:
                logger.error("Scan loop error: %s", exc)
                alert_error("run_scan", str(exc))

        # ---- EOD close all positions ----
        eod_t = parse_ist_time(EOD_SUMMARY_TIME)
        if (
            market_day
            and now_time >= eod_t
            and trader.positions
        ):
            logger.info("EOD: force-closing all positions")
            prices = {}
            for sym in list(trader.positions.keys()):
                p = latest_price(sym)
                if p:
                    prices[sym] = p
            trader.close_all_positions(prices, reason="EOD")
            snap = trader.portfolio_snapshot({})
            alert_daily_summary(snap)

        logger.debug("Sleeping %ds …", SCAN_INTERVAL_SECONDS)
        time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
