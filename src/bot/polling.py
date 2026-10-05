import asyncio
import json
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from src.bot.client import TelegramAPIError, TelegramClient

logger = logging.getLogger(__name__)
MAX_UPDATE_RETRIES = 3
# Telegram retains updates for 24 hours and can randomize IDs after a week.
# Allow for an update already being a day old when handled, plus polling delay.
OFFSET_MAX_AGE_SECONDS = 5 * 24 * 60 * 60


@dataclass(frozen=True)
class OffsetCheckpoint:
    offset: int
    saved_at: float


class OffsetStore(Protocol):
    async def load(self) -> OffsetCheckpoint | None: ...
    async def save(self, checkpoint: OffsetCheckpoint) -> None: ...


class RedisOffsetStore:
    def __init__(
        self,
        redis,
        key: str = "telegram:polling:offset",
        *,
        clock: Callable[[], float] = time.time,
    ):
        self.redis = redis
        self.key = key
        self.clock = clock

    async def load(self) -> OffsetCheckpoint | None:
        value = await self.redis.get(self.key)
        if value is None:
            return None
        payload = json.loads(value)
        if type(payload) is int and payload >= 0:
            # Legacy checkpoints have no trustworthy age. Preserve the confirmed
            # offset on upgrade, starting its bounded lifetime at migration time.
            checkpoint = OffsetCheckpoint(payload, self.clock())
            await self.save(checkpoint)
            logger.warning("Migrated legacy polling offset without original timestamp")
            return checkpoint
        if not isinstance(payload, dict):
            raise ValueError("Invalid polling checkpoint")
        offset, saved_at = payload.get("offset"), payload.get("saved_at")
        if (
            type(offset) is not int
            or offset < 0
            or type(saved_at) not in (int, float)
            or not math.isfinite(saved_at)
            or saved_at < 0
        ):
            raise ValueError("Invalid polling checkpoint")
        return OffsetCheckpoint(offset, saved_at)

    async def save(self, checkpoint: OffsetCheckpoint) -> None:
        # A single write keeps the acknowledgement and its timestamp atomic.
        await self.redis.set(
            self.key,
            json.dumps({"offset": checkpoint.offset, "saved_at": checkpoint.saved_at}),
        )


async def poll_updates(
    client: TelegramClient,
    handle_update: Callable[[dict], Awaitable[None]],
    *,
    timeout: int = 30,
    retry_delay: float = 3.0,
    offset_store: OffsetStore | None = None,
    max_update_retries: int = MAX_UPDATE_RETRIES,
    clock: Callable[[], float] = time.time,
) -> None:
    """Persist acknowledgement after handling; pause on unavailable storage."""
    if timeout <= 0 or retry_delay <= 0 or max_update_retries < 1:
        raise ValueError("Polling timeout and retry delay must be positive")
    offset: int | None = None
    saved_at: float | None = None
    failures: dict[int, int] = {}
    if offset_store is not None:
        while True:
            try:
                checkpoint = await offset_store.load()
                if checkpoint is not None:
                    offset, saved_at = checkpoint.offset, checkpoint.saved_at
                break
            except Exception as exc:
                logger.error(
                    "Polling offset load failed (%s); paused", type(exc).__name__
                )
                await asyncio.sleep(retry_delay)
    while True:
        if saved_at is not None and clock() - saved_at >= OFFSET_MAX_AGE_SECONDS:
            # Reset before contacting Telegram: a stale high offset would confirm
            # newly randomized, lower IDs without ever returning their updates.
            logger.info(
                "Expired idle polling checkpoint; requesting unconfirmed updates"
            )
            offset, saved_at = None, None
            failures.clear()
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
            checkpoint = OffsetCheckpoint(update_id + 1, clock())
            if offset_store is not None:
                while True:
                    try:
                        await offset_store.save(checkpoint)
                        break
                    except Exception as exc:
                        # Do not rerun a handled command or acknowledge to Telegram.
                        logger.error(
                            "Polling offset save failed (%s); paused",
                            type(exc).__name__,
                        )
                        await asyncio.sleep(retry_delay)
            offset, saved_at = checkpoint.offset, checkpoint.saved_at
            failures.pop(update_id, None)
