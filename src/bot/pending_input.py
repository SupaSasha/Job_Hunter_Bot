import json
from dataclasses import asdict, dataclass

PENDING_TTL_SECONDS = 600
INPUT_ACTIONS = {
    "filters:keywords",
    "filters:reqtech",
    "filters:preftech",
    "filters:extech",
    "filters:min_salary",
    "filters:blacklist_words",
    "filters:blacklist_companies",
    "filters:countries",
    "filters:custom_currency",
    "settings:timezone",
}


@dataclass(frozen=True)
class PendingInput:
    action: str
    message_id: int
    operation: str = "add"


class PendingInputStore:
    """Small expiring Redis record; no raw user input is stored here."""

    def __init__(self, redis):
        self.redis = redis

    @staticmethod
    def key(telegram_id: int) -> str:
        return f"telegram:user:{telegram_id}:pending_input"

    async def set(self, telegram_id: int, state: PendingInput) -> None:
        self._validate(state)
        await self.redis.set(
            self.key(telegram_id), json.dumps(asdict(state)), ex=PENDING_TTL_SECONDS
        )

    @staticmethod
    def _validate(state: PendingInput) -> None:
        if (
            state.action not in INPUT_ACTIONS
            or type(state.message_id) is not int
            or state.message_id <= 0
            or state.operation not in {"add", "remove"}
        ):
            raise ValueError("Invalid pending input state")

    async def get(self, telegram_id: int) -> PendingInput | None:
        value = await self.redis.get(self.key(telegram_id))
        if value is None:
            return None
        try:
            state = PendingInput(**json.loads(value))
            self._validate(state)
            return state
        except (ValueError, TypeError, KeyError):
            await self.clear(telegram_id)
            return None

    async def clear(self, telegram_id: int) -> None:
        await self.redis.delete(self.key(telegram_id))
