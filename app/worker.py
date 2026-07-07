from __future__ import annotations

import asyncio
import logging
import signal as os_signal
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from app.alerts.formatters import (
    format_entry_alert,
    format_invalidation_alert,
    format_signal_alert,
    format_stop_alert,
    format_target_alert,
    format_tracking_alert,
)
from app.alerts.telegram import TelegramClient
from app.data.twelve_data import TwelveDataClient, TwelveDataError
from app.models import Direction, SignalGrade, SignalStatus
from app.settings import Settings, get_settings
from app.state import StateStore
from app.strategy.engine import StrategyEngine
from app.strategy.indicators import resample_ohlc

LOGGER = logging.getLogger(__name__)

# Prevent all six Twelve Data requests from being sent simultaneously.
API_REQUEST_SPACING_SECONDS = 1.25


class Worker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        settings.require_market_data()
        settings.require_telegram()

        self.symbol_config = settings.load_symbol_config()

        self.data = TwelveDataClient(
            settings.twelve_data_api_key.get_secret_value()
        )

        self.telegram = TelegramClient(
            settings.telegram_bot_token.get_secret_value(),
            settings.telegram_chat_id,
        )

        self.state = StateStore(settings.state_db_path)
        self.engine = StrategyEngine()
        self.stop_event = asyncio.Event()
        self.websocket_available = settings.enable_websocket

    async def close(self) -> None:
        self.stop_event.set()
        await self.data.close()
        await self.telegram.close()

    async def run(self) -> None:
        if self.settings.send_startup_message:
            await self.telegram.send_message(
                "✅ SMC alert worker started\n\n"
                f"Monitoring: {', '.join(self.symbol_config)}\n"
                "Risk: $400 price loss from entry to SL"
            )

        tasks = [
            asyncio.create_task(
                self.scan_loop(),
                name="scan-loop",
            ),
            asyncio.create_task(
                self.telegram_command_loop(),
                name="telegram-commands",
            ),
        ]

        if self.settings.enable_websocket:
            tasks.append(
                asyncio.create_task(
                    self.websocket_loop(),
                    name="websocket",
                )
            )

        try:
            await self.stop_event.wait()
        finally:
            for task in tasks:
                task.cancel()

            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

    async def scan_loop(self) -> None:
        await self.scan_once()

        while not self.stop_event.is_set():
            delay = self._seconds_until_next_scan()

            LOGGER.info(
                "Next M15 scan in %.0f seconds",
                delay,
            )

            try:
                await asyncio.wait_for(
                    self.stop_event.wait(),
                    timeout=delay,
                )
            except TimeoutError:
                pass

            if self.stop_event.is_set():
                return

            if self._forex_market_window(
                datetime.now(timezone.utc)
            ):
                await self.scan_once()
            else:
                LOGGER.info(
                    "Forex market window is closed; scan skipped"
                )

    async def scan_once(self) -> None:
        LOGGER.info(
            "Starting M15 scan for %d symbols",
            len(self.symbol_config),
        )

        frames = await self._fetch_m15_frames()

        if not frames:
            LOGGER.warning(
                "No M15 data was returned for any symbol"
            )
            return

        conversion_prices = {
            symbol: float(frame["close"].iloc[-1])
            for symbol, frame in frames.items()
            if symbol in {"USD/JPY", "USD/CAD"}
        }

        evaluations: dict[str, Any] = {}

        # Basic 8:
        # Six M15 calls plus at most two M5 calls per scan.
        m5_budget = 2

        for symbol, m15 in frames.items():
            try:
                h1 = resample_ohlc(m15, "1h")
                h4 = resample_ohlc(m15, "4h")

                evaluation = self.engine.evaluate(
                    symbol=symbol,
                    m15=m15,
                    h1=h1,
                    h4=h4,
                    m5=None,
                    symbol_config=self.symbol_config[symbol],
                    conversion_prices=conversion_prices,
                    risk_usd=self.settings.risk_per_trade_usd,
                )

                if (
                    evaluation.needs_m5_confirmation
                    and m5_budget > 0
                ):
                    # Count attempted calls, not only successful calls.
                    m5_budget -= 1

                    try:
                        LOGGER.info(
                            "Requesting M5 confirmation for %s",
                            symbol,
                        )

                        m5 = await self.data.get_time_series(
                            symbol,
                            "5min",
                            120,
                        )

                        evaluation = self.engine.evaluate(
                            symbol=symbol,
                            m15=m15,
                            h1=h1,
                            h4=h4,
                            m5=m5,
                            symbol_config=self.symbol_config[symbol],
                            conversion_prices=conversion_prices,
                            risk_usd=self.settings.risk_per_trade_usd,
                        )

                    except TwelveDataError as exc:
                        LOGGER.warning(
                            "M5 confirmation failed for %s: %s",
                            symbol,
                            exc,
                        )

                evaluations[symbol] = evaluation

                await self._handle_evaluation(
                    evaluation
                )

                # Candle-close fallback when WebSocket is unavailable.
                if not self.websocket_available:
                    await self._process_price(
                        symbol,
                        float(m15["close"].iloc[-1]),
                    )

            except Exception as exc:
                LOGGER.exception(
                    "Strategy evaluation failed for %s: %s",
                    symbol,
                    exc,
                )

        if evaluations:
            LOGGER.info(
                "Scan complete: %s",
                ", ".join(
                    f"{symbol}={evaluation.score}/6"
                    for symbol, evaluation in evaluations.items()
                ),
            )
        else:
            LOGGER.warning(
                "Scan finished without successful evaluations"
            )

    async def _fetch_m15_frames(
        self,
    ) -> dict[str, pd.DataFrame]:
        """
        Fetch M15 candles sequentially.

        This prevents the worker from bursting all six requests
        at Twelve Data simultaneously.
        """

        frames: dict[str, pd.DataFrame] = {}
        symbols = list(self.symbol_config)

        for index, symbol in enumerate(symbols):
            try:
                LOGGER.info(
                    "Requesting M15 candles for %s",
                    symbol,
                )

                frame = await self.data.get_time_series(
                    symbol,
                    "15min",
                    self.settings.scan_output_size,
                )

                if frame.empty:
                    LOGGER.warning(
                        "Twelve Data returned an empty M15 frame for %s",
                        symbol,
                    )
                else:
                    frames[symbol] = frame

                    LOGGER.info(
                        "M15 data loaded for %s: %d candles",
                        symbol,
                        len(frame),
                    )

            except TwelveDataError as exc:
                LOGGER.error(
                    "M15 provider request failed for %s: %s",
                    symbol,
                    exc,
                )

            except Exception as exc:
                LOGGER.exception(
                    "Unexpected M15 fetch failure for %s: %s",
                    symbol,
                    exc,
                )

            # Do not sleep after the final symbol.
            if index < len(symbols) - 1:
                await asyncio.sleep(
                    API_REQUEST_SPACING_SECONDS
                )

        return frames

    async def _handle_evaluation(
        self,
        evaluation: Any,
    ) -> None:
        signal = evaluation.signal

        if signal is None:
            return

        existing = await self.state.get_signal(
            signal.signal_id
        )

        decimals = int(
            self.symbol_config[signal.symbol][
                "price_decimals"
            ]
        )

        if existing is None:
            await self.state.save_signal(signal)

            await self.telegram.send_message(
                format_signal_alert(
                    signal,
                    price_decimals=decimals,
                )
            )

            return

        if (
            existing.grade == SignalGrade.A
            and signal.grade == SignalGrade.A_PLUS
        ):
            # A+ setups are automatically tracked.
            signal.tracked = True

            await self.state.save_signal(signal)

            await self.telegram.send_message(
                format_signal_alert(
                    signal,
                    price_decimals=decimals,
                )
            )

    async def websocket_loop(self) -> None:
        try:
            async for event in self.data.stream_prices(
                self.symbol_config.keys(),
                stop_event=self.stop_event,
            ):
                symbol = str(
                    event.get("symbol", "")
                )

                price_raw = event.get("price")

                if symbol and price_raw is not None:
                    self.websocket_available = True

                    await self._process_price(
                        symbol,
                        float(price_raw),
                    )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            self.websocket_available = False

            LOGGER.exception(
                "WebSocket unavailable: %s",
                exc,
            )

            await self.telegram.send_message(
                "⚠️ Live WebSocket tracking is unavailable.\n\n"
                "Signal scans will continue on completed M15 candles, "
                "but entry/SL/TP alerts can be delayed until "
                "WebSocket access is restored."
            )

    async def _process_price(
        self,
        symbol: str,
        price: float,
    ) -> None:
        tracked_signals = await self.state.active_signals()

        for tracked in tracked_signals:
            if tracked.symbol != symbol:
                continue

            now = datetime.now(timezone.utc)

            if (
                now >= tracked.expires_at
                and not tracked.entry_hit
            ):
                tracked.status = SignalStatus.EXPIRED
                tracked.tracked = False

                await self.state.save_signal(tracked)

                continue

            if not tracked.entry_hit:
                invalid = (
                    tracked.direction == Direction.BUY
                    and price <= tracked.stop_loss
                ) or (
                    tracked.direction == Direction.SELL
                    and price >= tracked.stop_loss
                )

                if invalid:
                    tracked.status = SignalStatus.INVALIDATED
                    tracked.tracked = False

                    await self.state.save_signal(tracked)

                    await self.telegram.send_message(
                        format_invalidation_alert(tracked)
                    )

                    continue

                entry_hit = (
                    tracked.direction == Direction.BUY
                    and price <= tracked.entry
                ) or (
                    tracked.direction == Direction.SELL
                    and price >= tracked.entry
                )

                if entry_hit:
                    tracked.entry_hit = True
                    tracked.status = SignalStatus.ENTERED

                    await self.state.save_signal(tracked)

                    await self.telegram.send_message(
                        format_entry_alert(tracked)
                    )

                continue

            stop_hit = (
                tracked.direction == Direction.BUY
                and price <= tracked.stop_loss
            ) or (
                tracked.direction == Direction.SELL
                and price >= tracked.stop_loss
            )

            if stop_hit:
                tracked.stop_hit = True
                tracked.status = SignalStatus.STOPPED
                tracked.tracked = False

                await self.state.save_signal(tracked)

                await self.telegram.send_message(
                    format_stop_alert(tracked)
                )

                continue

            targets = (
                (
                    "tp1",
                    tracked.tp1,
                    tracked.tp1_hit,
                    SignalStatus.TP1,
                ),
                (
                    "tp2",
                    tracked.tp2,
                    tracked.tp2_hit,
                    SignalStatus.TP2,
                ),
                (
                    "tp3",
                    tracked.tp3,
                    tracked.tp3_hit,
                    SignalStatus.TP3,
                ),
            )

            for (
                name,
                level,
                already_hit,
                status,
            ) in targets:
                reached = (
                    tracked.direction == Direction.BUY
                    and price >= level
                ) or (
                    tracked.direction == Direction.SELL
                    and price <= level
                )

                if reached and not already_hit:
                    setattr(
                        tracked,
                        f"{name}_hit",
                        True,
                    )

                    tracked.status = status

                    if name == "tp3":
                        tracked.tracked = False

                    await self.state.save_signal(tracked)

                    await self.telegram.send_message(
                        format_target_alert(
                            tracked,
                            name,
                        )
                    )

    async def telegram_command_loop(self) -> None:
        stored = await self.state.get_setting(
            "telegram_update_offset"
        )

        offset = int(stored) if stored else None

        async for (
            update_id,
            text,
        ) in self.telegram.command_messages(
            initial_offset=offset
        ):
            await self.state.set_setting(
                "telegram_update_offset",
                str(update_id + 1),
            )

            await self._handle_command(text)

    async def _handle_command(
        self,
        text: str,
    ) -> None:
        parts = text.strip().split()

        if not parts:
            return

        command = (
            parts[0]
            .split("@")[0]
            .lower()
        )

        if command == "/track":
            if len(parts) != 2:
                await self.telegram.send_message(
                    "Usage: /track EURUSD"
                )
                return

            signal = await self.state.latest_a_for_symbol(
                parts[1]
            )

            if not signal:
                await self.telegram.send_message(
                    f"No current A setup found for "
                    f"{parts[1].upper()}."
                )
                return

            signal.tracked = True
            signal.status = SignalStatus.TRACKING

            await self.state.save_signal(signal)

            await self.telegram.send_message(
                format_tracking_alert(signal)
            )

        elif command == "/status":
            active = await self.state.active_signals()

            if not active:
                await self.telegram.send_message(
                    "No signals are currently being tracked."
                )
                return

            lines = [
                "📊 TRACKED SIGNALS",
                "",
            ]

            for item in active:
                lines.append(
                    f"{item.symbol} "
                    f"{item.direction.value} — "
                    f"{item.status.value.upper()}"
                )

            await self.telegram.send_message(
                "\n".join(lines)
            )

        elif command in {
            "/start",
            "/help",
        }:
            await self.telegram.send_message(
                "Commands:\n"
                "/track EURUSD — track the latest A setup "
                "for that pair\n"
                "/status — list tracked signals\n"
                "/help — show this message"
            )

    def _seconds_until_next_scan(self) -> float:
        now = datetime.now(timezone.utc)

        next_minute = (
            (now.minute // 15) + 1
        ) * 15

        if next_minute >= 60:
            boundary = (
                now.replace(
                    minute=0,
                    second=0,
                    microsecond=0,
                )
                + timedelta(hours=1)
            )
        else:
            boundary = now.replace(
                minute=next_minute,
                second=0,
                microsecond=0,
            )

        run_at = boundary + timedelta(
            seconds=self.settings.scan_grace_seconds
        )

        return max(
            1.0,
            (run_at - now).total_seconds(),
        )

    @staticmethod
    def _forex_market_window(
        now: datetime,
    ) -> bool:
        weekday = now.weekday()

        # Saturday
        if weekday == 5:
            return False

        # Sunday before approximately 21:00 UTC
        if weekday == 6 and now.hour < 21:
            return False

        # Friday after approximately 22:00 UTC
        if weekday == 4 and now.hour >= 22:
            return False

        return True


async def async_main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=getattr(
            logging,
            settings.log_level.upper(),
            logging.INFO,
        ),
        format=(
            "%(asctime)s %(levelname)s "
            "%(name)s — %(message)s"
        ),
    )

    logging.getLogger("httpx").setLevel(
        logging.WARNING
    )

    logging.getLogger("httpcore").setLevel(
        logging.WARNING
    )

    worker = Worker(settings)

    loop = asyncio.get_running_loop()

    for signal_name in (
        os_signal.SIGINT,
        os_signal.SIGTERM,
    ):
        try:
            loop.add_signal_handler(
                signal_name,
                worker.stop_event.set,
            )
        except NotImplementedError:
            pass

    try:
        await worker.run()
    finally:
        await worker.close()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
