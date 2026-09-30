from datetime import datetime

from sqlalchemy import update

from src.models.collector_run import CollectorRunORM


class CollectorRunRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    async def start(self, source: str, now: datetime) -> int:
        async with self.sessions() as session:
            run = CollectorRunORM(source=source, started_at=now, status="running")
            session.add(run)
            await session.flush()
            run_id = run.id
            await session.commit()
            return run_id

    async def finish(self, run_id: int, **values: object) -> None:
        async with self.sessions() as session:
            await session.execute(
                update(CollectorRunORM)
                .where(CollectorRunORM.id == run_id)
                .values(**values)
            )
            await session.commit()
