from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from .config import Config
from .database import Database

LOGGER_NAME = "repost.user_client"


class UserClient:
    def __init__(
        self,
        config: Config,
        database: Database,
        logger: Optional[logging.Logger] = None,
        client: Optional[TelegramClient] = None,
    ):
        self.config = config
        self.database = database
        self.logger = logger or logging.getLogger(LOGGER_NAME)
        self.client = client
        self.connected = False

    async def start(self) -> None:
        await self.database.connect()
        session_bytes = await self.database.load_session_bytes()
        session_string = session_bytes.decode() if session_bytes else None

        if self.client is None:
            self.client = TelegramClient(
                StringSession(session_string),
                api_id=self.config.telegram_api_id,
                api_hash=self.config.telegram_api_hash,
            )

        await self.client.connect()
        self.connected = True
        if not await self.client.is_user_authorized():
            if not self.config.telegram_auth_code:
                raise RuntimeError("TELEGRAM_AUTH_CODE is required for initial authorization")
            await self.client.send_code_request(self.config.telegram_phone)
            try:
                await self.client.sign_in(self.config.telegram_phone, self.config.telegram_auth_code)
            except SessionPasswordNeededError as exc:
                raise RuntimeError(
                    "Two-factor authentication is enabled; disable it or extend the client to accept a password"
                ) from exc
        await self.persist_session()

    async def stop(self) -> None:
        if self.client is not None:
            await self.client.disconnect()
            self.connected = False

    async def persist_session(self) -> None:
        if self.client is None:
            return
        session_string = self.client.session.save()
        await self.database.save_session_bytes(session_string.encode())

    async def fetch_posts(self, start_date: datetime, end_date: datetime) -> int:
        if not self.connected:
            await self.start()

        if self.client is None:
            raise RuntimeError("Telethon client is not initialized")

        channel = await self.client.get_entity(self.config.source_channel)
        saved = 0
        async for message in self.client.iter_messages(channel, offset_date=end_date, reverse=True):
            if not message or not getattr(message, "date", None):
                continue
            # Telethon returns tz-aware UTC dates; store them without tz info for consistency.
            message_date = message.date.astimezone(self.config.timezone)
            naive_date = message_date.replace(tzinfo=None)

            if naive_date < start_date.replace(tzinfo=None):
                break
            if naive_date > end_date.replace(tzinfo=None):
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
        self.logger.info("Messages fetched", extra={"count": saved})
        return saved
