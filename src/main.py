from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response

from .bot_client import BotClient
from .config import Config, ConfigError, load_config
from .database import Database
from .scheduler import Scheduler
from .user_client import UserClient

LOGGER_NAME = "repost.main"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def create_app(
    config: Optional[Config] = None,
    database: Optional[Database] = None,
    user_client: Optional["UserClient"] = None,
    bot_client: Optional[BotClient] = None,
    scheduler: Optional[Scheduler] = None,
) -> FastAPI:
    config = config or load_config()
    configure_logging(config.log_level)
    logger = structlog.get_logger(LOGGER_NAME)

    database = database or Database(
        config.database_url,
        logger=structlog.get_logger("repost.database"),
        max_retries=config.max_retries,
        retry_delay_seconds=config.retry_delay_seconds,
        use_ssl=config.database_ssl,
        connect_timeout=config.database_connect_timeout,
        command_timeout=config.database_command_timeout,
        disable_statement_cache=config.database_disable_statement_cache,
    )
    bot_client = bot_client or BotClient(
        config.telegram_bot_token,
        logger=structlog.get_logger("repost.bot_client"),
    )
    user_client = user_client or UserClient(
        config,
        database,
        logger=structlog.get_logger("repost.user_client"),
    )
    scheduler = scheduler or Scheduler(
        config,
        database,
        user_client,
        bot_client,
        logger=structlog.get_logger("repost.scheduler"),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            logger.info("App startup: scheduler initialize")
            await scheduler.initialize()
        except (
            Exception
        ) as exc:  # pragma: no cover - startup issues are runtime-specific
            logger.error("Startup failed", error=str(exc))
            raise
        yield
        logger.info("App shutdown: closing resources")
        await database.close()
        await bot_client.close()
        await user_client.stop()

    app = FastAPI(title="Telegram Repost Bot", version="0.1.0", lifespan=lifespan)
    repost_lock = asyncio.Lock()

    @app.get("/", response_class=JSONResponse)
    async def root() -> dict:
        return {"status": "ok", "message": "see /health and /trigger_repost"}

    @app.get("/favicon.ico")
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/health")
    async def health() -> dict:
        try:
            metrics = await scheduler.health()
            status = "ok"
        except Exception as exc:
            status = "degraded"
            metrics = {"error": str(exc)}
        response = {
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        response.update(metrics)
        return response

    @app.post("/trigger_repost")
    async def trigger_repost() -> dict:
        if repost_lock.locked():
            raise HTTPException(status_code=429, detail="Repost already in progress")

        async with repost_lock:
            try:
                post = await scheduler.repost_once()
            except (
                Exception
            ) as exc:  # pragma: no cover - depends on Telegram connectivity
                logger.error("Repost failed", error=str(exc))
                raise HTTPException(status_code=500, detail="Repost failed") from exc

        if not post:
            return {"status": "skipped", "reason": "no posts available"}

        return {"status": "ok", "message_id": post.get("message_id")}

    return app


try:
    app = create_app()
except ConfigError:
    # Fallback app to allow import without env during tests; real app is created in __main__ with proper env.
    app = FastAPI(title="Telegram Repost Bot", version="0.1.0")


if __name__ == "__main__":
    cfg = load_config()
    uvicorn.run("src.main:app", host="0.0.0.0", port=cfg.port, reload=False)
