from __future__ import annotations

import numpy as np
import pandas as pd


OHLC_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period, min_periods=period).mean()


def candle_body(frame: pd.DataFrame) -> pd.Series:
    return (frame["close"] - frame["open"]).abs()


def resample_ohlc(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    result = frame.resample(rule, label="left", closed="left").agg(OHLC_AGG)
    return result.dropna(subset=["open", "high", "low", "close"])


def is_bullish_displacement(frame: pd.DataFrame, position: int) -> bool:
    if position < 20:
        return False
    current = frame.iloc[position]
    atr_value = atr(frame).iloc[position]
    median_body = candle_body(frame).iloc[position - 20 : position].median()
    candle_range = current["high"] - current["low"]
    if not np.isfinite(atr_value) or atr_value <= 0 or median_body <= 0:
        return False
    close_location = (current["close"] - current["low"]) / candle_range if candle_range else 0
    return bool(
        current["close"] > current["open"]
        and candle_range >= 1.25 * atr_value
        and abs(current["close"] - current["open"]) >= 1.5 * median_body
        and close_location >= 0.75
    )


def is_bearish_displacement(frame: pd.DataFrame, position: int) -> bool:
    if position < 20:
        return False
    current = frame.iloc[position]
    atr_value = atr(frame).iloc[position]
    median_body = candle_body(frame).iloc[position - 20 : position].median()
    candle_range = current["high"] - current["low"]
    if not np.isfinite(atr_value) or atr_value <= 0 or median_body <= 0:
        return False
    close_location = (current["close"] - current["low"]) / candle_range if candle_range else 1
    return bool(
        current["close"] < current["open"]
        and candle_range >= 1.25 * atr_value
        and abs(current["close"] - current["open"]) >= 1.5 * median_body
        and close_location <= 0.25
    )
