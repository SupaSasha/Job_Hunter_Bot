import asyncio
import logging

from src.collectors.remoteok import RemoteOKCollector
from src.db.database import async_session_factory, engine
from src.services.jobs import JobSaveService
from src.services.normalization import NormalizationService


async def main() -> None:
    try:
        jobs = await RemoteOKCollector().collect()
        saved = duplicates = 0
        normalizer = NormalizationService()
        async with async_session_factory() as session:
            service = JobSaveService(session)
            for job in jobs:
                result = await service.save_if_new(normalizer.normalize(job))
                if result.status == "saved":
                    saved += 1
                else:
                    duplicates += 1
        print(f"received: {len(jobs)}\nsaved: {saved}\nduplicates: {duplicates}")
        if not jobs:
            logging.warning("No jobs received; persistence has not been exercised.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
