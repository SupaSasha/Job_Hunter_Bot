import asyncio
from typing import Protocol


class CommandDispatcher(Protocol):
    async def collect(self) -> None: ...

    async def digest(self, user_id: int) -> None: ...


class CeleryCommandDispatcher:
    def __init__(self, collection_tasks, digest_task):
        self.collection_tasks = tuple(collection_tasks)
        self.digest_task = digest_task

    async def collect(self) -> None:
        # Publish off the event loop; never wait for the worker's result.
        for task in self.collection_tasks:
            await asyncio.to_thread(task.delay)

    async def digest(self, user_id: int) -> None:
        await asyncio.to_thread(self.digest_task.delay, user_id, run_now=True)
