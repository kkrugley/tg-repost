import datetime as dt

import pytest
from telegram.error import TelegramError

from src.scheduler import Scheduler


class FakeDB:
    def __init__(self, post=None, initial_posts=0):
        self.post = post
        self.marked = []
        self.metadata = []
        self.initial_posts = initial_posts
        self.setup_called = False
        self.config = {}

    async def setup(self):
        self.setup_called = True

    async def get_random_unreposted_post(self):
        return self.post

    async def mark_reposted(self, message_id, when=None):
        self.marked.append(message_id)

    async def count_unreposted(self):
        return 1

    async def count_posts(self):
        return self.initial_posts

    async def latest_repost_time(self):
        return None

    async def get_config_value(self, key):
        return self.config.get(key)

    async def set_config_value(self, key, value):
        self.config[key] = value

    async def upsert_post_metadata(
        self, message_id, channel_id, post_date, content_preview=None
    ):
        self.metadata.append(message_id)


class FakeUserClient:
    def __init__(self, message_exists=True, fetch_saved=0):
        self.client = self
        self.message_exists = message_exists
        self.fetch_saved = fetch_saved
        self.started = False

    async def start(self):
        self.started = True

    async def fetch_posts(self, *_):
        return self.fetch_saved

    async def get_messages(self, channel, ids):
        return object() if self.message_exists else None

    async def status(self):
        return "connected"

    async def stop(self):
        return None


class FakeBotClient:
    def __init__(self, copy_error=None):
        self.copied = []
        self.copy_error = copy_error

    async def copy_post(self, target_channel_id, source_channel, message_id):
        if self.copy_error:
            raise self.copy_error
        self.copied.append(message_id)

    async def close(self):
        return None

    async def status(self):
        return "connected"


@pytest.mark.asyncio
async def test_repost_skips_when_no_posts(fake_config):
    scheduler = Scheduler(
        fake_config, FakeDB(post=None), FakeUserClient(), FakeBotClient()
    )
    result = await scheduler.repost_once()
    assert result is None


@pytest.mark.asyncio
async def test_repost_copies_and_marks(fake_config):
    post = {"message_id": 10, "channel_id": 20, "post_date": None}
    db = FakeDB(post=post)
    bot = FakeBotClient()
    scheduler = Scheduler(fake_config, db, FakeUserClient(), bot)

    result = await scheduler.repost_once()

    assert result["message_id"] == 10
    assert db.marked == [10]
    assert bot.copied == [10]


@pytest.mark.asyncio
async def test_repost_marks_missing_message(fake_config):
    post = {"message_id": 11, "channel_id": 20, "post_date": None}
    db = FakeDB(post=post)
    scheduler = Scheduler(
        fake_config,
        db,
        FakeUserClient(message_exists=False),
        FakeBotClient(copy_error=TelegramError("message to copy not found")),
    )

    result = await scheduler.repost_once()

    assert result["message_id"] == 11
    assert db.marked == [11]


@pytest.mark.asyncio
async def test_initialize_fetches_when_empty(fake_config):
    db = FakeDB(initial_posts=0)
    user = FakeUserClient(fetch_saved=2)
    scheduler = Scheduler(fake_config, db, user, FakeBotClient())

    await scheduler.initialize()

    assert db.config.get("initialized_at") is not None
    assert user.started is True


@pytest.mark.asyncio
async def test_health_returns_iso_last_repost(fake_config):
    class HealthDB(FakeDB):
        async def count_unreposted(self):
            return 2

        async def latest_repost_time(self):
            return dt.datetime(2024, 1, 1)

    scheduler = Scheduler(fake_config, HealthDB(), FakeUserClient(), FakeBotClient())

    health = await scheduler.health()

    assert health["database"] == "connected"
    assert health["last_repost"] == "2024-01-01T00:00:00"
    assert health["telegram_user_api"] == "connected"
    assert health["telegram_bot_api"] == "connected"
