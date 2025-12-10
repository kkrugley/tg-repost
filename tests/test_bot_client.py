import datetime as dt

import pytest
import pytz

from src.bot_client import BotClient


class FakeChat:
    def __init__(self, chat_id, username=None):
        self.id = chat_id
        self.username = username


class FakeMessage:
    def __init__(self, message_id, chat, date, text=None, caption=None):
        self.message_id = message_id
        self.chat = chat
        self.date = date
        self.text = text
        self.caption = caption


class FakeUpdate:
    def __init__(self, update_id, channel_post):
        self.update_id = update_id
        self.channel_post = channel_post


class FakeBot:
    def __init__(self, updates=None):
        self.calls = []
        self.closed = False
        self.updates = updates or []
        self.offsets = []

    async def copy_message(
        self, chat_id, from_chat_id, message_id, protect_content=False
    ):
        self.calls.append(
            {
                "chat_id": chat_id,
                "from_chat_id": from_chat_id,
                "message_id": message_id,
                "protect_content": protect_content,
            }
        )

    async def get_updates(self, offset=None, allowed_updates=None, timeout=None):
        self.offsets.append(offset)
        return self.updates

    async def close(self):
        self.closed = True

    async def get_me(self):
        return {"id": 1}


@pytest.mark.asyncio
async def test_copy_post_uses_bot(fake_config):
    fake_bot = FakeBot()
    client = BotClient(fake_config.telegram_bot_token, bot=fake_bot)

    await client.copy_post(
        fake_config.target_channel_id, fake_config.source_channel, 10
    )

    assert fake_bot.calls[0]["message_id"] == 10


@pytest.mark.asyncio
async def test_close_bot(fake_config):
    fake_bot = FakeBot()
    client = BotClient(fake_config.telegram_bot_token, bot=fake_bot)

    await client.close()

    assert fake_bot.closed is True


@pytest.mark.asyncio
async def test_status_connected(fake_config):
    fake_bot = FakeBot()
    client = BotClient(fake_config.telegram_bot_token, bot=fake_bot)

    status = await client.status()

    assert status == "connected"


@pytest.mark.asyncio
async def test_fetch_channel_posts_filters_and_tracks_update(fake_config):
    tz = pytz.UTC
    source_chat = FakeChat(chat_id=-1001, username="source_channel")
    other_chat = FakeChat(chat_id=-2000, username="other")
    updates = [
        FakeUpdate(
            5,
            FakeMessage(
                1,
                source_chat,
                tz.localize(dt.datetime(2022, 10, 30, 12, 0)),
                text="keep me",
            ),
        ),
        FakeUpdate(
            6,
            FakeMessage(
                2,
                other_chat,
                tz.localize(dt.datetime(2022, 10, 30, 12, 0)),
                text="skip me",
            ),
        ),
    ]
    fake_bot = FakeBot(updates=updates)
    client = BotClient(fake_config.telegram_bot_token, bot=fake_bot)

    posts, last_update = await client.fetch_channel_posts(
        source_channel=fake_config.source_channel,
        start_date=fake_config.start_datetime,
        end_date=fake_config.end_datetime,
        timezone=fake_config.timezone,
        last_update_id=4,
    )

    assert last_update == 6
    assert len(posts) == 1
    assert posts[0]["message_id"] == 1
    assert fake_bot.offsets == [5]
