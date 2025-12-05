import pytest

from src.scheduler import Scheduler


class FakeDB:
    def __init__(self, post=None):
        self.post = post
        self.marked = []

    async def setup(self):
        return None

    async def get_random_unreposted_post(self):
        return self.post

    async def mark_reposted(self, message_id, when=None):
        self.marked.append(message_id)

    async def count_unreposted(self):
        return 1

    async def count_posts(self):
        return 0

    async def latest_repost_time(self):
        return None


class FakeUserClient:
    def __init__(self, message_exists=True):
        self.client = self
        self.message_exists = message_exists

    async def start(self):
        return None

    async def fetch_posts(self, *_):
        return None

    async def get_messages(self, channel, ids):
        return object() if self.message_exists else None

    async def status(self):
        return "connected"

    # Telethon compatibility
    async def stop(self):
        return None


class FakeBotClient:
    def __init__(self):
        self.copied = []

    async def copy_post(self, target_channel_id, source_channel, message_id):
        self.copied.append(message_id)

    async def close(self):
        return None

    async def status(self):
        return "connected"


@pytest.mark.asyncio
async def test_repost_skips_when_no_posts(fake_config):
    scheduler = Scheduler(fake_config, FakeDB(post=None), FakeUserClient(), FakeBotClient())
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
    scheduler = Scheduler(fake_config, db, FakeUserClient(message_exists=False), FakeBotClient())

    result = await scheduler.repost_once()

    assert result["message_id"] == 11
    assert db.marked == [11]


@pytest.mark.asyncio
async def test_initialize_skips_when_posts_exist(fake_config):
    class InitDB(FakeDB):
        async def count_posts(self):
            return 5

    db = InitDB()
    user = FakeUserClient()
    scheduler = Scheduler(fake_config, db, user, FakeBotClient())

    await scheduler.initialize()

    # fetch_posts should not have been called; no marks
    assert db.marked == []


@pytest.mark.asyncio
async def test_health_returns_iso_last_repost(fake_config):
    class HealthDB(FakeDB):
        async def count_unreposted(self):
            return 2

        async def latest_repost_time(self):
            import datetime as dt

            return dt.datetime(2024, 1, 1)

    scheduler = Scheduler(fake_config, HealthDB(), FakeUserClient(), FakeBotClient())

    health = await scheduler.health()

    assert health["database"] == "connected"
    assert health["last_repost"] == "2024-01-01T00:00:00"
    assert health["telegram_user_api"] == "connected"
    assert health["telegram_bot_api"] == "connected"
