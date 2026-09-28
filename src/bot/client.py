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
        self._base_url = f"https://api.telegram.org/bot{token.strip()}"
        self._timeout = timeout
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
        result = await self._request("sendMessage", payload)
        if not isinstance(result, dict):
            raise TelegramAPIError("Telegram returned an unexpected response")
        message_id = result.get("message_id")
        if type(message_id) is not int or message_id <= 0:
            raise TelegramAPIError("Telegram response has no valid message_id")
        return message_id

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> None:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = await self._request("editMessageText", payload)
        if (
            not isinstance(result, dict)
            or type(result.get("message_id")) is not int
            or result["message_id"] != message_id
        ):
            raise TelegramAPIError("Telegram returned an invalid edited message")

    async def _request(
        self, method: str, payload: dict, *, read_timeout: float | None = None
    ) -> object:
        options = {}
        if read_timeout is not None:
            options["timeout"] = httpx.Timeout(self._timeout, read=read_timeout)
        try:
            response = await self._client.post(
                f"{self._base_url}/{method}", json=payload, **options
            )
        except httpx.TimeoutException:
            raise TelegramAPIError("Telegram request timed out") from None
        except httpx.RequestError:
            raise TelegramAPIError("Telegram network error") from None

        if method == "editMessageText" and response.status_code == 400:
            try:
                error = response.json()
            except ValueError:
                error = None
            if (
                isinstance(error, dict)
                and error.get("ok") is False
                and error.get("error_code") == 400
                and str(error.get("description", "")).startswith(
                    "Bad Request: message is not modified"
                )
            ):
                return {"message_id": payload["message_id"]}
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
            raise TelegramAPIError(f"Telegram API rejected {method}{suffix}")
        if body.get("ok") is not True or "result" not in body:
            raise TelegramAPIError("Telegram returned an unexpected response")
        return body["result"]

    async def get_bot_username(self) -> str:
        result = await self._request("getMe", {})
        if not isinstance(result, dict) or result.get("is_bot") is not True:
            raise TelegramAPIError("Telegram returned an invalid bot identity")
        username = result.get("username")
        if not isinstance(username, str) or not re.fullmatch(
            r"[A-Za-z0-9_]+", username
        ):
            raise TelegramAPIError("Telegram returned an invalid bot username")
        return username

    async def get_updates(
        self, offset: int | None = None, timeout: int = 30
    ) -> list[dict]:
        if type(timeout) is not int or timeout < 0:
            raise ValueError("Telegram polling timeout must be a nonnegative integer")
        if offset is not None and type(offset) is not int:
            raise ValueError("Telegram update offset must be an integer")
        payload = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        result = await self._request(
            "getUpdates", payload, read_timeout=max(self._timeout, timeout + 10.0)
        )
        if not isinstance(result, list) or any(
            not isinstance(update, dict)
            or type(update.get("update_id")) is not int
            or update["update_id"] < 0
            for update in result
        ):
            raise TelegramAPIError("Telegram returned invalid updates")
        return result

    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None
    ) -> None:
        payload = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = text
        result = await self._request("answerCallbackQuery", payload)
        if result is not True:
            raise TelegramAPIError("Telegram did not acknowledge callback query")
