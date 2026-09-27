import json
import logging
import traceback

import httpx
import pytest

from src.bot.client import TelegramAPIError, TelegramClient

TOKEN = "123456:test-token"


async def test_send_message_reuses_client_and_redacts_logs(caplog) -> None:
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    with caplog.at_level(logging.DEBUG):
        async with TelegramClient(
            TOKEN, transport=httpx.MockTransport(handler)
        ) as client:
            markup = {
                "inline_keyboard": [[{"text": "Open", "url": "https://example.com"}]]
            }
            for _ in range(2):
                assert await client.send_message(123, "A <B> & C", markup) == 42
            assert not client._client.is_closed
        assert client._client.is_closed
    assert len(requests) == 2
    request = requests[0]
    assert request.method == "POST"
    assert request.url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert json.loads(request.content) == {
        "chat_id": 123,
        "text": "A <B> & C",
        "reply_markup": markup,
    }
    assert TOKEN not in caplog.text
    assert "/bot<redacted>/sendMessage" in caplog.text


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (429, {"ok": False}, "HTTP error: 429"),
        (500, {"ok": False}, "HTTP error: 500"),
        (302, {}, "HTTP error: 302"),
        (200, {"ok": False, "error_code": 403, "description": TOKEN}, "rejected"),
        (200, [], "unexpected response"),
        (200, {"ok": True}, "unexpected response"),
        (200, {"ok": "true", "result": {}}, "unexpected response"),
        (200, {"ok": True, "result": {"message_id": True}}, "message_id"),
        (200, {"ok": True, "result": {"message_id": 0}}, "message_id"),
        (200, {"ok": True, "result": {"message_id": "42"}}, "message_id"),
    ],
)
async def test_bad_responses_are_sanitized(status, body, error) -> None:
    async with TelegramClient(
        TOKEN,
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body)),
    ) as client:
        with pytest.raises(TelegramAPIError, match=error) as caught:
            await client.send_message(123, "message")
    assert TOKEN not in str(caught.value)


async def test_invalid_json() -> None:
    async with TelegramClient(
        TOKEN,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=TOKEN)),
    ) as client:
        with pytest.raises(TelegramAPIError, match="invalid JSON"):
            await client.send_message(123, "message")


@pytest.mark.parametrize("error_class", [httpx.ReadTimeout, httpx.ConnectError])
async def test_network_errors_do_not_expose_request_url(error_class) -> None:
    def handler(request):
        raise error_class(f"failed: {request.url}", request=request)

    async with TelegramClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TelegramAPIError) as caught:
            await client.send_message(123, "message")
    rendered = "".join(traceback.format_exception(caught.value))
    assert TOKEN not in rendered
    assert caught.value.__suppress_context__ is True
