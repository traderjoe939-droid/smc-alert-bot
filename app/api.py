from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.alerts.formatters import format_signal_alert
from app.alerts.telegram import TelegramClient
from app.data.twelve_data import TwelveDataClient
from app.risk import calculate_lot_size
from app.settings import Settings, get_settings
from app.strategy.engine import StrategyEngine
from app.strategy.indicators import resample_ohlc


logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

class LotSizeRequest(BaseModel):
    symbol: str = Field(examples=["EUR/USD"])
    entry: float
    stop_loss: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.data = TwelveDataClient(settings.twelve_data_api_key.get_secret_value())
    app.state.telegram = TelegramClient(
        settings.telegram_bot_token.get_secret_value(), settings.telegram_chat_id
    )
    app.state.engine = StrategyEngine()
    yield
    await app.state.data.close()
    await app.state.telegram.close()


app = FastAPI(
    title="SMC Alert Bot API",
    version="0.1.0",
    description="Testing API for the SMC liquidity-sweep Telegram alert MVP.",
    lifespan=lifespan,
)


def require_auth(
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    configured = settings.api_auth_token.get_secret_value()
    if not configured:
        raise HTTPException(503, "API_AUTH_TOKEN is not configured")
    if authorization != f"Bearer {configured}":
        raise HTTPException(401, "Invalid bearer token")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/test/telegram", dependencies=[Depends(require_auth)])
async def test_telegram() -> dict[str, str]:
    await app.state.telegram.send_message("✅ Telegram test successful")
    return {"status": "sent"}


@app.get("/test/market/{symbol:path}", dependencies=[Depends(require_auth)])
async def test_market(symbol: str) -> dict[str, object]:
    frame = await app.state.data.get_time_series(symbol, "15min", 5)
    return {
        "symbol": symbol,
        "candles": [
            {"datetime": timestamp.isoformat(), **row.to_dict()}
            for timestamp, row in frame.iterrows()
        ],
    }


@app.post("/test/lot-size", dependencies=[Depends(require_auth)])
async def test_lot_size(payload: LotSizeRequest) -> dict[str, object]:
    settings = app.state.settings
    symbols = settings.load_symbol_config()
    if payload.symbol not in symbols:
        raise HTTPException(404, "Unknown or disabled symbol")
    config = symbols[payload.symbol]
    conversion_prices: dict[str, float] = {}
    quote = str(config["quote_currency"])
    if quote != "USD":
        pair = f"USD/{quote}"
        conversion_prices[pair] = await app.state.data.get_latest_price(pair)
    result = calculate_lot_size(
        entry=payload.entry,
        stop_loss=payload.stop_loss,
        risk_usd=settings.risk_per_trade_usd,
        contract_size=float(config["contract_size"]),
        quote_currency=quote,
        conversion_prices=conversion_prices,
        min_lot=float(config["min_lot"]),
        max_lot=float(config["max_lot"]),
        lot_step=float(config["lot_step"]),
    )
    return result.__dict__


@app.post("/test/scan/{symbol:path}", dependencies=[Depends(require_auth)])
async def test_scan(
    symbol: str,
    send: bool = Query(False, description="Send the qualifying alert to Telegram"),
) -> dict[str, object]:
    settings = app.state.settings
    symbols = settings.load_symbol_config()
    if symbol not in symbols:
        raise HTTPException(404, "Unknown or disabled symbol")

    m15 = await app.state.data.get_time_series(
        symbol, "15min", settings.scan_output_size
    )
    h1 = resample_ohlc(m15, "1h")
    h4 = resample_ohlc(m15, "4h")
    conversion_prices: dict[str, float] = {
        pair: await app.state.data.get_latest_price(pair)
        for pair in ("USD/JPY", "USD/CAD")
    }
    evaluation = app.state.engine.evaluate(
        symbol=symbol,
        m15=m15,
        h1=h1,
        h4=h4,
        m5=None,
        symbol_config=symbols[symbol],
        conversion_prices=conversion_prices,
        risk_usd=settings.risk_per_trade_usd,
    )
    if evaluation.needs_m5_confirmation:
        m5 = await app.state.data.get_time_series(symbol, "5min", 120)
        evaluation = app.state.engine.evaluate(
            symbol=symbol,
            m15=m15,
            h1=h1,
            h4=h4,
            m5=m5,
            symbol_config=symbols[symbol],
            conversion_prices=conversion_prices,
            risk_usd=settings.risk_per_trade_usd,
        )

    if send and evaluation.signal:
        decimals = int(symbols[symbol]["price_decimals"])
        await app.state.telegram.send_message(
            format_signal_alert(evaluation.signal, price_decimals=decimals)
        )
    return evaluation.to_dict()
