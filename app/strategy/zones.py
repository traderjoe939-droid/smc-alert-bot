from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.models import Direction, PriceZone
from app.strategy.indicators import atr, is_bearish_displacement, is_bullish_displacement
from app.strategy.structure import confirmed_swings, latest_swing_before


@dataclass(frozen=True)
class ZoneCandidate:
    zone: PriceZone
    position: int


def find_fvgs(
    frame: pd.DataFrame,
    direction: Direction,
    *,
    min_atr_fraction: float = 0.10,
    max_age: int | None = None,
) -> list[ZoneCandidate]:
    results: list[ZoneCandidate] = []
    atr_values = atr(frame)
    start = max(2, len(frame) - max_age) if max_age else 2

    for position in range(start, len(frame)):
        a = frame.iloc[position - 2]
        c = frame.iloc[position]
        atr_value = float(atr_values.iloc[position])
        if atr_value <= 0 or pd.isna(atr_value):
            continue

        if direction == Direction.BUY and c["low"] > a["high"]:
            lower, upper = float(a["high"]), float(c["low"])
        elif direction == Direction.SELL and c["high"] < a["low"]:
            lower, upper = float(c["high"]), float(a["low"])
        else:
            continue

        if upper - lower < min_atr_fraction * atr_value:
            continue

        invalidated = False
        after = frame.iloc[position + 1 :]
        if direction == Direction.BUY and not after.empty:
            invalidated = bool((after["close"] < lower).any())
        elif direction == Direction.SELL and not after.empty:
            invalidated = bool((after["close"] > upper).any())
        if invalidated:
            continue

        results.append(
            ZoneCandidate(
                PriceZone(
                    lower=lower,
                    upper=upper,
                    created_at=frame.index[position].to_pydatetime(),
                    source="FVG",
                ),
                position,
            )
        )
    return results


def find_order_blocks(
    frame: pd.DataFrame,
    direction: Direction,
    *,
    max_age: int,
) -> list[ZoneCandidate]:
    """Find strict order blocks tied to displacement and structure break."""

    highs, lows = confirmed_swings(frame)
    results: list[ZoneCandidate] = []
    start = max(20, len(frame) - max_age)

    for displacement_position in range(start, len(frame)):
        if direction == Direction.BUY:
            if not is_bullish_displacement(frame, displacement_position):
                continue
            broken = latest_swing_before(highs, displacement_position)
            if broken is None or frame["close"].iloc[displacement_position] <= broken.price:
                continue
            opposite = [
                position
                for position in range(max(0, displacement_position - 3), displacement_position)
                if frame["close"].iloc[position] < frame["open"].iloc[position]
            ]
            if not opposite:
                continue
            ob_position = opposite[-1]
            row = frame.iloc[ob_position]
            lower, upper = float(row["low"]), float(row["open"])
            later = frame.iloc[displacement_position + 1 :]
            invalid = bool((later["close"] < lower).any()) if not later.empty else False
            midpoint_touched_before_last = (
                bool((later.iloc[:-1]["low"] <= (lower + upper) / 2).any())
                if len(later) > 1
                else False
            )
        else:
            if not is_bearish_displacement(frame, displacement_position):
                continue
            broken = latest_swing_before(lows, displacement_position)
            if broken is None or frame["close"].iloc[displacement_position] >= broken.price:
                continue
            opposite = [
                position
                for position in range(max(0, displacement_position - 3), displacement_position)
                if frame["close"].iloc[position] > frame["open"].iloc[position]
            ]
            if not opposite:
                continue
            ob_position = opposite[-1]
            row = frame.iloc[ob_position]
            lower, upper = float(row["open"]), float(row["high"])
            later = frame.iloc[displacement_position + 1 :]
            invalid = bool((later["close"] > upper).any()) if not later.empty else False
            midpoint_touched_before_last = (
                bool((later.iloc[:-1]["high"] >= (lower + upper) / 2).any())
                if len(later) > 1
                else False
            )

        if invalid or midpoint_touched_before_last or upper <= lower:
            continue

        results.append(
            ZoneCandidate(
                PriceZone(
                    lower=lower,
                    upper=upper,
                    created_at=frame.index[ob_position].to_pydatetime(),
                    source="OB",
                ),
                ob_position,
            )
        )
    return results


def select_entry_zone(
    fvg: ZoneCandidate | None,
    order_block: ZoneCandidate | None,
) -> PriceZone | None:
    if fvg and order_block:
        lower = max(fvg.zone.lower, order_block.zone.lower)
        upper = min(fvg.zone.upper, order_block.zone.upper)
        if lower < upper:
            return PriceZone(
                lower=lower,
                upper=upper,
                created_at=max(fvg.zone.created_at, order_block.zone.created_at),
                source="FVG+OB",
            )
    if fvg:
        return fvg.zone
    if order_block:
        return order_block.zone
    return None
