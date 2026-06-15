"""
Technical indicator calculations: VWAP, EMA, RSI, ATR, and composite signal.
All functions accept a pandas DataFrame with OHLCV columns.

Signals are continuous floats in [-1, +1] — not binary +1/0/-1.
This means the composite score actually varies and the threshold filter works.
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
# Continuous ORB signal  (-1.0 to +1.0)
# ---------------------------------------------------------------------------

def orb_signal(df: pd.DataFrame, orb_minutes: int = ORB_MINUTES) -> float:
    """
    Continuous breakout strength above/below the opening range.
    +1.0 → price is 1× ATR or more above ORB high (strong breakout)
    -1.0 → price is 1× ATR or more below ORB low (strong breakdown)
      0  → price is inside the opening range
    Values between 0 and ±1 reflect how far into the breakout price has moved.
    """
    today = df.index[-1].date()
    today_df = df[df.index.date == today]

    candles_needed = max(1, orb_minutes // 15)
    if len(today_df) <= candles_needed:
        return 0.0

    orb_high = today_df["High"].iloc[:candles_needed].max()
    orb_low  = today_df["Low"].iloc[:candles_needed].min()
    latest_close = today_df["Close"].iloc[-1]
    atr = calc_atr(today_df).iloc[-1]

    if pd.isna(atr) or atr == 0:
        return 0.0

    if latest_close > orb_high:
        strength = (latest_close - orb_high) / atr
        return float(min(strength, 1.0))
    if latest_close < orb_low:
        strength = (orb_low - latest_close) / atr
        return float(-min(strength, 1.0))
    return 0.0


# ---------------------------------------------------------------------------
# Continuous VWAP signal  (-1.0 to +1.0)
# ---------------------------------------------------------------------------

def vwap_signal(df: pd.DataFrame) -> float:
    """
    Continuous distance from VWAP normalized by band width.
    +1.0 → price at or above upper VWAP band (very extended above VWAP)
    -1.0 → price at or below lower VWAP band
      0  → price exactly at VWAP
    """
    vwap, upper, lower = calc_vwap_bands(df)
    last_close = df["Close"].iloc[-1]
    last_vwap  = vwap.iloc[-1]
    last_upper = upper.iloc[-1]
    last_lower = lower.iloc[-1]

    if pd.isna(last_vwap) or pd.isna(last_upper) or pd.isna(last_lower):
        return 0.0

    band_half = (last_upper - last_lower) / 2
    if band_half == 0:
        return 0.0

    raw = (last_close - last_vwap) / band_half
    return float(max(-1.0, min(1.0, raw)))


# ---------------------------------------------------------------------------
# Continuous Momentum signal  (-1.0 to +1.0)
# ---------------------------------------------------------------------------

def momentum_signal(df: pd.DataFrame) -> float:
    """
    Combines EMA crossover strength with RSI position.
    EMA component: how far fast EMA is above/below slow EMA (as % of price)
    RSI component: normalized RSI position (50 = neutral, 70 = strong, 30 = weak)
    Result is average of both, clipped to [-1, +1].
    """
    close    = df["Close"]
    ema_fast = calc_ema(close, EMA_FAST)
    ema_slow = calc_ema(close, EMA_SLOW)
    rsi      = calc_rsi(close)

    last_fast  = ema_fast.iloc[-1]
    last_slow  = ema_slow.iloc[-1]
    last_rsi   = rsi.iloc[-1]
    last_close = close.iloc[-1]

    if pd.isna(last_fast) or pd.isna(last_slow) or pd.isna(last_rsi) or last_close == 0:
        return 0.0

    # EMA component: % gap between fast and slow, scaled so 0.5% gap = ±0.5 signal
    ema_gap_pct = (last_fast - last_slow) / last_close
    ema_score   = float(max(-1.0, min(1.0, ema_gap_pct / 0.005)))

    # RSI component: (RSI - 50) / 30 maps 80→+1, 50→0, 20→-1
    rsi_score = float(max(-1.0, min(1.0, (last_rsi - 50) / 30)))

    return round((ema_score + rsi_score) / 2, 4)


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

    atr_val    = calc_atr(df).iloc[-1]
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
