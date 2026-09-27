from contextlib import asynccontextmanager

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import settings


@asynccontextmanager
async def task_resources():
    """Each asyncio.run owns its engine and Redis pool; no cross-loop connections."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    redis = Redis.from_url(
        settings.REDIS_URL, socket_connect_timeout=5, socket_timeout=5
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False), redis
    finally:
        try:
            await redis.aclose()
        finally:
            await engine.dispose()
