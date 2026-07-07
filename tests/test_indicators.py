import pandas as pd

from app.strategy.indicators import resample_ohlc


def test_resample_m15_to_h1() -> None:
    index = pd.date_range("2026-01-01", periods=8, freq="15min", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": range(8),
            "high": [value + 1 for value in range(8)],
            "low": [value - 1 for value in range(8)],
            "close": [value + 0.5 for value in range(8)],
            "volume": [1] * 8,
        },
        index=index,
    )
    h1 = resample_ohlc(frame, "1h")
    assert len(h1) == 2
    assert h1.iloc[0]["open"] == 0
    assert h1.iloc[0]["high"] == 4
    assert h1.iloc[0]["low"] == -1
    assert h1.iloc[0]["close"] == 3.5
