"""
Fetches and caches 15-minute OHLCV candles from yfinance for a list of NSE symbols.
"""

import logging
import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

import pandas as pd
import yfinance as yf

from config import (
    CANDLE_INTERVAL,
    CANDLE_LOOKBACK_DAYS,
    NSE_SUFFIX,
)

logger = logging.getLogger(__name__)

# Module-level cache: symbol → (fetch_epoch, DataFrame)
_cache: dict[str, tuple[float, pd.DataFrame]] = {}
CACHE_TTL_SECONDS = 60 * 14   # slightly under one candle interval


def _ticker(symbol: str) -> str:
    return symbol if symbol.endswith(NSE_SUFFIX) else symbol + NSE_SUFFIX


def fetch_candles(symbol: str, force: bool = False) -> Optional[pd.DataFrame]:
    """
    Return a DataFrame of 15-min candles for `symbol`.

    Columns: Open, High, Low, Close, Volume (DatetimeIndex in IST/UTC).
    Returns None if the download fails or produces empty data.
    """
    now = time.monotonic()
    if not force and symbol in _cache:
        ts, df = _cache[symbol]
        if now - ts < CACHE_TTL_SECONDS:
            return df

    ticker = _ticker(symbol)
    end    = datetime.utcnow()
    start  = end - timedelta(days=CANDLE_LOOKBACK_DAYS)

    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval=CANDLE_INTERVAL,
            auto_adjust=True,
            progress=False,
        )
    except Exception as exc:
        logger.error("yfinance error for %s: %s", symbol, exc)
        return None

    if df is None or df.empty:
        logger.warning("No data returned for %s", symbol)
        return None

    df.index = pd.to_datetime(df.index)

    # yfinance 1.x returns MultiIndex columns (field, ticker) even for single tickers
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    _cache[symbol] = (now, df)
    logger.debug("Fetched %d candles for %s", len(df), symbol)
    return df


def fetch_all(symbols: list[str]) -> dict[str, Optional[pd.DataFrame]]:
    """Fetch candles for multiple symbols; returns mapping symbol → DataFrame."""
    result: dict[str, Optional[pd.DataFrame]] = {}
    for sym in symbols:
        result[sym] = fetch_candles(sym)
    return result


def latest_price(symbol: str) -> Optional[float]:
    """Return the most-recent close price for a symbol."""
    df = fetch_candles(symbol)
    if df is None or df.empty:
        return None
    return float(df["Close"].iloc[-1])


def get_opening_range(symbol: str, orb_minutes: int = 30) -> Optional[dict]:
    """
    Return {"high": …, "low": …} for the first `orb_minutes` of today's session.
    Returns None when today's intraday data is unavailable.
    """
    df = fetch_candles(symbol)
    if df is None or df.empty:
        return None

    today = datetime.utcnow().date()
    today_df = df[df.index.date == today]

    if today_df.empty:
        return None

    candles_needed = orb_minutes // 15
    orb_df = today_df.iloc[:candles_needed]

    if orb_df.empty:
        return None

    return {
        "high": float(orb_df["High"].max()),
        "low":  float(orb_df["Low"].min()),
    }
