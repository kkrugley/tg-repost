import pytest

from src.bot_client import BotClient


class FakeBot:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def copy_message(self, chat_id, from_chat_id, message_id, protect_content=False):
        self.calls.append(
            {
                "chat_id": chat_id,
                "from_chat_id": from_chat_id,
                "message_id": message_id,
                "protect_content": protect_content,
            }
        )

    async def close(self):
        self.closed = True

    async def get_me(self):
        return {"id": 1}


@pytest.mark.asyncio
async def test_copy_post_uses_bot(fake_config):
    fake_bot = FakeBot()
    client = BotClient(fake_config.telegram_bot_token, bot=fake_bot)

    await client.copy_post(fake_config.target_channel_id, fake_config.source_channel, 10)

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
