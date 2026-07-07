from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd
import websockets

LOGGER = logging.getLogger(__name__)


class TwelveDataError(RuntimeError):
    pass


class TwelveDataClient:
    REST_BASE = "https://api.twelvedata.com"
    WS_URL = "wss://ws.twelvedata.com/v1/quotes/price"

    def __init__(self, api_key: str, timeout_seconds: float = 20.0) -> None:
        if not api_key:
            raise ValueError("Twelve Data API key is required")
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self.REST_BASE,
            timeout=timeout_seconds,
            headers={"User-Agent": "smc-alert-bot/0.1"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_time_series(
        self,
        symbol: str,
        interval: str,
        outputsize: int,
        timezone_name: str = "UTC",
        retries: int = 3,
    ) -> pd.DataFrame:
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "timezone": timezone_name,
            "order": "asc",
            "format": "JSON",
            "apikey": self.api_key,
        }

        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                response = await self._client.get("/time_series", params=params)
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") == "error" or "values" not in payload:
                    raise TwelveDataError(
                        f"Twelve Data error for {symbol} {interval}: "
                        f"{payload.get('message', payload)}"
                    )
                return self._frame_from_values(payload["values"])
            except (httpx.HTTPError, ValueError, TwelveDataError) as exc:
                last_error = exc
                if attempt + 1 == retries:
                    break
                await asyncio.sleep(2**attempt)
        raise TwelveDataError(str(last_error))

    async def get_latest_price(self, symbol: str) -> float:
        response = await self._client.get(
            "/price", params={"symbol": symbol, "apikey": self.api_key}
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") == "error" or "price" not in payload:
            raise TwelveDataError(
                f"Twelve Data price error for {symbol}: {payload.get('message', payload)}"
            )
        return float(payload["price"])

    @staticmethod
    def _frame_from_values(values: list[dict[str, Any]]) -> pd.DataFrame:
        frame = pd.DataFrame(values)
        required = {"datetime", "open", "high", "low", "close"}
        missing = required - set(frame.columns)
        if missing:
            raise TwelveDataError(f"Missing candle fields: {sorted(missing)}")

        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
        for column in ("open", "high", "low", "close"):
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        if "volume" in frame.columns:
            frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
        else:
            frame["volume"] = 0.0

        frame = frame.sort_values("datetime").drop_duplicates("datetime")
        frame = frame.set_index("datetime")
        return frame[["open", "high", "low", "close", "volume"]]

    async def stream_prices(
        self,
        symbols: Iterable[str],
        *,
        stop_event: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield Twelve Data WebSocket events, reconnecting on disconnects.

        Basic accounts have trial WebSocket limits. If subscription fails, this
        generator raises TwelveDataError so the worker can notify Telegram and
        fall back to candle-close tracking.
        """

        symbol_text = ",".join(symbols)
        url = f"{self.WS_URL}?apikey={self.api_key}"
        backoff = 2

        while not (stop_event and stop_event.is_set()):
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_size=2**20,
                ) as websocket:
                    await websocket.send(
                        json.dumps(
                            {
                                "action": "subscribe",
                                "params": {"symbols": symbol_text},
                            }
                        )
                    )
                    backoff = 2
                    while not (stop_event and stop_event.is_set()):
                        raw = await asyncio.wait_for(websocket.recv(), timeout=60)
                        event = json.loads(raw)
                        if event.get("event") == "subscribe-status":
                            if event.get("status") != "ok" or event.get("fails"):
                                raise TwelveDataError(
                                    f"WebSocket subscription failed: {event}"
                                )
                            LOGGER.info("WebSocket subscribed: %s", event.get("success"))
                        elif event.get("event") == "price":
                            event["received_at"] = datetime.now(timezone.utc).isoformat()
                            yield event
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("WebSocket disconnected: %s", exc)
                if isinstance(exc, TwelveDataError):
                    raise
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
