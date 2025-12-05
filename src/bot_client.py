from __future__ import annotations

import logging
from typing import Optional

from telegram import Bot
from telegram.error import TelegramError

LOGGER_NAME = "repost.bot_client"


class BotClient:
    def __init__(self, token: str, logger: Optional[logging.Logger] = None, bot: Optional[Bot] = None):
        self.logger = logger or logging.getLogger(LOGGER_NAME)
        self.bot = bot or Bot(token=token)

    async def copy_post(self, target_channel_id: int, source_channel: str, message_id: int) -> None:
        try:
            await self.bot.copy_message(
                chat_id=target_channel_id,
                from_chat_id=source_channel,
                message_id=message_id,
                protect_content=False,
            )
            self.logger.info(
                "Post copied", extra={"message_id": message_id, "target_channel_id": target_channel_id}
            )
        except TelegramError as exc:
            self.logger.error(
                "Failed to copy message",
                extra={"message_id": message_id, "error": str(exc)},
            )
            raise

    async def close(self) -> None:
        await self.bot.close()
