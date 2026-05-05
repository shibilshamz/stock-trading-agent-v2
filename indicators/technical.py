"""
Technical indicator calculations: VWAP, EMA, RSI, ATR, and composite signal.
All functions accept a pandas DataFrame with OHLCV columns.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    ATR_PERIOD,
    EMA_FAST,
    EMA_SLOW,
    MOMENTUM_RSI_OVERBOUGHT,
    MOMENTUM_RSI_OVERSOLD,
    MOMENTUM_RSI_PERIOD,
    ORB_MINUTES,
    SIGNAL_THRESHOLD,
    VWAP_BAND_STD,
    WEIGHT_MOMENTUM,
    WEIGHT_ORB,
    WEIGHT_VWAP,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core indicators
# ---------------------------------------------------------------------------

def calc_vwap(df: pd.DataFrame) -> pd.Series:
    """Intraday VWAP anchored to each calendar day."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    df2 = df.copy()
    df2["_tp"] = tp
    df2["_date"] = df2.index.date

    vwap_vals = []
    for date, group in df2.groupby("_date"):
        cum_tpv = (group["_tp"] * group["Volume"]).cumsum()
        cum_vol = group["Volume"].cumsum()
        vwap_vals.append(cum_tpv / cum_vol.replace(0, np.nan))

    return pd.concat(vwap_vals).reindex(df.index)


def calc_vwap_bands(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (vwap, upper_band, lower_band) using rolling std of typical price."""
    vwap = calc_vwap(df)
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    std = tp.rolling(20).std()
    return vwap, vwap + VWAP_BAND_STD * std, vwap - VWAP_BAND_STD * std


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = MOMENTUM_RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# ---------------------------------------------------------------------------
# ORB signal  (−1 / 0 / +1)
# ---------------------------------------------------------------------------

def orb_signal(df: pd.DataFrame, orb_minutes: int = ORB_MINUTES) -> int:
    """
    +1 → bullish breakout above opening-range high
    -1 → bearish breakdown below opening-range low
     0 → inside range or insufficient data
    """
    today = df.index[-1].date()
    today_df = df[df.index.date == today]

    candles_needed = max(1, orb_minutes // 15)
    if len(today_df) <= candles_needed:
        return 0

    orb_high = today_df["High"].iloc[:candles_needed].max()
    orb_low  = today_df["Low"].iloc[:candles_needed].min()
    latest_close = today_df["Close"].iloc[-1]

    if latest_close > orb_high:
        return 1
    if latest_close < orb_low:
        return -1
    return 0


# ---------------------------------------------------------------------------
# VWAP signal  (−1 / 0 / +1)
# ---------------------------------------------------------------------------

def vwap_signal(df: pd.DataFrame) -> int:
    """
    +1 → price above VWAP + momentum confirms
    -1 → price below VWAP
     0 → at VWAP or indeterminate
    """
    vwap, upper, lower = calc_vwap_bands(df)
    last_close = df["Close"].iloc[-1]
    last_vwap  = vwap.iloc[-1]

    if pd.isna(last_vwap):
        return 0
    if last_close > last_vwap:
        return 1
    if last_close < last_vwap:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Momentum signal  (−1 / 0 / +1)
# ---------------------------------------------------------------------------

def momentum_signal(df: pd.DataFrame) -> int:
    """
    EMA crossover combined with RSI confirmation.
    +1 → fast EMA > slow EMA AND RSI not overbought
    -1 → fast EMA < slow EMA AND RSI not oversold
     0 → mixed or neutral
    """
    close     = df["Close"]
    ema_fast  = calc_ema(close, EMA_FAST)
    ema_slow  = calc_ema(close, EMA_SLOW)
    rsi       = calc_rsi(close)

    last_fast = ema_fast.iloc[-1]
    last_slow = ema_slow.iloc[-1]
    last_rsi  = rsi.iloc[-1]

    if pd.isna(last_fast) or pd.isna(last_slow) or pd.isna(last_rsi):
        return 0

    bullish = last_fast > last_slow and last_rsi < MOMENTUM_RSI_OVERBOUGHT
    bearish = last_fast < last_slow and last_rsi > MOMENTUM_RSI_OVERSOLD

    if bullish:
        return 1
    if bearish:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Composite score
# ---------------------------------------------------------------------------

def composite_score(df: pd.DataFrame) -> dict:
    """
    Returns a dict with individual signals and the composite [-1, 1] score.
    A positive score above SIGNAL_THRESHOLD is a buy signal;
    below -SIGNAL_THRESHOLD is a sell/short signal.
    """
    orb  = orb_signal(df)
    vwap = vwap_signal(df)
    mom  = momentum_signal(df)

    score = WEIGHT_ORB * orb + WEIGHT_VWAP * vwap + WEIGHT_MOMENTUM * mom

    atr_val = calc_atr(df).iloc[-1]
    last_close = float(df["Close"].iloc[-1])

    return {
        "orb_signal":       orb,
        "vwap_signal":      vwap,
        "momentum_signal":  mom,
        "composite_score":  round(float(score), 4),
        "atr":              round(float(atr_val), 4) if not pd.isna(atr_val) else None,
        "last_close":       last_close,
        "action":           _action(score),
    }


def _action(score: float) -> str:
    if score >= SIGNAL_THRESHOLD:
        return "BUY"
    if score <= -SIGNAL_THRESHOLD:
        return "SELL"
    return "HOLD"
