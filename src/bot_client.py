from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import structlog
from telegram import Bot
from telegram.error import TelegramError

LOGGER_NAME = "repost.bot_client"


class BotClient:
    def __init__(
        self,
        token: str,
        logger: Optional[structlog.stdlib.BoundLogger] = None,
        bot: Optional[Bot] = None,
    ):
        self.logger = logger or structlog.get_logger(LOGGER_NAME)
        self.bot = bot or Bot(token=token)

    @staticmethod
    def _chat_matches_source(chat, source_channel: str) -> bool:
        username = (getattr(chat, "username", None) or "").lstrip("@").lower()
        normalized_source = source_channel.lstrip("@").lower()
        chat_id = str(getattr(chat, "id", ""))
        return username == normalized_source or chat_id == source_channel

    async def fetch_channel_posts(
        self,
        source_channel: str,
        start_date: datetime,
        end_date: datetime,
        timezone,
        last_update_id: Optional[int] = None,
    ) -> Tuple[List[Dict], Optional[int]]:
        offset = last_update_id + 1 if last_update_id is not None else None
        updates = await self.bot.get_updates(
            offset=offset, allowed_updates=["channel_post"], timeout=10
        )
        posts: List[Dict] = []
        latest_update_id = last_update_id
        start_day = start_date.astimezone(timezone).date()
        end_day = end_date.astimezone(timezone).date()

        for update in updates:
            if latest_update_id is None or update.update_id > latest_update_id:
                latest_update_id = update.update_id

            message = getattr(update, "channel_post", None)
            if not message:
                continue

            chat = message.chat
            if not self._chat_matches_source(chat, source_channel):
                continue

            msg_date = message.date
            if msg_date.tzinfo:
                msg_date = msg_date.astimezone(timezone)
            else:
                msg_date = timezone.localize(msg_date)

            msg_day = msg_date.date()
            if msg_day < start_day or msg_day > end_day:
                continue

            preview = (message.text or message.caption or "")[:500]
            posts.append(
                {
                    "message_id": message.message_id,
                    "channel_id": chat.id,
                    "post_date": msg_date.replace(tzinfo=None),
                    "content_preview": preview,
                }
            )

        return posts, latest_update_id

    async def copy_post(
        self, target_channel_id: int, source_channel: str, message_id: int
    ) -> None:
        try:
            await self.bot.copy_message(
                chat_id=target_channel_id,
                from_chat_id=source_channel,
                message_id=message_id,
                protect_content=False,
            )
            self.logger.info(
                "Post copied",
                message_id=message_id,
                target_channel_id=target_channel_id,
            )
        except TelegramError as exc:
            self.logger.error(
                "Failed to copy message", message_id=message_id, error=str(exc)
            )
            raise

    async def status(self) -> str:
        try:
            await self.bot.get_me()
            return "connected"
        except Exception:  # pragma: no cover - depends on network/runtime
            return "error"

    async def close(self) -> None:
        await self.bot.close()
