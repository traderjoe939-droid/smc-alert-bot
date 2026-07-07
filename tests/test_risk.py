import pytest

from app.risk import calculate_lot_size


def test_eurusd_fixed_400_risk() -> None:
    result = calculate_lot_size(
        entry=1.08740,
        stop_loss=1.08580,
        risk_usd=400,
        contract_size=100000,
        quote_currency="USD",
        conversion_prices={},
        min_lot=0.01,
        max_lot=100,
        lot_step=0.01,
    )
    assert result.lot_size == pytest.approx(2.50)
    assert result.actual_price_risk_usd == pytest.approx(400.0)


def test_usdjpy_conversion_and_round_down() -> None:
    result = calculate_lot_size(
        entry=155.000,
        stop_loss=154.800,
        risk_usd=400,
        contract_size=100000,
        quote_currency="JPY",
        conversion_prices={"USD/JPY": 155.0},
        min_lot=0.01,
        max_lot=100,
        lot_step=0.01,
    )
    assert result.lot_size == pytest.approx(3.10)
    assert result.actual_price_risk_usd <= 400


def test_below_minimum_lot_is_rejected() -> None:
    with pytest.raises(ValueError, match="below broker minimum"):
        calculate_lot_size(
            entry=1.0,
            stop_loss=0.5,
            risk_usd=10,
            contract_size=100000,
            quote_currency="USD",
            conversion_prices={},
            min_lot=0.01,
            max_lot=100,
            lot_step=0.01,
        )
