from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.feedback import FeedbackORM
from src.repositories.feedback import FeedbackRepository


class FeedbackService:
    """Own the transaction; use a session without unrelated pending writes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = FeedbackRepository(session)

    async def set_feedback(
        self, user_id: int, job_id: int, feedback_type: str
    ) -> FeedbackORM:
        if feedback_type not in ("saved", "rejected"):
            raise ValueError("feedback_type must be 'saved' or 'rejected'")
        try:
            existing = await self.repository.get_by_user_job(user_id, job_id)
            if existing is None:
                result = await self.repository.add(
                    FeedbackORM(
                        user_id=user_id, job_id=job_id, feedback_type=feedback_type
                    )
                )
            else:
                result = await self.repository.update_type(existing, feedback_type)
            await self.session.commit()
            return result
        except IntegrityError as exc:
            await self.session.rollback()
            original = exc.orig
            if (
                getattr(original, "sqlstate", None) != "23505"
                or getattr(original.__cause__, "constraint_name", None)
                != "uq_feedback_user_job"
            ):
                raise
            try:
                existing = await self.repository.get_by_user_job(user_id, job_id)
                if existing is None:
                    raise exc
                result = await self.repository.update_type(existing, feedback_type)
                await self.session.commit()
                return result
            except Exception:
                await self.session.rollback()
                raise
        except Exception:
            await self.session.rollback()
            raise
