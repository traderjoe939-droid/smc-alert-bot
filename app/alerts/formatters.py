from __future__ import annotations

from app.models import Direction, Signal, SignalGrade
from app.strategy.engine import CHECK_LABELS


def _format_price(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def format_signal_alert(signal: Signal, *, price_decimals: int) -> str:
    if signal.grade == SignalGrade.A_PLUS:
        title = f"🟢 A+ {signal.direction.value}"
    else:
        title = f"🟢 A Possible {signal.direction.value}"

    risk_text = f"${signal.risk_usd:,.0f}"
    lines = [
        title,
        "",
        f"Pair: {signal.symbol}",
        f"Timeframe: {signal.timeframe}",
        "",
        f"Entry: {_format_price(signal.entry, price_decimals)}",
        f"SL: {_format_price(signal.stop_loss, price_decimals)}",
        "",
        f"TP1: {_format_price(signal.tp1, price_decimals)}",
        f"TP2: {_format_price(signal.tp2, price_decimals)}",
        f"TP3: {_format_price(signal.tp3, price_decimals)}",
        "",
        f"Risk: {risk_text}",
        f"Lot Size: {signal.lot_size:.2f} lots",
        "",
        f"Score: {signal.score}/6 ({signal.percentage}%)",
        "",
    ]
    for key, label in CHECK_LABELS.items():
        icon = "✅" if signal.checks[key] else "❌"
        lines.append(f"{icon} {label}")

    if signal.grade == SignalGrade.A:
        lines.extend(["", "No trade yet."])
    return "\n".join(lines)


def format_entry_alert(signal: Signal) -> str:
    return f"🔔 ENTRY TRIGGERED\n\nPair: {signal.symbol}\nDirection: {signal.direction.value}"


def format_target_alert(signal: Signal, target: str) -> str:
    return f"🎯 {target.upper()} HIT\n\nPair: {signal.symbol}\nDirection: {signal.direction.value}"


def format_stop_alert(signal: Signal) -> str:
    return f"🛑 SL HIT\n\nPair: {signal.symbol}\nDirection: {signal.direction.value}"


def format_invalidation_alert(signal: Signal) -> str:
    return f"⚠️ SETUP INVALIDATED\n\nPair: {signal.symbol}\nDirection: {signal.direction.value}"


def format_tracking_alert(signal: Signal) -> str:
    return (
        "✅ TRACKING ENABLED\n\n"
        f"Pair: {signal.symbol}\n"
        f"Direction: {signal.direction.value}\n"
        "The bot will now send entry, SL, TP1, TP2 and TP3 alerts."
    )
