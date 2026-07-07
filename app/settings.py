from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and config/symbols.yaml."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    twelve_data_api_key: SecretStr = Field(default=SecretStr(""))
    telegram_bot_token: SecretStr = Field(default=SecretStr(""))
    telegram_chat_id: str = ""
    api_auth_token: SecretStr = Field(default=SecretStr(""))

    account_currency: str = "USD"
    risk_per_trade_usd: float = 400.0
    symbols_csv: str = Field(
        default="EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD,GBP/JPY",
        validation_alias="SYMBOLS",
    )
    scan_output_size: int = 500
    scan_grace_seconds: int = 20
    enable_websocket: bool = True
    send_startup_message: bool = True
    state_db_path: str = "./smc_state.sqlite3"
    log_level: str = "INFO"
    symbol_config_path: str = "config/symbols.yaml"

    @property
    def symbols(self) -> list[str]:
        return [part.strip() for part in self.symbols_csv.split(",") if part.strip()]

    @field_validator("account_currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    def require_market_data(self) -> None:
        if not self.twelve_data_api_key.get_secret_value():
            raise RuntimeError("TWELVE_DATA_API_KEY is not configured")

    def require_telegram(self) -> None:
        if not self.telegram_bot_token.get_secret_value() or not self.telegram_chat_id:
            raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    def load_symbol_config(self) -> dict[str, dict[str, Any]]:
        path = Path(self.symbol_config_path)
        if not path.exists():
            raise FileNotFoundError(f"Symbol config not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        configured = raw.get("symbols", {})
        return {
            symbol: details
            for symbol, details in configured.items()
            if details.get("enabled", False) and symbol in self.symbols
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
