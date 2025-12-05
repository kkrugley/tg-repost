import datetime as dt

import pytest
import pytz

from src.user_client import UserClient


class StubDatabase:
    def __init__(self):
        self.sessions = []
        self.metadata = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def load_session_bytes(self):
        return None

    async def save_session_bytes(self, data: bytes):
        self.sessions.append(data)

    async def upsert_post_metadata(
        self, message_id, channel_id, post_date, content_preview=None
    ):
        self.metadata.append(
            {
                "message_id": message_id,
                "channel_id": channel_id,
                "post_date": post_date,
                "content_preview": content_preview,
            }
        )


class FakeSession:
    def save(self):
        return "session-string"


class FakeMessage:
    def __init__(self, message_id: int, date: dt.datetime, text: str):
        self.id = message_id
        self.date = date
        self.message = text


class FakeTelethonClient:
    def __init__(self, messages):
        self.messages = messages
        self.connected = False
        self.authorized = True
        self.session = FakeSession()
        self.sent_code = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def is_user_authorized(self):
        return self.authorized

    async def send_code_request(self, phone):
        self.sent_code = True

    async def sign_in(self, phone, code):
        self.authorized = True

    async def get_entity(self, channel):
        return type("Channel", (), {"id": 99, "username": channel})()

    async def iter_messages(self, channel, offset_date=None, reverse=True):
        for message in self.messages:
            yield message

    async def get_messages(self, channel, ids):
        for message in self.messages:
            if message.id == ids:
                return message
        return None


@pytest.mark.asyncio
async def test_fetch_posts_saves_metadata(fake_config):
    tz = pytz.UTC
    messages = [
        FakeMessage(1, tz.localize(dt.datetime(2022, 10, 30, 12, 0)), "hello"),
        FakeMessage(2, tz.localize(dt.datetime(2022, 10, 31, 12, 0)), "world"),
    ]

    db = StubDatabase()
    client = FakeTelethonClient(messages)
    user_client = UserClient(fake_config, db, client=client)

    saved = await user_client.fetch_posts(
        fake_config.start_datetime, fake_config.end_datetime
    )

    assert saved == 2
    assert len(db.metadata) == 2
    assert db.sessions[-1] == b"session-string"


@pytest.mark.asyncio
async def test_user_status(fake_config):
    db = StubDatabase()
    client = FakeTelethonClient([])
    user_client = UserClient(fake_config, db, client=client)

    await user_client.start()
    status = await user_client.status()

    assert status == "connected"
