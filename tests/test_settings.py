from app.settings import Settings


def test_symbols_csv_parses() -> None:
    settings = Settings(SYMBOLS="EUR/USD, GBP/USD")
    assert settings.symbols == ["EUR/USD", "GBP/USD"]
