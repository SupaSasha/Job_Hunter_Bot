from pydantic import BaseModel


class NotificationResult(BaseModel):
    sent: bool
    skipped: bool
    reason: str | None = None
    telegram_message_id: int | None = None
