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
      - Overnight gap magnitude (30%)
      - Volume relative to 5-day avg (40%)
      - EMA slope direction over 3 days — trending up scores higher (30%)
    """
    if daily is None or len(daily) < 3:
        return 0.0

    try:
        close  = daily["Close"].dropna()
        volume = daily["Volume"].dropna()

        if len(close) < 2:
            return 0.0

        # Gap score: absolute % gap of latest open vs prev close, capped at 5%
        prev_close = close.iloc[-2]
        today_open = daily["Open"].iloc[-1]
        gap_pct = abs((today_open - prev_close) / prev_close) if prev_close else 0
        gap_score = min(gap_pct / 0.05, 1.0)

        # Volume score: today's vol vs 5-day mean
        vol_mean = volume.mean()
        vol_ratio = (volume.iloc[-1] / vol_mean) if vol_mean else 1.0
        vol_score = min(vol_ratio / 3.0, 1.0)

        # Trend score: replace ATR/price with EMA slope direction over last 3 days
        # Positive slope = trending up = better ORB candidate
        if len(close) >= 3:
            ema = close.ewm(span=9, adjust=False).mean()
            slope = (ema.iloc[-1] - ema.iloc[-3]) / ema.iloc[-3] if ema.iloc[-3] else 0
            trend_score = min(abs(slope) / 0.02, 1.0) if slope > 0 else 0.0
        else:
            trend_score = 0.0

        return round(0.30 * gap_score + 0.40 * vol_score + 0.30 * trend_score, 4)

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
