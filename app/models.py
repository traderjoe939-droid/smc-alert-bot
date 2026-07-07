from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class Direction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class SignalGrade(StrEnum):
    A_PLUS = "A+"
    A = "A"


class SignalStatus(StrEnum):
    PLANNED = "planned"
    TRACKING = "tracking"
    ENTERED = "entered"
    TP1 = "tp1"
    TP2 = "tp2"
    TP3 = "tp3"
    STOPPED = "stopped"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


@dataclass(frozen=True)
class PriceZone:
    lower: float
    upper: float
    created_at: datetime
    source: str

    @property
    def midpoint(self) -> float:
        return (self.lower + self.upper) / 2.0


@dataclass
class Signal:
    signal_id: str
    symbol: str
    direction: Direction
    grade: SignalGrade
    timeframe: str
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    risk_usd: float
    lot_size: float
    actual_price_risk_usd: float
    score: int
    checks: dict[str, bool]
    missing_condition: str | None
    sweep_time: datetime
    zone_time: datetime
    created_at: datetime
    expires_at: datetime
    tracked: bool
    status: SignalStatus = SignalStatus.PLANNED
    entry_hit: bool = False
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    stop_hit: bool = False

    @property
    def percentage(self) -> int:
        return round((self.score / 6) * 100)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("direction", "grade", "status"):
            result[key] = str(result[key])
        for key in ("sweep_time", "zone_time", "created_at", "expires_at"):
            result[key] = result[key].astimezone(timezone.utc).isoformat()
        return result

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Signal":
        data = dict(payload)
        data["direction"] = Direction(data["direction"])
        data["grade"] = SignalGrade(data["grade"])
        data["status"] = SignalStatus(data.get("status", SignalStatus.PLANNED))
        for key in ("sweep_time", "zone_time", "created_at", "expires_at"):
            data[key] = datetime.fromisoformat(data[key])
        return cls(**data)
