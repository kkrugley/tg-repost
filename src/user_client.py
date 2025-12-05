from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import structlog
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from .config import Config
from .database import Database

LOGGER_NAME = "repost.user_client"


class DatabaseSession(StringSession):
    def __init__(self, database: Database, session_string: Optional[str] = None):
        super().__init__(session_string)
        self.database = database

    @classmethod
    async def from_db(cls, database: Database) -> "DatabaseSession":
        session_bytes = await database.load_session_bytes()
        session_string = session_bytes.decode() if session_bytes else None
        return cls(database, session_string)

    async def save_to_db(self) -> None:
        session_string = super().save()
        await self.database.save_session_bytes(session_string.encode())


class UserClient:
    def __init__(
        self,
        config: Config,
        database: Database,
        logger: Optional[structlog.stdlib.BoundLogger] = None,
        client: Optional[TelegramClient] = None,
    ):
        self.config = config
        self.database = database
        self.logger = logger or structlog.get_logger(LOGGER_NAME)
        self.client = client
        self.connected = False

    async def start(self) -> None:
        await self.database.connect()
        session = await DatabaseSession.from_db(self.database)

        if self.client is None:
            self.client = TelegramClient(
                session,
                api_id=self.config.telegram_api_id,
                api_hash=self.config.telegram_api_hash,
            )

        attempt = 0
        last_error: Optional[Exception] = None
        while attempt < self.config.max_retries:
            attempt += 1
            try:
                await self.client.connect()
                self.connected = True
                if not await self.client.is_user_authorized():
                    if not self.config.telegram_auth_code:
                        raise RuntimeError(
                            "TELEGRAM_AUTH_CODE is required for initial authorization"
                        )
                    await self.client.send_code_request(self.config.telegram_phone)
                    try:
                        await self.client.sign_in(
                            self.config.telegram_phone, self.config.telegram_auth_code
                        )
                    except SessionPasswordNeededError as exc:
                        raise RuntimeError(
                            "Two-factor authentication is enabled; provide password support or disable 2FA"
                        ) from exc
                await session.save_to_db()
                self.logger.info("User client connected")
                return
            except Exception as exc:  # pragma: no cover - network/telegram errors
                last_error = exc
                self.logger.warning(
                    "User client connect failed", error=str(exc), attempt=attempt
                )
                if attempt >= self.config.max_retries:
                    break
                await asyncio.sleep(self.config.retry_delay_seconds)

        if last_error:
            raise last_error

    async def stop(self) -> None:
        if self.client is not None:
            await self.client.disconnect()
            self.connected = False

    async def persist_session(self) -> None:
        if self.client is None:
            return
        session = self.client.session
        if isinstance(session, DatabaseSession):
            await session.save_to_db()
        else:
            session_string = session.save()
            await self.database.save_session_bytes(session_string.encode())

    async def fetch_posts(self, start_date: datetime, end_date: datetime) -> int:
        if not self.connected:
            await self.start()

        if self.client is None:
            raise RuntimeError("Telethon client is not initialized")

        saved = 0
        attempt = 0
        while attempt < self.config.max_retries:
            attempt += 1
            try:
                channel = await self.client.get_entity(self.config.source_channel)
                start_day = start_date.astimezone(self.config.timezone).date()
                end_day = end_date.astimezone(self.config.timezone).date()
                async for message in self.client.iter_messages(
                    channel, offset_date=end_date, reverse=True
                ):
                    if not message or not getattr(message, "date", None):
                        continue
                    message_date = message.date.astimezone(self.config.timezone)
                    naive_date = message_date.replace(tzinfo=None)
                    message_day = naive_date.date()

                    if message_day < start_day:
                        break
                    if message_day > end_day:
                        continue

                    preview = (message.message or "")[:500]
                    await self.database.upsert_post_metadata(
                        message_id=message.id,
                        channel_id=getattr(channel, "id", 0),
                        post_date=naive_date,
                        content_preview=preview,
                    )
                    saved += 1

                await self.persist_session()
                self.logger.info("Messages fetched", count=saved)
                return saved
            except Exception as exc:  # pragma: no cover - network/telegram errors
                self.logger.warning(
                    "Fetch posts failed", error=str(exc), attempt=attempt
                )
                if attempt >= self.config.max_retries:
                    raise
                await asyncio.sleep(self.config.retry_delay_seconds)

        return saved

    async def status(self) -> str:
        if self.client is None:
            return "disconnected"
        try:
            if not self.connected:
                return "disconnected"
            authorized = await self.client.is_user_authorized()
            return "connected" if authorized else "unauthorized"
        except Exception:  # pragma: no cover - telemetry/connection errors
            return "error"
