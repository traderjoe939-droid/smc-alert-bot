from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from app.models import Signal, SignalGrade, SignalStatus


class StateStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    signal_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    grade TEXT NOT NULL,
                    tracked INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_signals_symbol_created "
                "ON signals(symbol, created_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    async def get_signal(self, signal_id: str) -> Signal | None:
        async with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM signals WHERE signal_id = ?", (signal_id,)
                ).fetchone()
        return Signal.from_dict(json.loads(row["payload"])) if row else None

    async def save_signal(self, signal: Signal) -> None:
        payload = json.dumps(signal.to_dict(), separators=(",", ":"))
        async with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO signals(signal_id, symbol, grade, tracked, status, created_at, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(signal_id) DO UPDATE SET
                        grade = excluded.grade,
                        tracked = excluded.tracked,
                        status = excluded.status,
                        payload = excluded.payload
                    """,
                    (
                        signal.signal_id,
                        signal.symbol,
                        signal.grade.value,
                        int(signal.tracked),
                        signal.status.value,
                        signal.created_at.isoformat(),
                        payload,
                    ),
                )

    async def latest_a_for_symbol(self, symbol: str) -> Signal | None:
        async with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT payload FROM signals
                    WHERE REPLACE(symbol, '/', '') = ? AND grade = ?
                      AND status IN (?, ?)
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (
                        symbol.replace("/", "").upper(),
                        SignalGrade.A.value,
                        SignalStatus.PLANNED.value,
                        SignalStatus.TRACKING.value,
                    ),
                ).fetchone()
        return Signal.from_dict(json.loads(row["payload"])) if row else None

    async def active_signals(self) -> list[Signal]:
        active = (
            SignalStatus.PLANNED.value,
            SignalStatus.TRACKING.value,
            SignalStatus.ENTERED.value,
            SignalStatus.TP1.value,
            SignalStatus.TP2.value,
        )
        placeholders = ",".join("?" for _ in active)
        async with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT payload FROM signals WHERE tracked = 1 "
                    f"AND status IN ({placeholders})",
                    active,
                ).fetchall()
        return [Signal.from_dict(json.loads(row["payload"])) for row in rows]

    async def get_setting(self, key: str) -> str | None:
        async with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT value FROM settings WHERE key = ?", (key,)
                ).fetchone()
        return str(row["value"]) if row else None

    async def set_setting(self, key: str, value: str) -> None:
        async with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO settings(key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value),
                )
