import asyncio
import logging

from src.tasks.jobs import collect_the_muse_async


async def main() -> None:
    result = await collect_the_muse_async()
    for key, value in result.items():
        print(f"{key}: {value}")
    if result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
