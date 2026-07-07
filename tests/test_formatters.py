from datetime import datetime, timedelta, timezone

from app.alerts.formatters import format_signal_alert
from app.models import Direction, Signal, SignalGrade, SignalStatus


def make_signal(grade: SignalGrade) -> Signal:
    now = datetime.now(timezone.utc)
    checks = {
        "htf_bias": True,
        "htf_key_zone": True,
        "liquidity_sweep": True,
        "displacement_choch": True,
        "retrace": grade == SignalGrade.A_PLUS,
        "clean_3r": True,
    }
    return Signal(
        signal_id="ABC123",
        symbol="EUR/USD",
        direction=Direction.BUY,
        grade=grade,
        timeframe="M15",
        entry=1.08740,
        stop_loss=1.08580,
        tp1=1.08900,
        tp2=1.09060,
        tp3=1.09220,
        risk_usd=400,
        lot_size=2.50,
        actual_price_risk_usd=400,
        score=6 if grade == SignalGrade.A_PLUS else 5,
        checks=checks,
        missing_condition=None if grade == SignalGrade.A_PLUS else "FVG / OB Retracement",
        sweep_time=now,
        zone_time=now,
        created_at=now,
        expires_at=now + timedelta(hours=6),
        tracked=grade == SignalGrade.A_PLUS,
        status=SignalStatus.ENTERED if grade == SignalGrade.A_PLUS else SignalStatus.PLANNED,
        entry_hit=grade == SignalGrade.A_PLUS,
    )


def test_a_plus_alert_is_clean() -> None:
    text = format_signal_alert(make_signal(SignalGrade.A_PLUS), price_decimals=5)
    assert text.startswith("🟢 A+ BUY")
    assert "Entry: 1.08740" in text
    assert "Lot Size: 2.50 lots" in text
    assert "Score: 6/6 (100%)" in text
    assert "No trade yet." not in text


def test_a_alert_says_no_trade_yet() -> None:
    text = format_signal_alert(make_signal(SignalGrade.A), price_decimals=5)
    assert text.startswith("🟢 A Possible BUY")
    assert "❌ FVG / OB Retracement" in text
    assert text.endswith("No trade yet.")
