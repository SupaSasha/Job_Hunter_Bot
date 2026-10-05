import pytest

from src.bot.pending_input import PENDING_TTL_SECONDS, PendingInput, PendingInputStore


async def test_set_read_clear_ttl_and_user_isolation(fake_redis):
    store = PendingInputStore(fake_redis)
    assert await store.get(123) is None
    state = PendingInput("filters:reqtech", 42, "remove")
    await store.set(123, state)
    assert fake_redis.set.call_args.kwargs == {"ex": PENDING_TTL_SECONDS}
    assert PENDING_TTL_SECONDS == 600
    assert fake_redis.set.call_args.args[0] == "telegram:user:123:pending_input"
    assert await store.get(123) == state
    assert await store.get(999) is None
    await store.clear(123)
    assert await store.get(123) is None


async def test_survives_new_store_instance_and_expiration(fake_redis):
    await PendingInputStore(fake_redis).set(123, PendingInput("filters:keywords", 42))
    assert (await PendingInputStore(fake_redis).get(123)).action == "filters:keywords"
    await fake_redis.delete(PendingInputStore.key(123))
    assert await PendingInputStore(fake_redis).get(123) is None


@pytest.mark.parametrize(
    "value",
    [
        "garbage",
        "{}",
        "null",
        '{"action":"filters:keywords","message_id":0}',
        '{"action":"filters:evil","message_id":42}',
        '{"action":"filters:keywords","message_id":42,"operation":"clear"}',
    ],
)
async def test_corrupt_state_is_cleared(fake_redis, value):
    store = PendingInputStore(fake_redis)
    await fake_redis.set(store.key(123), value)
    assert await store.get(123) is None
    fake_redis.delete.assert_awaited_once_with(store.key(123))
