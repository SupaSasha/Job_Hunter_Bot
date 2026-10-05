from src.bot.callbacks import CallbackHandler
from src.bot.commands import CommandHandler
from src.bot.filters import FiltersHandler
from src.bot.settings import SettingsHandler


async def route_update(
    update: dict,
    *,
    commands: CommandHandler,
    callbacks: CallbackHandler,
    settings: SettingsHandler | None = None,
    filters: FiltersHandler | None = None,
) -> None:
    if "callback_query" in update:
        callback = update["callback_query"]
        data = callback.get("data") if isinstance(callback, dict) else None
        if (
            filters is not None
            and isinstance(data, str)
            and data.startswith("filters:")
        ):
            await filters.handle(callback)
        elif (
            settings is not None
            and isinstance(data, str)
            and data.startswith(("settings:", "tz:", "time:", "score:"))
        ):
            await settings.handle(callback)
        else:
            await callbacks.handle(callback)
        return
    message = update.get("message")
    if isinstance(message, dict):
        text = message.get("text")
        if isinstance(text, str) and text.startswith("/"):
            await commands.handle(message)
        elif isinstance(text, str) and filters is not None:
            await filters.handle_input(message)
