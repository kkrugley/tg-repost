import datetime as dt

import pytest
import pytz

from src.config import Config


@pytest.fixture
def fake_config() -> Config:
    tz = pytz.UTC
    return Config(
        telegram_api_id=1,
        telegram_api_hash="hash",
        telegram_phone="+7000000000",
        telegram_auth_code="12345",
        telegram_session_string=None,
        telegram_bot_token="bot-token",
        target_channel_id=-100123,
        source_channel="source_channel",
        start_datetime=tz.localize(dt.datetime(2022, 10, 30)),
        end_datetime=tz.localize(dt.datetime(2022, 10, 31)),
        database_url="postgresql://user:pass@localhost:5432/db",
        port=10000,
        log_level="INFO",
        timezone=tz,
        max_retries=2,
        retry_delay_seconds=0,
    )
