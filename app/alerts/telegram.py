from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, chat_id: str, timeout_seconds: float = 35.0) -> None:
        if not token or not chat_id:
            raise ValueError("Telegram token and chat ID are required")
        self.chat_id = str(chat_id)
        self._client = httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def send_message(self, text: str) -> dict[str, Any]:
        response = await self._client.post(
            "/sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise TelegramError(str(payload))
        return payload["result"]

    async def get_updates(
        self,
        *,
        offset: int | None,
        timeout: int = 25,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            params["offset"] = offset
        response = await self._client.get("/getUpdates", params=params)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise TelegramError(str(payload))
        return list(payload.get("result", []))

    async def command_messages(
        self,
        *,
        initial_offset: int | None = None,
    ) -> AsyncIterator[tuple[int, str]]:
        offset = initial_offset
        while True:
            try:
                updates = await self.get_updates(offset=offset)
                for update in updates:
                    update_id = int(update["update_id"])
                    offset = update_id + 1
                    message = update.get("message", {})
                    if str(message.get("chat", {}).get("id")) != self.chat_id:
                        continue
                    text = str(message.get("text", "")).strip()
                    if text.startswith("/"):
                        yield update_id, text
            except httpx.HTTPError as exc:
                LOGGER.warning("Telegram polling error: %r", exc)
