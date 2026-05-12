"""
Telegram alert sender using the Bot API (no python-telegram-bot dependency).
All calls are fire-and-forget via httpx.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx
import pytz

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _send(text: str, parse_mode: str = "HTML") -> bool:
    """Low-level send; returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured — skipping alert")
        return False

    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    try:
        resp = httpx.post(
            url,
            json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "text":       text,
                "parse_mode": parse_mode,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Formatted alert helpers
# ---------------------------------------------------------------------------

def alert_trade_opened(symbol: str, action: str, qty: int, entry: float,
                        stop: float, target: float, reason: str) -> bool:
    arrow = "🟢" if action == "BUY" else "🔴"
    msg = (
        f"{arrow} <b>TRADE OPENED — {action} {symbol}</b>\n"
        f"Entry:  ₹{entry:.2f}  ×  {qty} shares\n"
        f"Stop:   ₹{stop:.2f}\n"
        f"Target: ₹{target:.2f}\n"
        f"AI: {reason}\n"
        f"<i>{_now()}</i>"
    )
    return _send(msg)


def alert_trade_closed(symbol: str, action: str, qty: int,
                        entry: float, exit_price: float,
                        pnl: float, reason: str) -> bool:
    emoji = "✅" if pnl >= 0 else "❌"
    msg = (
        f"{emoji} <b>TRADE CLOSED — {symbol}</b>\n"
        f"Action:  {action}  ×  {qty} shares\n"
        f"Entry:  ₹{entry:.2f}  →  Exit: ₹{exit_price:.2f}\n"
        f"P&L:    ₹{pnl:+.2f}\n"
        f"Reason: {reason}\n"
        f"<i>{_now()}</i>"
    )
    return _send(msg)


def alert_daily_summary(snapshot: dict) -> bool:
    pnl    = snapshot["daily_pnl"]
    total  = snapshot["total_value"]
    ret    = snapshot["return_pct"]
    trades = snapshot["total_trades"]
    emoji  = "📈" if pnl >= 0 else "📉"

    msg = (
        f"{emoji} <b>EOD Summary</b>\n"
        f"Daily P&L:    ₹{pnl:+.2f}\n"
        f"Portfolio:    ₹{total:,.0f}\n"
        f"Total return: {ret:+.2f}%\n"
        f"Trades today: {trades}\n"
        f"<i>{_now()}</i>"
    )
    return _send(msg)


def alert_signal(symbol: str, score: float, action: str,
                  confidence: float, ai_reason: str) -> bool:
    if action == "HOLD":
        return False   # don't spam HOLD signals
    emoji = "📊"
    msg = (
        f"{emoji} <b>SIGNAL — {action} {symbol}</b>\n"
        f"Score:      {score:+.3f}\n"
        f"Confidence: {confidence:.0%}\n"
        f"Reason:     {ai_reason}\n"
        f"<i>{_now()}</i>"
    )
    return _send(msg)


def alert_risk_halt(reason: str) -> bool:
    msg = (
        f"⛔ <b>TRADING HALTED</b>\n"
        f"{reason}\n"
        f"<i>{_now()}</i>"
    )
    return _send(msg)


def alert_error(context: str, error: str) -> bool:
    msg = (
        f"⚠️ <b>ERROR</b> in <code>{context}</code>\n"
        f"{error}\n"
        f"<i>{_now()}</i>"
    )
    return _send(msg)


def alert_startup(universe: list[str], balance: float) -> bool:
    msg = (
        f"🚀 <b>Trading Agent Started</b>\n"
        f"Universe: {', '.join(universe)}\n"
        f"Balance:  ₹{balance:,.0f}\n"
        f"<i>{_now()}</i>"
    )
    return _send(msg)


def alert_market_open(universe: list[str], balance: float, open_positions: int) -> bool:
    shown   = universe[:10]
    extra   = len(universe) - 10
    stocks  = ", ".join(shown) + (f" +{extra} more" if extra > 0 else "")
    carried = f"{open_positions} position(s) carried over" if open_positions else "No carried positions"
    msg = (
        f"🔔 <b>Market Open — Agent Active</b>\n"
        f"Watching:  {len(universe)} stocks\n"
        f"Balance:   ₹{balance:,.0f}\n"
        f"Carried:   {carried}\n"
        f"Schedule:  Scanning every 15 min until 15:30 IST\n"
        f"Stocks:    <i>{stocks}</i>\n"
        f"<i>{_now()}</i>"
    )
    return _send(msg)


def alert_market_close(snapshot: dict) -> bool:
    pnl      = snapshot["daily_pnl"]
    total    = snapshot["total_value"]
    ret      = snapshot["return_pct"]
    trades   = snapshot["total_trades"]
    open_pos = snapshot["open_positions"]

    pnl_emoji    = "📈" if pnl >= 0 else "📉"
    block        = "🟩" if pnl >= 0 else "🟥"
    blocks_count = min(int(abs(pnl) / 100), 5)
    blocks       = block * blocks_count if blocks_count else ""

    carried = (
        f"{open_pos} position(s) carried to tomorrow" if open_pos else "No open positions"
    )
    msg = (
        f"{pnl_emoji} <b>Market Closed — Agent Signing Off</b>\n"
        f"Daily P&L:  ₹{pnl:+.2f}  {blocks}\n"
        f"Portfolio:  ₹{total:,.0f}\n"
        f"Return:     {ret:+.2f}%\n"
        f"Trades:     {trades}\n"
        f"Positions:  {carried}\n"
        f"Next scan:  tomorrow 07:45 UAE / 09:15 IST\n"
        f"<i>{_now()}</i>"
    )
    return _send(msg)


def _now() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S IST")
