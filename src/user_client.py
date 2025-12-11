from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import structlog
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
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

    @classmethod
    async def from_env_or_db(
        cls, database: Database, session_string: Optional[str] = None
    ) -> "DatabaseSession":
        if session_string:
            return cls(database, session_string)
        return await cls.from_db(database)

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

    @staticmethod
    def _normalize_channel_id(message: object, channel: object) -> int:
        peer = getattr(message, "peer_id", None) or getattr(message, "to_id", None)
        raw_id: int | str | None = 0
        if peer:
            raw_id = getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None)
        else:
            raw_id = getattr(channel, "id", 0) or 0

        if raw_id is None:
            raw_id = 0

        try:
            channel_id = int(raw_id)
        except (TypeError, ValueError):
            return 0

        # Preserve existing -100 prefix; add it for positive ids so Bot API can resolve.
        if str(channel_id).startswith("-100"):
            return channel_id
        if channel_id > 0:
            return int(f"-100{channel_id}")
        return channel_id

    async def start(self) -> None:
        self.logger.info("User client start")
        await self.database.connect()
        session = await DatabaseSession.from_env_or_db(
            self.database, self.config.telegram_session_string
        )
        if (
            self.config.telegram_session_string
            and not await self.database.load_session_bytes()
        ):
            await self.database.save_session_bytes(
                self.config.telegram_session_string.encode()
            )

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
                self.logger.info(
                    "Connecting Telethon client",
                    attempt=attempt,
                    phone=self.config.telegram_phone,
                )
                await self.client.connect()
                self.connected = True
                if await self.client.is_user_authorized():
                    await session.save_to_db()
                    self.logger.info("User client connected")
                    return

                code_hash = await self.database.get_config_value(
                    "telethon_phone_code_hash"
                )
                if not code_hash:
                    try:
                        sent = await self.client.send_code_request(
                            self.config.telegram_phone
                        )
                        await self.database.set_config_value(
                            "telethon_phone_code_hash", sent.phone_code_hash
                        )
                    except FloodWaitError as exc:
                        await self.database.set_config_value(
                            "telethon_phone_code_hash", ""
                        )
                        raise RuntimeError(
                            f"Telegram rate limit: wait {exc.seconds} seconds before "
                            "requesting a new code"
                        ) from exc

                    raise RuntimeError(
                        "Authorization code sent. Set TELEGRAM_AUTH_CODE from the latest "
                        "SMS/Telegram message and restart."
                    )

                # Safety: if hash is empty but we got here, force re-request.
                if code_hash == "":
                    raise RuntimeError(
                        "Authorization code sent. Set TELEGRAM_AUTH_CODE from the latest "
                        "SMS/Telegram message and restart."
                    )

                if not self.config.telegram_auth_code:
                    raise RuntimeError(
                        "TELEGRAM_AUTH_CODE is required to complete authorization; set it "
                        "to the latest code and restart."
                    )

                code = self.config.telegram_auth_code.strip()
                try:
                    await self.client.sign_in(
                        self.config.telegram_phone,
                        code=code,
                        phone_code_hash=code_hash,
                    )
                    await self.database.set_config_value("telethon_phone_code_hash", "")
                    await session.save_to_db()
                    self.logger.info("User client connected")
                    return
                except (PhoneCodeInvalidError, PhoneCodeExpiredError) as exc:
                    await self.database.set_config_value("telethon_phone_code_hash", "")
                    raise RuntimeError(
                        "TELEGRAM_AUTH_CODE is invalid or expired; request a new code, "
                        "update env, and restart"
                    ) from exc
                except SessionPasswordNeededError as exc:
                    raise RuntimeError(
                        "Two-factor authentication is enabled; provide password support or disable 2FA"
                    ) from exc
            except RuntimeError:
                # Do not retry auth flow in the same run to avoid code reuse/expiry.
                raise
            except Exception as exc:  # pragma: no cover
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
                # Iterate from newest to oldest; break when older than start_day.
                async for message in self.client.iter_messages(channel):
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
                    channel_id: int = self._normalize_channel_id(message, channel)
                    await self.database.upsert_post_metadata(
                        message_id=message.id,
                        channel_id=channel_id,
                        post_date=naive_date,
                        content_preview=preview,
                    )
                    saved += 1

                await self.persist_session()
                self.logger.info("Messages fetched", count=saved)
                return saved
            except Exception as exc:  # pragma: no cover
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
        except Exception:  # pragma: no cover
            return "error"
