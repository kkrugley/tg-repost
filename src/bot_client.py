from __future__ import annotations

from typing import Optional

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

    async def copy_post(self, target_channel_id: int, source_channel: str, message_id: int) -> None:
        try:
            await self.bot.copy_message(
                chat_id=target_channel_id,
                from_chat_id=source_channel,
                message_id=message_id,
                protect_content=False,
            )
            self.logger.info("Post copied", message_id=message_id, target_channel_id=target_channel_id)
        except TelegramError as exc:
            self.logger.error("Failed to copy message", message_id=message_id, error=str(exc))
            raise

    async def status(self) -> str:
        try:
            await self.bot.get_me()
            return "connected"
        except Exception:  # pragma: no cover - depends on network/runtime
            return "error"

    async def close(self) -> None:
        await self.bot.close()
