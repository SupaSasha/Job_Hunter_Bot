"""Bounded JSON requests with sanitized errors and Retry-After support."""

import json
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

from src.collectors.base import CollectionError


def retry_at(value: str) -> datetime | None:
    try:
        if value.isascii() and value.isdigit():
            return datetime.now(UTC) + timedelta(seconds=int(value))
        result = parsedate_to_datetime(value)
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    source: str,
    params,
    max_response_bytes: int,
) -> object:
    try:
        async with client.stream("GET", url, params=params) as response:
            if response.status_code == 429:
                raise CollectionError(
                    f"{source} HTTP 429 rate limited",
                    retry_at=retry_at(response.headers.get("Retry-After", "")),
                )
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > max_response_bytes:
                    raise CollectionError(f"{source} response exceeds size limit")
    except httpx.TimeoutException:
        raise CollectionError(f"{source} request timed out") from None
    except httpx.HTTPStatusError as exc:
        raise CollectionError(f"{source} HTTP {exc.response.status_code}") from None
    except httpx.HTTPError:
        raise CollectionError(f"{source} network request failed") from None
    try:
        return json.loads(content)
    except (ValueError, UnicodeDecodeError):
        raise CollectionError(f"{source} returned invalid JSON") from None
