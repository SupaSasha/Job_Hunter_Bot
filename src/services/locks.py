from contextlib import asynccontextmanager

from redis.asyncio import Redis
from redis.exceptions import LockNotOwnedError


@asynccontextmanager
async def collector_lock(redis: Redis, source: str):
    # The worker's 600s hard limit is shorter than the 660s lease.
    lock = redis.lock(
        f"collector:{source}:lock",
        timeout=660,
        blocking=False,
        thread_local=False,
    )
    acquired = await lock.acquire()
    try:
        yield acquired
    finally:
        if acquired:
            try:
                # redis-py's Lua release compares the ownership token atomically.
                await lock.release()
            except LockNotOwnedError:
                pass
