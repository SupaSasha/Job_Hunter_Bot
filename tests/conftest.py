from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def fake_redis():
    data = {}
    redis = AsyncMock()

    async def set_value(key, value, **kwargs):
        data[key] = value

    async def get_value(key):
        return data.get(key)

    async def delete(key):
        return int(data.pop(key, None) is not None)

    async def increment(key):
        value = int(data.get(key, 0)) + 1
        data[key] = value
        return value

    redis.incr.side_effect = increment
    redis.set.side_effect = set_value
    redis.get.side_effect = get_value
    redis.delete.side_effect = delete
    return redis
