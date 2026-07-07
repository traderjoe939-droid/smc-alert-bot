from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Mapping


@dataclass(frozen=True)
class LotSizeResult:
    lot_size: float
    raw_lot_size: float
    actual_price_risk_usd: float
    risk_per_lot_usd: float
    was_capped: bool


def _round_down(value: float, step: float) -> float:
    if value < 0 or step <= 0:
        raise ValueError("value must be non-negative and step must be positive")
    value_d = Decimal(str(value))
    step_d = Decimal(str(step))
    units = (value_d / step_d).to_integral_value(rounding=ROUND_DOWN)
    return float(units * step_d)


def quote_currency_to_usd_factor(
    quote_currency: str,
    conversion_prices: Mapping[str, float],
) -> float:
    """Return USD value of one unit of the quote currency.

    Examples:
    - USD -> 1
    - JPY -> 1 / USDJPY
    - CAD -> 1 / USDCAD

    The MVP universe only needs USD, JPY, and CAD conversions. The generic
    inverse/direct logic also supports future symbols when a matching rate is
    supplied in conversion_prices.
    """

    quote = quote_currency.upper()
    if quote == "USD":
        return 1.0

    direct = f"{quote}/USD"
    inverse = f"USD/{quote}"

    if direct in conversion_prices:
        price = conversion_prices[direct]
        if price <= 0:
            raise ValueError(f"Invalid conversion price for {direct}")
        return price

    if inverse in conversion_prices:
        price = conversion_prices[inverse]
        if price <= 0:
            raise ValueError(f"Invalid conversion price for {inverse}")
        return 1.0 / price

    raise KeyError(f"Missing USD conversion rate for quote currency {quote}")


def calculate_lot_size(
    *,
    entry: float,
    stop_loss: float,
    risk_usd: float,
    contract_size: float,
    quote_currency: str,
    conversion_prices: Mapping[str, float],
    min_lot: float,
    max_lot: float,
    lot_step: float,
) -> LotSizeResult:
    """Calculate MT5-style Forex volume for fixed entry-to-stop price risk.

    Commission and spread are intentionally excluded. The final volume is
    rounded down so the planned market-price loss does not exceed risk_usd.
    """

    distance = abs(entry - stop_loss)
    if distance <= 0:
        raise ValueError("Entry and stop loss must be different")
    if risk_usd <= 0 or contract_size <= 0:
        raise ValueError("Risk and contract size must be positive")

    conversion_factor = quote_currency_to_usd_factor(
        quote_currency, conversion_prices
    )
    risk_per_lot_usd = distance * contract_size * conversion_factor
    if risk_per_lot_usd <= 0:
        raise ValueError("Calculated risk per lot is invalid")

    raw_lot = risk_usd / risk_per_lot_usd
    was_capped = raw_lot > max_lot
    bounded = min(raw_lot, max_lot)
    rounded = _round_down(bounded, lot_step)

    if rounded < min_lot:
        raise ValueError(
            f"Calculated lot size {rounded:.4f} is below broker minimum {min_lot}"
        )

    actual_risk = rounded * risk_per_lot_usd
    return LotSizeResult(
        lot_size=rounded,
        raw_lot_size=raw_lot,
        actual_price_risk_usd=actual_risk,
        risk_per_lot_usd=risk_per_lot_usd,
        was_capped=was_capped,
    )
