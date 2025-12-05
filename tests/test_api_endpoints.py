import pytest
from fastapi.testclient import TestClient

from src.main import create_app


class FakeDatabase:
    async def close(self):
        return None


class FakeUserClient:
    async def stop(self):
        return None


class FakeBotClient:
    async def close(self):
        return None


class FakeScheduler:
    def __init__(self, repost_result=None):
        self.repost_result = repost_result
        self.initialized = False

    async def initialize(self):
        self.initialized = True

    async def health(self):
        return {"database": "connected", "unpublished_posts": 1, "last_repost": None}

    async def repost_once(self):
        return self.repost_result


@pytest.mark.asyncio
async def test_health_endpoint(fake_config):
    scheduler = FakeScheduler()
    app = create_app(
        config=fake_config,
        database=FakeDatabase(),
        user_client=FakeUserClient(),
        bot_client=FakeBotClient(),
        scheduler=scheduler,
    )

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_trigger_repost_success(fake_config):
    scheduler = FakeScheduler(repost_result={"message_id": 10})
    app = create_app(
        config=fake_config,
        database=FakeDatabase(),
        user_client=FakeUserClient(),
        bot_client=FakeBotClient(),
        scheduler=scheduler,
    )

    with TestClient(app) as client:
        response = client.post("/trigger_repost")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_trigger_repost_no_posts(fake_config):
    scheduler = FakeScheduler(repost_result=None)
    app = create_app(
        config=fake_config,
        database=FakeDatabase(),
        user_client=FakeUserClient(),
        bot_client=FakeBotClient(),
        scheduler=scheduler,
    )

    with TestClient(app) as client:
        response = client.post("/trigger_repost")
        assert response.status_code == 200
        assert response.json()["status"] == "skipped"
