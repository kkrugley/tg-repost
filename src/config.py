from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional

import pytz
from dotenv import load_dotenv

DATE_FORMAT = "%Y-%m-%d"


class ConfigError(ValueError):
    """Raised when environment validation fails."""


@dataclass
class Config:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: str
    telegram_auth_code: Optional[str]
    telegram_bot_token: str
    target_channel_id: int
    source_channel: str
    start_datetime: datetime
    end_datetime: datetime
    database_url: str
    port: int
    log_level: str
    timezone: pytz.BaseTzInfo
    max_retries: int = 3
    retry_delay_seconds: int = 30


def _require(name: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise ConfigError(f"{name} is required")
    return value


def _parse_int(name: str) -> int:
    raw = _require(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _parse_date(name: str, tz: pytz.BaseTzInfo) -> datetime:
    raw = _require(name)
    try:
        parsed_date = datetime.strptime(raw, DATE_FORMAT).date()
    except ValueError as exc:
        raise ConfigError(f"{name} must match {DATE_FORMAT}") from exc
    return tz.localize(datetime.combine(parsed_date, time()))


def _timezone(name: str = "TIMEZONE") -> pytz.BaseTzInfo:
    raw = os.getenv(name, "UTC")
    try:
        return pytz.timezone(raw)
    except Exception as exc:  # pragma: no cover - pytz has custom exceptions
        raise ConfigError(f"Invalid timezone: {raw}") from exc


def load_config() -> Config:
    load_dotenv()
    tz = _timezone()

    start_datetime = _parse_date("START_DATE", tz)
    end_datetime = _parse_date("END_DATE", tz)
    if start_datetime > end_datetime:
        raise ConfigError("START_DATE must be before or equal to END_DATE")

    config = Config(
        telegram_api_id=_parse_int("TELEGRAM_API_ID"),
        telegram_api_hash=_require("TELEGRAM_API_HASH"),
        telegram_phone=_require("TELEGRAM_PHONE"),
        telegram_auth_code=os.getenv("TELEGRAM_AUTH_CODE"),
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        target_channel_id=_parse_int("TARGET_CHANNEL_ID"),
        source_channel=_require("SOURCE_CHANNEL").lstrip("@"),
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        database_url=_require("DATABASE_URL"),
        port=_parse_int("PORT"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        timezone=tz,
    )
    return config
