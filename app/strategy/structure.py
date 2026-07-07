from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd


class Bias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class Swing:
    position: int
    timestamp: pd.Timestamp
    price: float
    kind: str


def confirmed_swings(frame: pd.DataFrame, left: int = 3, right: int = 3) -> tuple[list[Swing], list[Swing]]:
    highs: list[Swing] = []
    lows: list[Swing] = []
    if len(frame) < left + right + 1:
        return highs, lows

    for position in range(left, len(frame) - right):
        high = float(frame["high"].iloc[position])
        low = float(frame["low"].iloc[position])
        left_highs = frame["high"].iloc[position - left : position]
        right_highs = frame["high"].iloc[position + 1 : position + right + 1]
        left_lows = frame["low"].iloc[position - left : position]
        right_lows = frame["low"].iloc[position + 1 : position + right + 1]

        if high > float(left_highs.max()) and high > float(right_highs.max()):
            highs.append(Swing(position, frame.index[position], high, "high"))
        if low < float(left_lows.min()) and low < float(right_lows.min()):
            lows.append(Swing(position, frame.index[position], low, "low"))
    return highs, lows


def timeframe_bias(frame: pd.DataFrame) -> Bias:
    highs, lows = confirmed_swings(frame)
    if len(highs) < 2 or len(lows) < 2:
        return Bias.NEUTRAL

    higher_high = highs[-1].price > highs[-2].price
    higher_low = lows[-1].price > lows[-2].price
    lower_high = highs[-1].price < highs[-2].price
    lower_low = lows[-1].price < lows[-2].price

    if higher_high and higher_low:
        return Bias.BULLISH
    if lower_high and lower_low:
        return Bias.BEARISH
    return Bias.NEUTRAL


def combined_bias(h4: pd.DataFrame, h1: pd.DataFrame) -> Bias:
    h4_bias = timeframe_bias(h4)
    h1_bias = timeframe_bias(h1)
    if h4_bias == h1_bias and h4_bias != Bias.NEUTRAL:
        return h4_bias
    return Bias.NEUTRAL


def latest_swing_before(swings: list[Swing], position: int) -> Swing | None:
    candidates = [swing for swing in swings if swing.position < position]
    return candidates[-1] if candidates else None
