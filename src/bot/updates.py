from src.bot.callbacks import CallbackHandler
from src.bot.commands import CommandHandler
from src.bot.settings import SettingsHandler


async def route_update(
    update: dict,
    *,
    commands: CommandHandler,
    callbacks: CallbackHandler,
    settings: SettingsHandler | None = None,
) -> None:
    if "callback_query" in update:
        callback = update["callback_query"]
        data = callback.get("data") if isinstance(callback, dict) else None
        if (
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
