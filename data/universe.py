"""
Morning universe scan: score the full Nifty-50 list and return top N symbols
based on overnight gap, volume rank, and ATR liquidity filter.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from config import (
    NIFTY50_SYMBOLS,
    NSE_SUFFIX,
    UNIVERSE_TOP_N,
    ATR_PERIOD,
)

logger = logging.getLogger(__name__)


def _fetch_snapshot(symbols: list[str]) -> pd.DataFrame:
    """Download last 5-day daily OHLCV for all symbols in one batch call."""
    tickers = [s + NSE_SUFFIX for s in symbols]
    # yfinance 1.x removed group_by and threads; MultiIndex is now (field, ticker)
    raw = yf.download(
        tickers,
        period="5d",
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    return raw


def _score_symbol(daily: pd.DataFrame) -> float:
    """
    Composite morning-scan score (0-1).
    Components:
      - Overnight gap magnitude (30 %)
      - Volume relative to 5-day avg (40 %)
      - ATR / price  — liquidity & volatility (30 %)
    """
    if daily is None or len(daily) < 3:
        return 0.0

    try:
        close  = daily["Close"].dropna()
        volume = daily["Volume"].dropna()
        high   = daily["High"].dropna()
        low    = daily["Low"].dropna()

        if len(close) < 2:
            return 0.0

        # Gap score: absolute % gap of latest open vs prev close, capped at 5 %
        prev_close = close.iloc[-2]
        today_open = daily["Open"].iloc[-1]
        gap_pct = abs((today_open - prev_close) / prev_close) if prev_close else 0
        gap_score = min(gap_pct / 0.05, 1.0)

        # Volume score: today's vol vs 5-day mean
        vol_mean = volume.mean()
        vol_ratio = (volume.iloc[-1] / vol_mean) if vol_mean else 1.0
        vol_score = min(vol_ratio / 3.0, 1.0)

        # ATR / price
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(min(ATR_PERIOD, len(tr))).mean().iloc[-1]
        atr_pct = (atr / close.iloc[-1]) if close.iloc[-1] else 0
        atr_score = min(atr_pct / 0.03, 1.0)   # normalise to 3 % ATR/price

        return round(0.30 * gap_score + 0.40 * vol_score + 0.30 * atr_score, 4)

    except Exception as exc:
        logger.debug("Scoring failed: %s", exc)
        return 0.0


def get_trading_universe() -> list[str]:
    """
    Return top-N NSE symbols from Nifty 50 ranked by morning scan score.
    Strips the .NS suffix so every module can append it as needed.
    """
    logger.info("Running morning universe scan on %d symbols …", len(NIFTY50_SYMBOLS))

    raw = _fetch_snapshot(NIFTY50_SYMBOLS)
    scores: dict[str, float] = {}

    for sym in NIFTY50_SYMBOLS:
        ticker = sym + NSE_SUFFIX
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                # yfinance 1.x: MultiIndex is (field, ticker) — xs slices by ticker on level 1
                if ticker in raw.columns.get_level_values(1):
                    sym_data = raw.xs(ticker, axis=1, level=1)
                else:
                    sym_data = None
            else:
                sym_data = raw  # single-ticker fallback
            scores[sym] = _score_symbol(sym_data)
        except Exception as exc:
            logger.debug("Skip %s: %s", sym, exc)
            scores[sym] = 0.0

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top = [sym for sym, _ in ranked[:UNIVERSE_TOP_N]]

    logger.info(
        "Universe selected (%d): %s",
        len(top),
        ", ".join(f"{s}({scores[s]:.2f})" for s in top),
    )
    return top
