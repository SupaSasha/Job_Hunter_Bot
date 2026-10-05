import logging
import re
from dataclasses import dataclass
from typing import Literal

from src.bot.client import TelegramAPIError, TelegramClient
from src.i18n import initial_language, t, user_language
from src.repositories.jobs import JobRepository
from src.repositories.users import UserRepository
from src.services.feedback import FeedbackService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallbackAction:
    job_id: int
    feedback_type: Literal["saved", "rejected"]


def parse_callback_data(data: str) -> CallbackAction | None:
    if not isinstance(data, str):
        return None
    match = re.fullmatch(r"(save|reject):([1-9][0-9]{0,9})", data)
    if match is None:
        return None
    job_id = int(match.group(2))
    # jobs.id is PostgreSQL INTEGER. Bound the input before any DB lookup.
    if job_id > 2**31 - 1:
        return None
    return CallbackAction(
        job_id=job_id,
        feedback_type="saved" if match.group(1) == "save" else "rejected",
    )


class CallbackHandler:
    def __init__(
        self,
        users: UserRepository,
        jobs: JobRepository,
        feedback: FeedbackService,
        client: TelegramClient,
    ) -> None:
        self.users = users
        self.jobs = jobs
        self.feedback = feedback
        self.client = client

    async def _answer(self, callback_id: str, text: str) -> None:
        try:
            await self.client.answer_callback_query(callback_id, text=text)
        except TelegramAPIError as exc:
            # Feedback may already be committed. An expired popup must not keep
            # replaying an old action ahead of subsequent user actions.
            logger.warning("Telegram callback acknowledgement failed: %s", exc)

    async def handle(self, callback: dict) -> None:
        logger.info("Callback received")
        if not isinstance(callback, dict):
            logger.warning("Invalid callback")
            return
        callback_id = callback.get("id")
        if not isinstance(callback_id, str) or not callback_id.strip():
            logger.warning("Invalid callback: missing query ID")
            return
        action = parse_callback_data(callback.get("data"))
        sender = callback.get("from")
        telegram_id = sender.get("id") if isinstance(sender, dict) else None
        language = initial_language(
            sender.get("language_code") if isinstance(sender, dict) else None
        )
        if (
            action is None
            or type(telegram_id) is not int
            or not 0 < telegram_id <= 2**63 - 1
        ):
            logger.warning("Invalid callback")
            await self._answer(callback_id, t("feedback.invalid", language))
            return

        user = await self.users.get_by_telegram_id(telegram_id)
        language = user_language(user, sender.get("language_code"))
        if user is None:
            logger.warning("Unknown user in callback")
            await self._answer(callback_id, t("feedback.unregistered", language))
            return
        if not user.is_active:
            logger.warning("Inactive user in callback")
            await self._answer(callback_id, t("feedback.inactive", language))
            return
        job = await self.jobs.get_by_id(action.job_id)
        if job is None:
            logger.warning("Job not found: job_id=%s", action.job_id)
            await self._answer(callback_id, t("feedback.not_found", language))
            return
        user_id = user.id
        await self.feedback.set_feedback(user_id, action.job_id, action.feedback_type)
        logger.info(
            "Feedback saved: user_id=%s job_id=%s type=%s",
            user_id,
            action.job_id,
            action.feedback_type,
        )
        text = t(
            (
                "feedback.saved"
                if action.feedback_type == "saved"
                else "feedback.rejected"
            ),
            language,
        )
        await self._answer(callback_id, text)
