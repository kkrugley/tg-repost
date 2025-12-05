from __future__ import annotations

import asyncio
import inspect
from datetime import datetime
import ssl
from typing import Any, Dict, Optional, cast
from contextlib import asynccontextmanager

import asyncpg
from asyncpg.pool import Pool
import structlog

LOGGER_NAME = "repost.database"

CREATE_POSTS_TABLE = """
CREATE TABLE IF NOT EXISTS repost_posts (
    id SERIAL PRIMARY KEY,
    message_id INTEGER UNIQUE NOT NULL,
    channel_id BIGINT NOT NULL,
    post_date TIMESTAMP NOT NULL,
    is_reposted BOOLEAN DEFAULT FALSE,
    reposted_at TIMESTAMP NULL,
    content_preview TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_POSTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_repost_posts_not_reposted ON repost_posts(is_reposted, post_date);
"""

CREATE_SESSION_TABLE = """
CREATE TABLE IF NOT EXISTS repost_session (
    key VARCHAR(255) PRIMARY KEY,
    value BYTEA NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_CONFIG_TABLE = """
CREATE TABLE IF NOT EXISTS repost_config (
    key VARCHAR(255) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

SESSION_KEY = "telethon_session"


class Database:
    def __init__(
        self,
        dsn: str,
        logger: Optional[structlog.stdlib.BoundLogger] = None,
        pool: Optional[Any] = None,
        max_retries: int = 3,
        retry_delay_seconds: int = 30,
    ):
        self.dsn = dsn
        self.pool = pool
        self.logger = logger or structlog.get_logger(LOGGER_NAME)
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

    def _require_pool(self) -> Pool:
        if self.pool is None:
            raise RuntimeError("Database pool is not initialized")
        return cast(Pool, self.pool)

    async def connect(self) -> None:
        if self.pool is None:
            attempt = 0
            while attempt < self.max_retries:
                attempt += 1
                ssl_ctx = ssl.create_default_context()
                # For Supabase poolers we disable hostname check/cert verify to avoid DNS/SSL mismatches.
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                try:
                    self.pool = await asyncpg.create_pool(self.dsn, ssl=ssl_ctx)
                    self.logger.info("Connected to database")
                    break
                except Exception as exc:
                    self.logger.error(
                        "Database connection failed",
                        error=str(exc),
                        error_type=exc.__class__.__name__,
                        attempt=attempt,
                    )
                    if attempt >= self.max_retries:
                        raise
                    await asyncio.sleep(self.retry_delay_seconds)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
            self.logger.info("Database connection closed")

    @asynccontextmanager
    async def _acquire_connection(self):
        pool = self._require_pool()
        resource = pool.acquire()

        if hasattr(resource, "__aenter__"):
            async with resource as conn:
                yield conn
            return

        if inspect.isawaitable(resource):
            conn = await resource
        else:
            conn = resource

        if hasattr(conn, "__aenter__"):
            async with conn as managed:
                yield managed
            return

        try:
            yield conn
        finally:
            release = getattr(pool, "release", None)
            if callable(release):
                maybe_awaitable = release(conn)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable

    async def setup(self) -> None:
        await self.connect()
        async with self._acquire_connection() as conn:
            await conn.execute(CREATE_POSTS_TABLE)
            await conn.execute(CREATE_POSTS_INDEX)
            await conn.execute(CREATE_SESSION_TABLE)
            await conn.execute(CREATE_CONFIG_TABLE)
        self.logger.info("Database schema ensured")

    async def upsert_post_metadata(
        self,
        message_id: int,
        channel_id: int,
        post_date: datetime,
        content_preview: Optional[str] = None,
    ) -> None:
        await self.connect()
        query = """
        INSERT INTO repost_posts (message_id, channel_id, post_date, content_preview)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (message_id) DO UPDATE
        SET channel_id = EXCLUDED.channel_id,
            post_date = EXCLUDED.post_date,
            content_preview = EXCLUDED.content_preview;
        """
        async with self._acquire_connection() as conn:
            await conn.execute(
                query, message_id, channel_id, post_date, content_preview
            )
        self.logger.debug("Saved post metadata", message_id=message_id)

    async def get_random_unreposted_post(self) -> Optional[Dict[str, Any]]:
        await self.connect()
        query = """
        SELECT id, message_id, channel_id, post_date
        FROM repost_posts
        WHERE is_reposted = FALSE
        ORDER BY random()
        LIMIT 1;
        """
        async with self._acquire_connection() as conn:
            row = await conn.fetchrow(query)
            if row:
                return dict(row)
        return None

    async def mark_reposted(
        self, message_id: int, when: Optional[datetime] = None
    ) -> None:
        await self.connect()
        query = """
        UPDATE repost_posts
        SET is_reposted = TRUE,
            reposted_at = COALESCE($2, CURRENT_TIMESTAMP)
        WHERE message_id = $1;
        """
        async with self._acquire_connection() as conn:
            await conn.execute(query, message_id, when)
        self.logger.info("Post marked reposted", message_id=message_id)

    async def count_unreposted(self) -> int:
        await self.connect()
        query = "SELECT COUNT(*) FROM repost_posts WHERE is_reposted = FALSE;"
        async with self._acquire_connection() as conn:
            return int(await conn.fetchval(query))

    async def count_posts(self) -> int:
        await self.connect()
        query = "SELECT COUNT(*) FROM repost_posts;"
        async with self._acquire_connection() as conn:
            return int(await conn.fetchval(query))

    async def latest_repost_time(self) -> Optional[datetime]:
        await self.connect()
        query = """
        SELECT reposted_at FROM repost_posts
        WHERE reposted_at IS NOT NULL
        ORDER BY reposted_at DESC
        LIMIT 1;
        """
        async with self._acquire_connection() as conn:
            value = await conn.fetchval(query)
            return value

    async def save_session_bytes(self, data: bytes) -> None:
        await self.connect()
        query = """
        INSERT INTO repost_session (key, value, updated_at)
        VALUES ($1, $2, CURRENT_TIMESTAMP)
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value,
            updated_at = CURRENT_TIMESTAMP;
        """
        async with self._acquire_connection() as conn:
            await conn.execute(query, SESSION_KEY, data)
        self.logger.info("Telethon session saved")

    async def load_session_bytes(self) -> Optional[bytes]:
        await self.connect()
        query = "SELECT value FROM repost_session WHERE key = $1;"
        async with self._acquire_connection() as conn:
            value = await conn.fetchval(query, SESSION_KEY)
            return value

    async def set_config_value(self, key: str, value: str) -> None:
        await self.connect()
        query = """
        INSERT INTO repost_config (key, value, updated_at)
        VALUES ($1, $2, CURRENT_TIMESTAMP)
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value,
            updated_at = CURRENT_TIMESTAMP;
        """
        async with self._acquire_connection() as conn:
            await conn.execute(query, key, value)

    async def get_config_value(self, key: str) -> Optional[str]:
        await self.connect()
        query = "SELECT value FROM repost_config WHERE key = $1;"
        async with self._acquire_connection() as conn:
            value = await conn.fetchval(query, key)
            return value
