import pytest

from src.config import ConfigError, load_config


def test_load_config(monkeypatch):
    env = {
        "TELEGRAM_API_ID": "123",
        "TELEGRAM_API_HASH": "hash",
        "TELEGRAM_PHONE": "+7000000000",
        "TELEGRAM_AUTH_CODE": "11111",
        "TELEGRAM_BOT_TOKEN": "token",
        "TARGET_CHANNEL_ID": "-1001",
        "SOURCE_CHANNEL": "@pulkrug",
        "START_DATE": "2022-10-30",
        "END_DATE": "2024-10-24",
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
        "PORT": "8080",
        "LOG_LEVEL": "debug",
        "TIMEZONE": "UTC",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    cfg = load_config()

    assert cfg.telegram_api_id == 123
    assert cfg.target_channel_id == -1001
    assert cfg.source_channel == "pulkrug"
    assert cfg.start_datetime.year == 2022
    assert cfg.log_level == "DEBUG"


def test_load_config_invalid_dates(monkeypatch):
    env = {
        "TELEGRAM_API_ID": "123",
        "TELEGRAM_API_HASH": "hash",
        "TELEGRAM_PHONE": "+7000000000",
        "TELEGRAM_BOT_TOKEN": "token",
        "TARGET_CHANNEL_ID": "-1001",
        "SOURCE_CHANNEL": "pulkrug",
        "START_DATE": "2024-10-25",
        "END_DATE": "2024-10-24",
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
        "PORT": "8080",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(ConfigError):
        load_config()
