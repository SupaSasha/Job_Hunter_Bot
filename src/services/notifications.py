from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.formatter import build_job_keyboard, format_job_message
from src.models.notification import NotificationORM
from src.models.user import UserORM
from src.repositories.notifications import NotificationRepository
from src.schemas.job import JobDTO
from src.schemas.notifications import NotificationResult
from src.schemas.scoring import ScoreResult


class NotificationService:
    """Own transactions in a dedicated session; retry only explicit rejections.

    A durable pending row reserves delivery before HTTP. After an ambiguous
    timeout or a crash, delivery may have happened; automatic retries are unsafe.
    """

    def __init__(self, session: AsyncSession, client: TelegramClient) -> None:
        self.session = session
        self.client = client
        self.repository = NotificationRepository(session)

    @staticmethod
    def _existing_result(notification: NotificationORM) -> NotificationResult:
        reasons = {
            "sent": "already_sent",
            "pending": "already_pending",
            "failed": "previous_failed",
            "unknown": "delivery_unknown",
            "retryable": "retry_not_claimed",
        }
        return NotificationResult(
            sent=False,
            skipped=True,
            reason=reasons[notification.status],
            telegram_message_id=notification.telegram_message_id,
        )

    async def notify(
        self, *, user: UserORM, job_id: int, job: JobDTO, score: ScoreResult
    ) -> NotificationResult:
        if not user.is_active:
            return NotificationResult(sent=False, skipped=True, reason="inactive_user")
        # Copy scalars before rollback can expire ORM instances.
        user_id, chat_id = user.id, user.telegram_id
        try:
            existing = await self.repository.get_by_user_job(user_id, job_id)
            message = format_job_message(job, score)
            keyboard = build_job_keyboard(job_id, job.url)
            if existing is not None:
                result = self._existing_result(existing)
                if existing.status != "retryable":
                    await self.session.rollback()
                    return result
                notification_id = await self.repository.claim_retryable(
                    existing.id, datetime.now(UTC)
                )
                if notification_id is None:
                    await self.session.rollback()
                    return result
            else:
                notification = await self.repository.add(
                    NotificationORM(
                        user_id=user_id,
                        job_id=job_id,
                        score=score.score,
                        status="pending",
                    )
                )
                notification_id = notification.id
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            original = exc.orig
            if (
                getattr(original, "sqlstate", None) != "23505"
                or getattr(original.__cause__, "constraint_name", None)
                != "uq_notifications_user_job"
            ):
                raise
            try:
                existing = await self.repository.get_by_user_job(user_id, job_id)
                if existing is None:
                    raise exc
                return self._existing_result(existing)
            finally:
                await self.session.rollback()
        except Exception:
            await self.session.rollback()
            raise

        try:
            try:
                message_id = await self.client.send_message(
                    chat_id, message, reply_markup=keyboard
                )
            except Exception as exc:
                retryable = isinstance(exc, TelegramAPIError) and exc.retryable
                retry_at = None
                if retryable and exc.retry_after is not None:
                    retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after)
                await self.repository.mark_failed(
                    notification_id,
                    status="retryable" if retryable else "unknown",
                    retry_after_until=retry_at,
                )
                await self.session.commit()
                if isinstance(exc, TelegramAPIError):
                    return NotificationResult(
                        sent=False, skipped=False, reason=str(exc)
                    )
                raise
            await self.repository.mark_sent(notification_id, message_id)
            await self.session.commit()
            return NotificationResult(
                sent=True, skipped=False, telegram_message_id=message_id
            )
        except Exception:
            # A failed final DB write leaves the committed pending row intact.
            await self.session.rollback()
            raise
