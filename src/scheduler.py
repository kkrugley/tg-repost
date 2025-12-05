from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog

from .bot_client import BotClient
from .config import Config
from .database import Database
from .user_client import UserClient

LOGGER_NAME = "repost.scheduler"


class Scheduler:
    def __init__(
        self,
        config: Config,
        database: Database,
        user_client: UserClient,
        bot_client: BotClient,
        logger: Optional[structlog.stdlib.BoundLogger] = None,
    ):
        self.config = config
        self.database = database
        self.user_client = user_client
        self.bot_client = bot_client
        self.logger = logger or structlog.get_logger(LOGGER_NAME)

    async def initialize(self) -> None:
        await self.database.setup()
        await self.user_client.start()
        initialized_at = await self.database.get_config_value("initialized_at")
        post_count = await self.database.count_posts()
        if post_count > 0:
            self.logger.info(
                "Initialization skipped",
                posts=post_count,
                initialized_at=initialized_at,
            )
            return

        saved = await self.user_client.fetch_posts(
            self.config.start_datetime, self.config.end_datetime
        )
        await self.database.set_config_value(
            "initialized_at", datetime.now(timezone.utc).isoformat()
        )
        self.logger.info("Initial fetch complete", saved=saved)

    async def repost_once(self) -> Optional[dict]:
        post = await self.database.get_random_unreposted_post()
        if not post:
            self.logger.info("No unreposted posts available")
            return None

        attempt = 0
        last_error: Optional[Exception] = None
        while attempt < self.config.max_retries:
            attempt += 1
            try:
                await self._copy_and_mark(post)
                return post
            except Exception as exc:  # pragma: no cover - depends on network
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                self.logger.warning(
                    "Retrying repost",
                    message_id=post.get("message_id"),
                    attempt=attempt,
                    error=str(exc),
                )
                await asyncio.sleep(self.config.retry_delay_seconds)

        if last_error:
            raise last_error
        return None

    async def _copy_and_mark(self, post: dict) -> None:
        message_id = post["message_id"]
        if self.user_client.client:
            message = await self.user_client.client.get_messages(
                self.config.source_channel, ids=message_id
            )
            if not message:
                self.logger.warning(
                    "Message missing in source channel", message_id=message_id
                )
                await self.database.mark_reposted(message_id)
                return

        await self.bot_client.copy_post(
            target_channel_id=self.config.target_channel_id,
            source_channel=self.config.source_channel,
            message_id=message_id,
        )
        await self.database.mark_reposted(message_id)

    async def health(self) -> dict:
        last_repost = await self.database.latest_repost_time()
        return {
            "database": "connected",
            "telegram_user_api": await self.user_client.status(),
            "telegram_bot_api": await self.bot_client.status(),
            "unpublished_posts": await self.database.count_unreposted(),
            "last_repost": last_repost.isoformat() if last_repost else None,
        }
