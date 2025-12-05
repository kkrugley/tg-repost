from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException

from .bot_client import BotClient
from .config import Config, load_config
from .database import Database
from .scheduler import Scheduler
from .user_client import UserClient

LOGGER_NAME = "repost.main"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    )


def create_app(
    config: Optional[Config] = None,
    database: Optional[Database] = None,
    user_client: Optional[UserClient] = None,
    bot_client: Optional[BotClient] = None,
    scheduler: Optional[Scheduler] = None,
) -> FastAPI:
    config = config or load_config()
    configure_logging(config.log_level)
    logger = logging.getLogger(LOGGER_NAME)

    database = database or Database(config.database_url, logger=logging.getLogger("repost.database"))
    user_client = user_client or UserClient(config, database, logger=logging.getLogger("repost.user_client"))
    bot_client = bot_client or BotClient(config.telegram_bot_token, logger=logging.getLogger("repost.bot_client"))
    scheduler = scheduler or Scheduler(config, database, user_client, bot_client, logger=logging.getLogger("repost.scheduler"))

    app = FastAPI(title="Telegram Repost Bot", version="0.1.0")
    repost_lock = asyncio.Lock()

    @app.on_event("startup")
    async def startup_event() -> None:
        try:
            await scheduler.initialize()
        except Exception as exc:  # pragma: no cover - startup issues are runtime-specific
            logger.error("Startup failed", extra={"error": str(exc)})
            raise

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        await database.close()
        await bot_client.close()
        await user_client.stop()

    @app.get("/health")
    async def health() -> dict:
        try:
            metrics = await scheduler.health()
            status = "healthy"
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
            except Exception as exc:  # pragma: no cover - depends on Telegram connectivity
                logger.error("Repost failed", extra={"error": str(exc)})
                raise HTTPException(status_code=500, detail="Repost failed") from exc

        if not post:
            return {"status": "skipped", "reason": "no posts available"}

        return {"status": "ok", "message_id": post.get("message_id")}

    return app


app = create_app()


if __name__ == "__main__":
    cfg = load_config()
    uvicorn.run("src.main:app", host="0.0.0.0", port=cfg.port, reload=False)
