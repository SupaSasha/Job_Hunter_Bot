"""Redact credentials in HTTP client diagnostics without changing requests."""

import logging
import re


class NetworkLogFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.secrets: set[str] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = re.sub(r"/bot[^/\s\"']+", "/bot<redacted>", message)
        redacted = re.sub(
            r"([?&]api_key=)[^&\s\"'<>\\]+",
            r"\1<redacted>",
            redacted,
            flags=re.IGNORECASE,
        )
        # Jooble authenticates in the last /api/<key> path segment. Relative
        # httpcore request targets omit the hostname, so redact both forms.
        redacted = re.sub(
            r"(/api/)[^/?\s\"'<>\\]+(?=[?\s\"'<>\\]|$)",
            r"\1<redacted>",
            redacted,
        )
        for secret in sorted(self.secrets, key=len, reverse=True):
            # httpcore may render headers as repr(bytes), escaping quotes/slashes.
            for value in (repr(secret.encode())[2:-1], repr(secret)[1:-1], secret):
                redacted = redacted.replace(value, "<redacted>")
        if message != redacted:
            record.msg = redacted
            record.args = ()
        return True


_filter = NetworkLogFilter()


def install_network_log_filter(*, secrets: tuple[str, ...] = ()) -> None:
    _filter.secrets.update(value for value in secrets if value)
    # httpx logs URLs at INFO; httpcore can log request targets at DEBUG.
    for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
        logging.getLogger(name).addFilter(_filter)
