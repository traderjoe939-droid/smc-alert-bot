from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pandas as pd

from app.models import Direction, PriceZone, Signal, SignalGrade, SignalStatus
from app.risk import calculate_lot_size
from app.strategy.indicators import atr, is_bearish_displacement, is_bullish_displacement
from app.strategy.structure import Bias, combined_bias, confirmed_swings, latest_swing_before
from app.strategy.zones import ZoneCandidate, find_fvgs, find_order_blocks, select_entry_zone


CHECK_LABELS = {
    "htf_bias": "HTF Bias",
    "htf_key_zone": "HTF Key Zone",
    "liquidity_sweep": "Liquidity Sweep",
    "displacement_choch": "Displacement + CHoCH",
    "retrace": "FVG / OB Retracement",
    "clean_3r": "Clean 3R Path",
}
CORE_CHECKS = ("htf_bias", "liquidity_sweep", "displacement_choch")


@dataclass
class StrategyEvaluation:
    symbol: str
    direction: Direction | None
    checks: dict[str, bool]
    score: int
    needs_m5_confirmation: bool
    reason: str
    signal: Signal | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction.value if self.direction else None,
            "checks": self.checks,
            "score": self.score,
            "needs_m5_confirmation": self.needs_m5_confirmation,
            "reason": self.reason,
            "signal": self.signal.to_dict() if self.signal else None,
        }


@dataclass(frozen=True)
class SweepContext:
    position: int
    recovery_position: int
    reference_position: int
    reference_price: float
    extreme: float
    structure_price: float
    timestamp: pd.Timestamp


@dataclass(frozen=True)
class LegContext:
    displacement_position: int
    zone: PriceZone
    touch_timestamp: pd.Timestamp | None


class StrategyEngine:
    def evaluate(
        self,
        *,
        symbol: str,
        m15: pd.DataFrame,
        h1: pd.DataFrame,
        h4: pd.DataFrame,
        m5: pd.DataFrame | None,
        symbol_config: Mapping[str, Any],
        conversion_prices: Mapping[str, float],
        risk_usd: float = 400.0,
        now: datetime | None = None,
    ) -> StrategyEvaluation:
        now = now or datetime.now(timezone.utc)
        empty_checks = {key: False for key in CHECK_LABELS}
        if min(len(m15), len(h1), len(h4)) < 30:
            return StrategyEvaluation(
                symbol, None, empty_checks, 0, False, "Insufficient candle history"
            )

        bias = combined_bias(h4, h1)
        if bias == Bias.NEUTRAL:
            return StrategyEvaluation(
                symbol, None, empty_checks, 0, False, "H4 and H1 bias are not aligned"
            )
        direction = Direction.BUY if bias == Bias.BULLISH else Direction.SELL
        checks = dict(empty_checks)
        checks["htf_bias"] = True

        sweep = self._find_latest_sweep(m15, direction)
        if sweep is None:
            return StrategyEvaluation(
                symbol, direction, checks, 1, False, "No valid recent M15 liquidity sweep"
            )
        checks["liquidity_sweep"] = True
        checks["htf_key_zone"] = self._valid_htf_zone(
            price=sweep.extreme,
            direction=direction,
            h1=h1,
            h4=h4,
        )

        leg = self._find_leg(m15, direction, sweep)
        if leg is None:
            score = sum(checks.values())
            return StrategyEvaluation(
                symbol,
                direction,
                checks,
                score,
                False,
                "Sweep found, but displacement/CHoCH or entry zone is incomplete",
            )
        checks["displacement_choch"] = True

        entry = leg.zone.midpoint
        m15_atr = float(atr(m15).iloc[-1])
        if pd.isna(m15_atr) or m15_atr <= 0:
            return StrategyEvaluation(
                symbol, direction, checks, sum(checks.values()), False, "ATR unavailable"
            )
        minimum_stop_distance = float(symbol_config.get("minimum_stop_distance", 0.0))
        buffer = max(0.10 * m15_atr, minimum_stop_distance)
        if direction == Direction.BUY:
            stop_loss = sweep.extreme - buffer
            risk_distance = entry - stop_loss
            tp1, tp2, tp3 = (
                entry + risk_distance,
                entry + 2 * risk_distance,
                entry + 3 * risk_distance,
            )
        else:
            stop_loss = sweep.extreme + buffer
            risk_distance = stop_loss - entry
            tp1, tp2, tp3 = (
                entry - risk_distance,
                entry - 2 * risk_distance,
                entry - 3 * risk_distance,
            )

        if risk_distance <= 0:
            return StrategyEvaluation(
                symbol,
                direction,
                checks,
                sum(checks.values()),
                False,
                "Entry zone is on the wrong side of the structural stop",
            )

        checks["clean_3r"] = self._clean_3r_path(
            direction=direction,
            entry=entry,
            tp3=tp3,
            m15=m15,
            h1=h1,
        )

        touched = leg.touch_timestamp is not None
        needs_m5 = touched and m5 is None
        checks["retrace"] = touched and self._m5_confirmation(
            direction=direction,
            midpoint=entry,
            stop_loss=stop_loss,
            touch_timestamp=leg.touch_timestamp,
            m5=m5,
        )

        score = sum(checks.values())
        if not all(checks[key] for key in CORE_CHECKS):
            return StrategyEvaluation(
                symbol, direction, checks, score, needs_m5, "A core condition is missing"
            )
        if score < 5:
            return StrategyEvaluation(
                symbol, direction, checks, score, needs_m5, "Setup is below A grade"
            )

        grade = SignalGrade.A_PLUS if score == 6 else SignalGrade.A
        missing_key = next((key for key, passed in checks.items() if not passed), None)
        missing = CHECK_LABELS[missing_key] if missing_key else None

        lot_result = calculate_lot_size(
            entry=entry,
            stop_loss=stop_loss,
            risk_usd=risk_usd,
            contract_size=float(symbol_config["contract_size"]),
            quote_currency=str(symbol_config["quote_currency"]),
            conversion_prices=conversion_prices,
            min_lot=float(symbol_config["min_lot"]),
            max_lot=float(symbol_config["max_lot"]),
            lot_step=float(symbol_config["lot_step"]),
        )

        zone_time = leg.zone.created_at
        signal_id = self._signal_id(symbol, direction, sweep.timestamp, zone_time)
        signal = Signal(
            signal_id=signal_id,
            symbol=symbol,
            direction=direction,
            grade=grade,
            timeframe="M15",
            entry=entry,
            stop_loss=stop_loss,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            risk_usd=risk_usd,
            lot_size=lot_result.lot_size,
            actual_price_risk_usd=lot_result.actual_price_risk_usd,
            score=score,
            checks=checks,
            missing_condition=missing,
            sweep_time=sweep.timestamp.to_pydatetime(),
            zone_time=zone_time,
            created_at=now,
            expires_at=now + timedelta(hours=6),
            tracked=grade == SignalGrade.A_PLUS,
            status=SignalStatus.ENTERED if grade == SignalGrade.A_PLUS else SignalStatus.PLANNED,
            entry_hit=grade == SignalGrade.A_PLUS,
        )
        return StrategyEvaluation(
            symbol=symbol,
            direction=direction,
            checks=checks,
            score=score,
            needs_m5_confirmation=needs_m5,
            reason=f"{grade.value} setup",
            signal=signal,
        )

    def _find_latest_sweep(
        self, frame: pd.DataFrame, direction: Direction
    ) -> SweepContext | None:
        highs, lows = confirmed_swings(frame)
        atr_values = atr(frame)
        start = max(7, len(frame) - 16)
        candidates: list[SweepContext] = []

        for position in range(start, len(frame)):
            atr_value = float(atr_values.iloc[position])
            if pd.isna(atr_value) or atr_value <= 0:
                continue

            if direction == Direction.BUY:
                reference = latest_swing_before(lows, position)
                structure = latest_swing_before(highs, position)
                if not reference or not structure or position - reference.position > 50:
                    continue
                extreme = float(frame["low"].iloc[position])
                swept = extreme <= reference.price - 0.05 * atr_value
                same_recovery = float(frame["close"].iloc[position]) > reference.price
                next_recovery = (
                    position + 1 < len(frame)
                    and float(frame["close"].iloc[position + 1]) > reference.price
                )
            else:
                reference = latest_swing_before(highs, position)
                structure = latest_swing_before(lows, position)
                if not reference or not structure or position - reference.position > 50:
                    continue
                extreme = float(frame["high"].iloc[position])
                swept = extreme >= reference.price + 0.05 * atr_value
                same_recovery = float(frame["close"].iloc[position]) < reference.price
                next_recovery = (
                    position + 1 < len(frame)
                    and float(frame["close"].iloc[position + 1]) < reference.price
                )

            if not swept or not (same_recovery or next_recovery):
                continue
            recovery_position = position if same_recovery else position + 1
            candidates.append(
                SweepContext(
                    position=position,
                    recovery_position=recovery_position,
                    reference_position=reference.position,
                    reference_price=reference.price,
                    extreme=extreme,
                    structure_price=structure.price,
                    timestamp=frame.index[position],
                )
            )
        return candidates[-1] if candidates else None

    def _find_leg(
        self,
        frame: pd.DataFrame,
        direction: Direction,
        sweep: SweepContext,
    ) -> LegContext | None:
        last_position = min(len(frame) - 1, sweep.position + 3)
        displacement_position: int | None = None
        for position in range(sweep.position, last_position + 1):
            if direction == Direction.BUY:
                qualifies = is_bullish_displacement(frame, position) and float(
                    frame["close"].iloc[position]
                ) > sweep.structure_price
            else:
                qualifies = is_bearish_displacement(frame, position) and float(
                    frame["close"].iloc[position]
                ) < sweep.structure_price
            if qualifies:
                displacement_position = position
                break
        if displacement_position is None:
            return None

        fvg = self._entry_fvg(frame, direction, displacement_position)
        order_block = self._entry_order_block(frame, direction, displacement_position)
        zone = select_entry_zone(fvg, order_block)
        if zone is None:
            return None

        after_start = min(displacement_position + 1, len(frame))
        touch_timestamp: pd.Timestamp | None = None
        for position in range(after_start, len(frame)):
            row = frame.iloc[position]
            if direction == Direction.BUY:
                invalid = float(row["close"]) < zone.lower
                touched = float(row["low"]) <= zone.midpoint
            else:
                invalid = float(row["close"]) > zone.upper
                touched = float(row["high"]) >= zone.midpoint
            if invalid:
                break
            if touched:
                touch_timestamp = frame.index[position]
                break
        return LegContext(displacement_position, zone, touch_timestamp)

    def _entry_fvg(
        self,
        frame: pd.DataFrame,
        direction: Direction,
        displacement_position: int,
    ) -> ZoneCandidate | None:
        atr_values = atr(frame)
        for position in (displacement_position, displacement_position + 1):
            if position < 2 or position >= len(frame):
                continue
            a = frame.iloc[position - 2]
            c = frame.iloc[position]
            atr_value = float(atr_values.iloc[position])
            if pd.isna(atr_value) or atr_value <= 0:
                continue
            if direction == Direction.BUY and c["low"] > a["high"]:
                lower, upper = float(a["high"]), float(c["low"])
            elif direction == Direction.SELL and c["high"] < a["low"]:
                lower, upper = float(c["high"]), float(a["low"])
            else:
                continue
            if upper - lower >= 0.10 * atr_value:
                return ZoneCandidate(
                    PriceZone(
                        lower=lower,
                        upper=upper,
                        created_at=frame.index[position].to_pydatetime(),
                        source="FVG",
                    ),
                    position,
                )
        return None

    def _entry_order_block(
        self,
        frame: pd.DataFrame,
        direction: Direction,
        displacement_position: int,
    ) -> ZoneCandidate | None:
        for position in range(displacement_position - 1, max(-1, displacement_position - 4), -1):
            if position < 0:
                break
            row = frame.iloc[position]
            if direction == Direction.BUY and row["close"] < row["open"]:
                return ZoneCandidate(
                    PriceZone(
                        lower=float(row["low"]),
                        upper=float(row["open"]),
                        created_at=frame.index[position].to_pydatetime(),
                        source="OB",
                    ),
                    position,
                )
            if direction == Direction.SELL and row["close"] > row["open"]:
                return ZoneCandidate(
                    PriceZone(
                        lower=float(row["open"]),
                        upper=float(row["high"]),
                        created_at=frame.index[position].to_pydatetime(),
                        source="OB",
                    ),
                    position,
                )
        return None

    def _valid_htf_zone(
        self,
        *,
        price: float,
        direction: Direction,
        h1: pd.DataFrame,
        h4: pd.DataFrame,
    ) -> bool:
        h4_highs, h4_lows = confirmed_swings(h4)
        if not h4_highs or not h4_lows:
            return False
        range_high = h4_highs[-1].price
        range_low = h4_lows[-1].price
        if range_high <= range_low:
            return False
        midpoint = (range_high + range_low) / 2
        lower_twenty = range_low + 0.20 * (range_high - range_low)
        upper_twenty = range_high - 0.20 * (range_high - range_low)

        h1_atr = float(atr(h1).iloc[-1])
        if pd.isna(h1_atr) or h1_atr <= 0:
            return False

        h1_fvgs = find_fvgs(h1, direction, max_age=100)
        h4_fvgs = find_fvgs(h4, direction, max_age=60)
        h1_obs = find_order_blocks(h1, direction, max_age=100)
        h4_obs = find_order_blocks(h4, direction, max_age=60)
        zones = [candidate.zone for candidate in h1_fvgs + h4_fvgs + h1_obs + h4_obs]
        near_zone = any(self._distance_to_zone(price, zone) <= 0.25 * h1_atr for zone in zones)

        if direction == Direction.BUY:
            return (price <= midpoint and near_zone) or price <= lower_twenty
        return (price >= midpoint and near_zone) or price >= upper_twenty

    @staticmethod
    def _distance_to_zone(price: float, zone: PriceZone) -> float:
        if zone.lower <= price <= zone.upper:
            return 0.0
        return min(abs(price - zone.lower), abs(price - zone.upper))

    @staticmethod
    def _m5_confirmation(
        *,
        direction: Direction,
        midpoint: float,
        stop_loss: float,
        touch_timestamp: pd.Timestamp | None,
        m5: pd.DataFrame | None,
    ) -> bool:
        if touch_timestamp is None or m5 is None or m5.empty:
            return False
        after = m5[m5.index >= touch_timestamp]
        for _, row in after.iterrows():
            if direction == Direction.BUY:
                if float(row["close"]) <= stop_loss:
                    return False
                if row["close"] > row["open"] and row["close"] >= midpoint:
                    return True
            else:
                if float(row["close"]) >= stop_loss:
                    return False
                if row["close"] < row["open"] and row["close"] <= midpoint:
                    return True
        return False

    @staticmethod
    def _clean_3r_path(
        *,
        direction: Direction,
        entry: float,
        tp3: float,
        m15: pd.DataFrame,
        h1: pd.DataFrame,
    ) -> bool:
        m15_highs, m15_lows = confirmed_swings(m15)
        h1_highs, h1_lows = confirmed_swings(h1)
        if direction == Direction.BUY:
            obstacles = [
                swing.price
                for swing in m15_highs + h1_highs
                if entry < swing.price < tp3
            ]
        else:
            obstacles = [
                swing.price
                for swing in m15_lows + h1_lows
                if tp3 < swing.price < entry
            ]
        return not obstacles

    @staticmethod
    def _signal_id(
        symbol: str,
        direction: Direction,
        sweep_time: pd.Timestamp,
        zone_time: datetime,
    ) -> str:
        raw = f"{symbol}|{direction.value}|{sweep_time.isoformat()}|{zone_time.isoformat()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12].upper()
