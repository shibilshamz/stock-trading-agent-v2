"""
Paper trading engine.
Maintains positions, cash balance, P&L, and trade history in memory.
Persists state to logs/paper_state.json so restarts don't reset the book.
Appends every open/close event to logs/trades.csv for the dashboard.
"""

import csv
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import pytz

from config import LOG_DIR, PAPER_BALANCE
from risk.sizing import TradeParams, check_stop_or_target

logger = logging.getLogger(__name__)

STATE_FILE  = os.path.join(LOG_DIR, "paper_state.json")
TRADES_CSV  = os.path.join(LOG_DIR, "trades.csv")
_IST        = pytz.timezone("Asia/Kolkata")

_CSV_HEADERS = [
    "timestamp_ist", "symbol", "action", "entry_price", "quantity",
    "stop_loss", "target", "confidence", "ai_source", "composite_score",
    "status", "pnl",
]


class PaperTrader:
    def __init__(self, starting_balance: float = PAPER_BALANCE):
        self.starting_balance = starting_balance
        self.cash:       float = starting_balance
        self.positions:  dict  = {}   # symbol → position dict
        self.trade_log:  list  = []
        self.daily_pnl:  float = 0.0
        self._load_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_position(
        self,
        params: TradeParams,
        confidence: float = 0.0,
        ai_source: str = "unknown",
        composite_score: float = 0.0,
    ) -> bool:
        """
        Open a new paper position.
        Returns True on success, False if insufficient cash or already open.
        """
        if params.symbol in self.positions:
            logger.warning("Duplicate rejected: already have an open position in %s", params.symbol)
            return False

        if params.position_value > self.cash:
            logger.warning(
                "Insufficient cash (₹%.0f) for %s (₹%.0f)",
                self.cash, params.symbol, params.position_value,
            )
            return False

        self.cash -= params.position_value
        self.positions[params.symbol] = {
            "symbol":          params.symbol,
            "action":          params.action,
            "entry_price":     params.entry_price,
            "stop_loss":       params.stop_loss,
            "take_profit":     params.take_profit,
            "quantity":        params.quantity,
            "position_value":  params.position_value,
            "risk_amount":     params.risk_amount,
            "opened_at":       datetime.now(timezone.utc).isoformat(),
            "confidence":      confidence,
            "ai_source":       ai_source,
            "composite_score": composite_score,
        }

        self._append_csv({
            "timestamp_ist":   datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S"),
            "symbol":          params.symbol,
            "action":          params.action,
            "entry_price":     params.entry_price,
            "quantity":        params.quantity,
            "stop_loss":       params.stop_loss,
            "target":          params.take_profit,
            "confidence":      round(confidence, 3),
            "ai_source":       ai_source,
            "composite_score": round(composite_score, 4),
            "status":          "OPEN",
            "pnl":             0.0,
        })

        logger.info(
            "OPENED %s %s: %d shares @₹%.2f | cash left ₹%.0f",
            params.action, params.symbol, params.quantity,
            params.entry_price, self.cash,
        )
        self._save_state()
        return True

    def close_position(self, symbol: str, exit_price: float, reason: str = "MANUAL") -> Optional[dict]:
        """
        Close an open position and realise P&L.
        Returns the trade record or None if no position exists.
        """
        if symbol not in self.positions:
            logger.warning("No open position for %s", symbol)
            return None

        pos    = self.positions.pop(symbol)
        qty    = pos["quantity"]
        entry  = pos["entry_price"]
        action = pos["action"]

        if action == "BUY":
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty

        proceeds       = pos["position_value"] + pnl
        self.cash     += proceeds
        self.daily_pnl += pnl

        trade = {
            **pos,
            "exit_price": round(exit_price, 2),
            "pnl":        round(pnl, 2),
            "reason":     reason,
            "closed_at":  datetime.now(timezone.utc).isoformat(),
        }
        self.trade_log.append(trade)

        self._append_csv({
            "timestamp_ist":   datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S"),
            "symbol":          symbol,
            "action":          action,
            "entry_price":     entry,
            "quantity":        qty,
            "stop_loss":       pos["stop_loss"],
            "target":          pos["take_profit"],
            "confidence":      round(pos.get("confidence", 0.0), 3),
            "ai_source":       pos.get("ai_source", "unknown"),
            "composite_score": round(pos.get("composite_score", 0.0), 4),
            "status":          "CLOSED",
            "pnl":             round(pnl, 2),
        })

        logger.info(
            "CLOSED %s: exit=₹%.2f | P&L=₹%.2f | reason=%s | balance=₹%.0f",
            symbol, exit_price, pnl, reason, self.cash,
        )
        self._save_state()
        return trade

    def check_positions(self, prices: dict[str, float]) -> list[dict]:
        """
        Iterate open positions and auto-close any that hit SL or TP.
        `prices` is a dict {symbol: current_price}.
        Returns list of closed trade records.
        """
        closed = []
        for sym, pos in list(self.positions.items()):
            price = prices.get(sym)
            if price is None:
                continue
            trigger = check_stop_or_target(pos, price)
            if trigger:
                record = self.close_position(sym, price, reason=trigger)
                if record:
                    closed.append(record)
        return closed

    def portfolio_snapshot(self, prices: dict[str, float]) -> dict:
        """Current portfolio value + unrealised P&L."""
        unrealised = 0.0
        open_positions_detail = []

        for sym, pos in self.positions.items():
            price  = prices.get(sym, pos["entry_price"])
            qty    = pos["quantity"]
            action = pos["action"]

            if action == "BUY":
                upnl = (price - pos["entry_price"]) * qty
            else:
                upnl = (pos["entry_price"] - price) * qty

            unrealised += upnl
            open_positions_detail.append({
                "symbol":      sym,
                "action":      action,
                "qty":         qty,
                "entry":       pos["entry_price"],
                "current":     price,
                "upnl":        round(upnl, 2),
                "stop_loss":   pos["stop_loss"],
                "take_profit": pos["take_profit"],
            })

        total_value = self.cash + sum(
            p["quantity"] * prices.get(p["symbol"], p["entry_price"])
            for p in self.positions.values()
        )

        return {
            "cash":                  round(self.cash, 2),
            "total_value":           round(total_value, 2),
            "unrealised_pnl":        round(unrealised, 2),
            "daily_pnl":             round(self.daily_pnl, 2),
            "open_positions":        len(self.positions),
            "open_positions_detail": open_positions_detail,
            "total_trades":          len(self.trade_log),
            "starting_balance":      self.starting_balance,
            "return_pct": round(
                (total_value - self.starting_balance) / self.starting_balance * 100, 2
            ),
        }

    def reset_daily_pnl(self):
        """Call at market open each day."""
        self.daily_pnl = 0.0
        self._save_state()

    def close_all_positions(self, prices: dict[str, float], reason: str = "EOD"):
        """Force-close all open positions at EOD."""
        for sym in list(self.positions.keys()):
            price = prices.get(sym)
            if price:
                self.close_position(sym, price, reason=reason)

    def close_stale_positions(
        self, prices: dict, max_hours: float, reason: str = "STALE"
    ) -> list[dict]:
        """Force-close positions held longer than max_hours. Returns closed records."""
        if max_hours <= 0:
            return []
        now    = datetime.now(timezone.utc)
        closed = []
        for sym, pos in list(self.positions.items()):
            try:
                opened_at = datetime.fromisoformat(pos["opened_at"])
                if opened_at.tzinfo is None:        # legacy naive-UTC strings
                    opened_at = opened_at.replace(tzinfo=timezone.utc)
            except (ValueError, KeyError):
                continue
            age_hours = (now - opened_at).total_seconds() / 3600
            if age_hours >= max_hours:
                price = prices.get(sym)
                if price:
                    logger.warning(
                        "Stale position %s: age=%.1fh >= %.0fh limit — closing",
                        sym, age_hours, max_hours,
                    )
                    record = self.close_position(sym, price, reason=reason)
                    if record:
                        closed.append(record)
        return closed

    # ------------------------------------------------------------------
    # CSV logging
    # ------------------------------------------------------------------

    def _append_csv(self, row: dict):
        os.makedirs(LOG_DIR, exist_ok=True)
        write_header = not os.path.exists(TRADES_CSV) or os.path.getsize(TRADES_CSV) == 0
        try:
            with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_CSV_HEADERS, extrasaction="ignore")
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
        except Exception as exc:
            logger.error("Failed to write trades.csv: %s", exc)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        state = {
            "cash":      self.cash,
            "positions": self.positions,
            "trade_log": self.trade_log,
            "daily_pnl": self.daily_pnl,
        }
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as exc:
            logger.error("Failed to save state: %s", exc)

    def _load_state(self):
        if not os.path.exists(STATE_FILE):
            self._recover_positions_from_csv()
            return
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.cash      = state.get("cash",      self.starting_balance)
            self.positions = state.get("positions", {})
            self.trade_log = state.get("trade_log", [])
            self.daily_pnl = state.get("daily_pnl", 0.0)
            logger.info(
                "Restored state: cash=₹%.0f, positions=%d",
                self.cash, len(self.positions),
            )
        except Exception as exc:
            logger.error("Failed to load state: %s — attempting CSV recovery", exc)
            self._recover_positions_from_csv()

    def _recover_positions_from_csv(self):
        """
        Rebuild open positions from trades.csv when paper_state.json is absent or corrupt.
        Walks the CSV in order: an OPEN row adds the position, a subsequent CLOSED row
        for the same symbol removes it.  Saves recovered state so the next run loads
        normally from paper_state.json.
        """
        if not os.path.exists(TRADES_CSV):
            return
        try:
            open_rows: dict = {}
            realised_pnl = 0.0
            with open(TRADES_CSV, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    sym = row.get("symbol", "")
                    if not sym:
                        continue
                    if row["status"] == "OPEN":
                        open_rows[sym] = row
                    elif row["status"] == "CLOSED":
                        open_rows.pop(sym, None)
                        realised_pnl += float(row.get("pnl") or 0)

            if not open_rows:
                return

            for sym, row in open_rows.items():
                entry = float(row["entry_price"])
                qty   = int(row["quantity"])
                self.positions[sym] = {
                    "symbol":          sym,
                    "action":          row["action"],
                    "entry_price":     entry,
                    "stop_loss":       float(row["stop_loss"]),
                    "take_profit":     float(row["target"]),
                    "quantity":        qty,
                    "position_value":  round(entry * qty, 2),
                    "risk_amount":     0.0,
                    "opened_at":       row["timestamp_ist"],
                    "confidence":      float(row.get("confidence") or 0),
                    "ai_source":       row.get("ai_source", "unknown"),
                    "composite_score": float(row.get("composite_score") or 0),
                }

            invested   = sum(p["position_value"] for p in self.positions.values())
            self.cash  = self.starting_balance + realised_pnl - invested
            logger.warning(
                "paper_state.json missing — recovered %d open position(s) from trades.csv; "
                "estimated cash ₹%.0f",
                len(self.positions), self.cash,
            )
            self._save_state()
        except Exception as exc:
            logger.error("CSV recovery failed: %s", exc)
