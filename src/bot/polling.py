import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from src.bot.client import TelegramAPIError, TelegramClient

logger = logging.getLogger(__name__)
MAX_UPDATE_RETRIES = 3


class OffsetStore(Protocol):
    async def load(self) -> int | None: ...
    async def save(self, offset: int) -> None: ...


class RedisOffsetStore:
    def __init__(self, redis, key: str = "telegram:polling:offset"):
        self.redis = redis
        self.key = key

    async def load(self) -> int | None:
        value = await self.redis.get(self.key)
        if value is None:
            return None
        offset = int(value)
        if offset < 0:
            raise ValueError("Invalid polling offset")
        return offset

    async def save(self, offset: int) -> None:
        await self.redis.set(self.key, offset)


async def poll_updates(
    client: TelegramClient,
    handle_update: Callable[[dict], Awaitable[None]],
    *,
    timeout: int = 30,
    retry_delay: float = 3.0,
    offset_store: OffsetStore | None = None,
    max_update_retries: int = MAX_UPDATE_RETRIES,
) -> None:
    """Persist acknowledgement after handling; pause on unavailable storage."""
    if timeout <= 0 or retry_delay <= 0 or max_update_retries < 1:
        raise ValueError("Polling timeout and retry delay must be positive")
    offset: int | None = None
    failures: dict[int, int] = {}
    if offset_store is not None:
        while True:
            try:
                offset = await offset_store.load()
                break
            except Exception as exc:
                logger.error(
                    "Polling offset load failed (%s); paused", type(exc).__name__
                )
                await asyncio.sleep(retry_delay)
    while True:
        try:
            updates = await client.get_updates(offset=offset, timeout=timeout)
        except TelegramAPIError as exc:
            logger.warning("Telegram polling error: %s", exc)
            await asyncio.sleep(max(retry_delay, exc.retry_after or 0))
            continue

        for update in sorted(updates, key=lambda item: item["update_id"]):
            update_id = update["update_id"]
            if offset is not None and update_id < offset:
                continue
            try:
                await handle_update(update)
            except Exception as exc:
                failures[update_id] = failures.get(update_id, 0) + 1
                logger.error(
                    "Update %s processing failed (%s), attempt %s/%s",
                    update_id,
                    type(exc).__name__,
                    failures[update_id],
                    max_update_retries,
                )
                if failures[update_id] < max_update_retries:
                    await asyncio.sleep(retry_delay)
                    break
                logger.error("Skipping poison update %s", update_id)
            next_offset = update_id + 1
            if offset_store is not None:
                while True:
                    try:
                        await offset_store.save(next_offset)
                        break
                    except Exception as exc:
                        # Do not rerun a handled command or acknowledge to Telegram.
                        logger.error(
                            "Polling offset save failed (%s); paused",
                            type(exc).__name__,
                        )
                        await asyncio.sleep(retry_delay)
            offset = next_offset
            failures.pop(update_id, None)
