"""
Position sizing and risk management.
Uses ATR-based stop-loss to determine share quantity and validates against
per-trade and daily-loss limits.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from config import (
    ATR_PERIOD,
    MAX_DAILY_LOSS_PCT,
    MAX_OPEN_POSITIONS,
    MAX_RISK_PER_TRADE_PCT,
    PAPER_BALANCE,
    POSITION_SIZE_PCT,
    STOP_LOSS_ATR_MULT,
    TAKE_PROFIT_RR,
)

logger = logging.getLogger(__name__)


@dataclass
class TradeParams:
    symbol:       str
    action:       str          # "BUY" or "SELL"
    entry_price:  float
    stop_loss:    float
    take_profit:  float
    quantity:     int
    risk_amount:  float        # ₹ at risk
    position_value: float      # ₹ deployed


def calculate_position(
    symbol: str,
    action: str,
    entry_price: float,
    atr: float,
    available_cash: float,
    current_balance: float,
    daily_pnl: float,
    open_positions: int,
) -> Optional[TradeParams]:
    """
    Return a TradeParams if the trade passes all risk checks, else None.

    Sizing logic:
      stop_distance = ATR × STOP_LOSS_ATR_MULT
      max_risk_cash = balance × MAX_RISK_PER_TRADE_PCT
      quantity = floor(max_risk_cash / stop_distance)
      capped by POSITION_SIZE_PCT × balance
    """
    if action not in ("BUY", "SELL"):
        logger.warning("Invalid action '%s' — skipping sizing", action)
        return None

    # ---- Guard: daily loss limit ----
    max_daily_loss = current_balance * MAX_DAILY_LOSS_PCT
    if daily_pnl <= -max_daily_loss:
        logger.warning(
            "Daily loss limit hit (₹%.0f). No new trades.", daily_pnl
        )
        return None

    # ---- Guard: max open positions ----
    if open_positions >= MAX_OPEN_POSITIONS:
        logger.warning("Max open positions (%d) reached.", MAX_OPEN_POSITIONS)
        return None

    # ---- Guard: ATR validity ----
    if not atr or atr <= 0:
        logger.warning("Invalid ATR for %s — skipping", symbol)
        return None

    stop_distance = atr * STOP_LOSS_ATR_MULT

    # Stop-loss and take-profit levels
    if action == "BUY":
        stop_loss   = round(entry_price - stop_distance, 2)
        take_profit = round(entry_price + stop_distance * TAKE_PROFIT_RR, 2)
    else:  # SELL (short)
        stop_loss   = round(entry_price + stop_distance, 2)
        take_profit = round(entry_price - stop_distance * TAKE_PROFIT_RR, 2)

    # Risk-based quantity
    max_risk_cash = current_balance * MAX_RISK_PER_TRADE_PCT
    qty_by_risk   = int(max_risk_cash / stop_distance) if stop_distance > 0 else 0

    # Cash-based cap
    max_position_cash = current_balance * POSITION_SIZE_PCT
    qty_by_cash       = int(min(available_cash, max_position_cash) / entry_price)

    quantity = min(qty_by_risk, qty_by_cash)

    if quantity <= 0:
        logger.warning(
            "Computed 0 shares for %s (cash=%.0f, risk=%.0f) — skipping",
            symbol, qty_by_cash, qty_by_risk,
        )
        return None

    position_value = round(quantity * entry_price, 2)
    risk_amount    = round(quantity * stop_distance, 2)

    params = TradeParams(
        symbol=symbol,
        action=action,
        entry_price=round(entry_price, 2),
        stop_loss=stop_loss,
        take_profit=take_profit,
        quantity=quantity,
        risk_amount=risk_amount,
        position_value=position_value,
    )

    logger.info(
        "Sized %s %s: qty=%d @₹%.2f | SL=₹%.2f | TP=₹%.2f | risk=₹%.2f",
        action, symbol, quantity, entry_price, stop_loss, take_profit, risk_amount,
    )
    return params


def check_stop_or_target(
    position: dict,
    current_price: float,
) -> Optional[str]:
    """
    Returns "STOP_LOSS", "TAKE_PROFIT", or None.
    `position` must have keys: action, stop_loss, take_profit.
    """
    action      = position["action"]
    stop_loss   = position["stop_loss"]
    take_profit = position["take_profit"]

    if action == "BUY":
        if current_price <= stop_loss:
            return "STOP_LOSS"
        if current_price >= take_profit:
            return "TAKE_PROFIT"
    else:  # SELL / short
        if current_price >= stop_loss:
            return "STOP_LOSS"
        if current_price <= take_profit:
            return "TAKE_PROFIT"

    return None
