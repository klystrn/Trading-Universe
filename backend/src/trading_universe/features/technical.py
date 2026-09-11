"""Technical indicators, implemented on pandas/numpy (spec section 23).

Every indicator returns ``None`` rather than a wrong number when it has
insufficient history. A strategy that receives ``None`` must decline to trade
rather than guessing - that is the whole point of the contract.
"""

from __future__ import annotations

from datetime import UTC

import numpy as np
import pandas as pd

from trading_universe.domain.market import Candle
from trading_universe.domain.snapshots import TechnicalSnapshot


def candles_to_frame(candles: list[Candle]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(
        {
            "timestamp": [c.timestamp for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
    ).set_index("timestamp")
    return df.sort_index()


# --- primitives ------------------------------------------------------------
def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # All-gain stretches produce inf/NaN; RSI is 100 there.
    return out.where(avg_loss > 0, 100.0).where(avg_gain > 0, out.fillna(50.0))


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def bollinger(series: pd.Series, window: int = 20, mult: float = 2.0):
    mid = sma(series, window)
    std = series.rolling(window, min_periods=window).std(ddof=0)
    upper = mid + mult * std
    lower = mid - mult * std
    width = (upper - lower) / mid.replace(0.0, np.nan)
    return mid, upper, lower, width


def rolling_vwap(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Rolling VWAP.

    True session VWAP needs intraday bars; on daily data this is the
    volume-weighted typical price over ``window`` sessions, which is what the
    'reclaim VWAP' confirmation check is comparing against.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (typical * df["volume"]).rolling(window, min_periods=window).sum()
    vol = df["volume"].rolling(window, min_periods=window).sum()
    return pv / vol.replace(0, np.nan)


def _last(series: pd.Series) -> float | None:
    if series.empty:
        return None
    value = series.iloc[-1]
    if pd.isna(value):
        return None
    return float(value)


def _nth_last(series: pd.Series, n: int) -> float | None:
    if len(series) <= n:
        return None
    value = series.iloc[-1 - n]
    if pd.isna(value):
        return None
    return float(value)


# --- pattern detection ------------------------------------------------------
def detect_swing_low(df: pd.DataFrame, lookback: int = 10) -> float | None:
    """Lowest low of the last ``lookback`` completed bars."""
    if len(df) < 2:
        return None
    window = df["low"].iloc[-min(lookback, len(df)) :]
    return float(window.min()) if not window.empty else None


def detect_swing_high(df: pd.DataFrame, lookback: int = 20) -> float | None:
    if len(df) < 2:
        return None
    window = df["high"].iloc[-min(lookback, len(df)) :]
    return float(window.max()) if not window.empty else None


def detect_higher_low(df: pd.DataFrame, lookback: int = 12) -> bool:
    """A recent trough that sits above the prior trough."""
    if len(df) < lookback + 4:
        return False
    lows = df["low"].iloc[-lookback:]
    mid = len(lows) // 2
    return bool(lows.iloc[mid:].min() > lows.iloc[:mid].min())


def detect_bullish_engulfing(df: pd.DataFrame) -> bool:
    if len(df) < 2:
        return False
    prev, cur = df.iloc[-2], df.iloc[-1]
    return bool(
        prev["close"] < prev["open"]
        and cur["close"] > cur["open"]
        and cur["close"] >= prev["open"]
        and cur["open"] <= prev["close"]
    )


def percentile_of_last(series: pd.Series, lookback: int) -> float | None:
    """Where the final value sits within its own ``lookback`` window, 0-100."""
    window = series.dropna().iloc[-lookback:]
    if len(window) < max(5, lookback // 4):
        return None
    current = window.iloc[-1]
    return float((window <= current).mean() * 100.0)


# --- snapshot ---------------------------------------------------------------
def build_technical_snapshot(
    ticker: str, candles: list[Candle], bb_lookback: int = 63
) -> TechnicalSnapshot:
    """Compute the full technical picture for one ticker."""
    df = candles_to_frame(candles)
    as_of = candles[-1].timestamp if candles else pd.Timestamp.now(tz=UTC).to_pydatetime()

    snap = TechnicalSnapshot(ticker=ticker, as_of=as_of, bars_available=len(df))
    if df.empty:
        return snap

    close = df["close"]
    snap.close = float(close.iloc[-1])
    snap.volume = int(df["volume"].iloc[-1])
    if len(close) > 1:
        snap.prev_close = float(close.iloc[-2])
        if snap.prev_close:
            snap.change_pct = round((snap.close - snap.prev_close) / snap.prev_close, 6)

    ema20 = ema(close, 20)
    dma50 = sma(close, 50)
    dma200 = sma(close, 200)
    rsi14 = rsi(close, 14)
    atr14 = atr(df, 14)
    _, bb_up, bb_lo, bb_w = bollinger(close, 20, 2.0)
    vwap20 = rolling_vwap(df, 20)

    snap.ema20 = _last(ema20)
    snap.dma50 = _last(dma50)
    snap.dma200 = _last(dma200)
    snap.rsi14 = _last(rsi14)
    snap.rsi14_prev = _nth_last(rsi14, 1)
    snap.atr14 = _last(atr14)
    snap.vwap = _last(vwap20)
    snap.bb_upper = _last(bb_up)
    snap.bb_lower = _last(bb_lo)
    snap.bb_width = _last(bb_w)
    snap.bb_width_percentile = percentile_of_last(bb_w, bb_lookback)
    # Compression is measured on the bar BEFORE the trigger: a squeeze that has
    # just broken out has, by definition, already widened its bands.
    snap.bb_width_percentile_prev = percentile_of_last(bb_w.iloc[:-1], bb_lookback)

    avg_vol_20 = sma(df["volume"].astype(float), 20)
    snap.avg_volume_20 = _last(avg_vol_20) or 0.0
    if snap.avg_volume_20 > 0:
        snap.volume_ratio = round(snap.volume / snap.avg_volume_20, 4)
    snap.avg_dollar_volume_20 = round(snap.avg_volume_20 * snap.close, 2)

    # Prior-bar extremes exclude today so "broke the 20-day high" means today's
    # price cleared a level that existed before today.
    if len(df) > 21:
        snap.high_20 = float(df["high"].iloc[-21:-1].max())
        snap.low_20 = float(df["low"].iloc[-21:-1].min())
        snap.broke_20d_high = snap.close > snap.high_20
        if snap.high_20 > 0:
            snap.pct_from_20d_high = round((snap.close - snap.high_20) / snap.high_20, 5)
    if len(df) > 252:
        snap.high_52w = float(df["high"].iloc[-252:].max())
        snap.low_52w = float(df["low"].iloc[-252:].min())

    snap.swing_low = detect_swing_low(df, 10)
    snap.swing_high = detect_swing_high(df, 20)

    # Trend flags
    if snap.dma50 is not None:
        snap.price_above_50dma = snap.close > snap.dma50
    if snap.dma200 is not None:
        snap.price_above_200dma = snap.close > snap.dma200
    if snap.dma50 is not None and snap.dma200 is not None:
        snap.dma50_above_dma200 = snap.dma50 > snap.dma200

    # Pullback proximity
    if snap.ema20:
        snap.ema20_pullback = abs(snap.close - snap.ema20) / snap.ema20 <= 0.02
    if snap.dma50:
        snap.dma50_pullback = abs(snap.close - snap.dma50) / snap.dma50 <= 0.025

    # 50DMA reclaim: below within the recent window, above now.
    if snap.dma50 is not None and len(df) > 21:
        recent_closes = close.iloc[-21:-1]
        recent_dma = dma50.iloc[-21:-1]
        below = (recent_closes < recent_dma).fillna(False)
        snap.recently_below_50dma = bool(below.any())
        snap.reclaimed_50dma = bool(snap.price_above_50dma and below.any())

    if snap.vwap is not None:
        snap.vwap_reclaimed = snap.close > snap.vwap

    if snap.bb_lower is not None and snap.bb_lower > 0:
        snap.near_lower_band = (snap.close - snap.bb_lower) / snap.bb_lower <= 0.02

    # ATR contracting / volume drying up
    atr_prev = _nth_last(atr14, 10)
    if snap.atr14 is not None and atr_prev:
        snap.atr_contracting = snap.atr14 < atr_prev
    vol_prev = _nth_last(avg_vol_20, 10)
    if snap.avg_volume_20 and vol_prev:
        snap.volume_declining = snap.avg_volume_20 < vol_prev

    # RSI behaviour
    rsi_window = rsi14.dropna().iloc[-10:]
    if not rsi_window.empty:
        snap.rsi_recently_oversold = bool(rsi_window.min() < 35.0)
    if snap.rsi14 is not None and snap.rsi14_prev is not None:
        snap.rsi_turning_up = snap.rsi14 > snap.rsi14_prev

    snap.higher_low = detect_higher_low(df, 12)
    snap.bullish_engulfing = detect_bullish_engulfing(df)

    return snap
