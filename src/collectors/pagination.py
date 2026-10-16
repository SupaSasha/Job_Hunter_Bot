"""Shared bounded cursor collection for official JSON job feeds."""

import asyncio
from collections.abc import Callable

import httpx

from src.collectors.http import fetch_json
from src.schemas.job import JobDTO


async def collect_cursor_pages(
    client: httpx.AsyncClient,
    url: str,
    *,
    source: str,
    params: dict[str, str],
    parser: Callable[[object], tuple[list[JobDTO], str | None]],
    max_pages: int,
    max_response_bytes: int,
) -> list[JobDTO]:
    jobs, seen_ids, seen_cursors = [], set(), set()
    cursor = None
    for page in range(max_pages):
        query = dict(params)
        if cursor is not None:
            query["cursor"] = cursor
        payload = await fetch_json(
            client,
            url,
            source=source,
            params=query,
            max_response_bytes=max_response_bytes,
        )
        batch, next_cursor = parser(payload)
        added = 0
        for job in batch:
            if job.external_id not in seen_ids:
                seen_ids.add(job.external_id)
                jobs.append(job)
                added += 1
        if not batch or not added or next_cursor is None or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        if page + 1 < max_pages:
            await asyncio.sleep(1)
    return jobs
