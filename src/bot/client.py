import logging
import re
from typing import Self

import httpx


class TelegramAPIError(Exception):
    """A sanitized error: no token, request URL, or raw response body."""


class _TelegramLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx logs request URLs at INFO; httpcore may log headers at DEBUG.
        message = record.getMessage()
        redacted = re.sub(r"/bot[^/\s\"']+", "/bot<redacted>", message)
        if message != redacted:
            record.msg = redacted
            record.args = ()
        return True


_log_filter = _TelegramLogFilter()
for _logger in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
    logging.getLogger(_logger).addFilter(_log_filter)


class TelegramClient:
    def __init__(
        self,
        token: str,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("Telegram bot token is not configured")
        self._url = f"https://api.telegram.org/bot{token.strip()}/sendMessage"
        self._client = httpx.AsyncClient(
            timeout=timeout, transport=transport, follow_redirects=False
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> int:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            response = await self._client.post(self._url, json=payload)
        except httpx.TimeoutException:
            raise TelegramAPIError("Telegram request timed out") from None
        except httpx.RequestError:
            raise TelegramAPIError("Telegram network error") from None

        if not response.is_success:
            raise TelegramAPIError(f"Telegram HTTP error: {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise TelegramAPIError("Telegram returned invalid JSON") from None
        if not isinstance(body, dict):
            raise TelegramAPIError("Telegram returned an unexpected response")
        if body.get("ok") is False:
            code = body.get("error_code")
            suffix = f" ({code})" if type(code) is int else ""
            raise TelegramAPIError(f"Telegram API rejected sendMessage{suffix}")
        result = body.get("result")
        if body.get("ok") is not True or not isinstance(result, dict):
            raise TelegramAPIError("Telegram returned an unexpected response")
        message_id = result.get("message_id")
        if type(message_id) is not int or message_id <= 0:
            raise TelegramAPIError("Telegram response has no valid message_id")
        return message_id
