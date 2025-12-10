import datetime as dt

import pytest

from src.database import Database


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.fetchval_returns = []
        self.fetchval_calls = []
        self.fetchrow_returns = []
        self.fetchrow_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, query, *args):
        self.executed.append((query.strip(), args))
        return "OK"

    async def fetchval(self, query, *args):
        self.fetchval_calls.append((query.strip(), args))
        if self.fetchval_returns:
            return self.fetchval_returns.pop(0)
        return None

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query.strip(), args))
        if self.fetchrow_returns:
            return self.fetchrow_returns.pop(0)
        return None


class FakePool:
    def __init__(self, connection: FakeConnection):
        self.connection = connection
        self.closed = False

    async def acquire(self):
        return self.connection

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_setup_creates_tables():
    conn = FakeConnection()
    db = Database("postgresql://user:pass@localhost:5432/db", pool=FakePool(conn))
    await db.setup()
    assert len(conn.executed) >= 4


@pytest.mark.asyncio
async def test_upsert_and_config_roundtrip():
    conn = FakeConnection()
    db = Database("postgresql://user:pass@localhost:5432/db", pool=FakePool(conn))

    await db.upsert_post_metadata(1, 2, dt.datetime(2024, 1, 1), "preview")
    assert conn.executed[-1][1][0] == 1

    await db.set_config_value("last_update_id", "42")
    conn.fetchval_returns.append("42")
    cfg_value = await db.get_config_value("last_update_id")
    assert cfg_value == "42"

    conn.fetchval_returns.append(b"bytes")
    session = await db.load_session_bytes()
    assert session == b"bytes"


@pytest.mark.asyncio
async def test_random_unreposted_post():
    conn = FakeConnection()
    conn.fetchrow_returns.append(
        {
            "id": 1,
            "message_id": 10,
            "channel_id": 20,
            "post_date": dt.datetime(2024, 1, 1),
        }
    )
    db = Database("postgresql://user:pass@localhost:5432/db", pool=FakePool(conn))

    post = await db.get_random_unreposted_post()
    assert post["message_id"] == 10


@pytest.mark.asyncio
async def test_count_posts():
    conn = FakeConnection()
    conn.fetchval_returns.append(3)
    db = Database("postgresql://user:pass@localhost:5432/db", pool=FakePool(conn))

    total = await db.count_posts()

    assert total == 3
