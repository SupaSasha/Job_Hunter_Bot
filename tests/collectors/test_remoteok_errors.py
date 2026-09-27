from unittest.mock import Mock

import httpx
import pytest

from src.collectors.remoteok import CollectionError, RemoteOKCollector


@pytest.mark.parametrize(
    "status,body",
    [
        (429, "{}"),
        (500, "{}"),
        (200, "not-json"),
        (200, "{}"),
    ],
)
async def test_collection_errors_are_not_successful_empty_batches(
    monkeypatch, status, body
):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text=body, request=request)
        )
    )
    monkeypatch.setattr(
        "src.collectors.remoteok.httpx.AsyncClient", Mock(return_value=client)
    )
    with pytest.raises(CollectionError):
        await RemoteOKCollector().collect()


async def test_valid_empty_source_response_is_successful(monkeypatch):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[], request=request)
        )
    )
    monkeypatch.setattr(
        "src.collectors.remoteok.httpx.AsyncClient", Mock(return_value=client)
    )
    assert await RemoteOKCollector().collect() == []
