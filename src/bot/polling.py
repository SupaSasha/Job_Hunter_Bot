import asyncio
import logging
from collections.abc import Awaitable, Callable

from src.bot.client import TelegramAPIError, TelegramClient

logger = logging.getLogger(__name__)


async def poll_updates(
    client: TelegramClient,
    handle_update: Callable[[dict], Awaitable[None]],
    *,
    timeout: int = 30,
    retry_delay: float = 3.0,
) -> None:
    """Poll sequentially. Keep offset in memory; acknowledge only handled updates."""
    if timeout <= 0 or retry_delay <= 0:
        raise ValueError("Polling timeout and retry delay must be positive")
    offset: int | None = None
    while True:
        try:
            updates = await client.get_updates(offset=offset, timeout=timeout)
        except TelegramAPIError as exc:
            logger.warning("Telegram polling error: %s", exc)
            await asyncio.sleep(retry_delay)
            continue

        for update in sorted(updates, key=lambda item: item["update_id"]):
            update_id = update["update_id"]
            if offset is not None and update_id < offset:
                continue
            try:
                await handle_update(update)
            except Exception as exc:
                # Do not log SQL parameters or raw Telegram payloads.
                logger.error(
                    "Update processing failed (%s); will retry", type(exc).__name__
                )
                await asyncio.sleep(retry_delay)
                break
            offset = update_id + 1
