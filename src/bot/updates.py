from src.bot.callbacks import CallbackHandler
from src.bot.commands import CommandHandler


async def route_update(
    update: dict, *, commands: CommandHandler, callbacks: CallbackHandler
) -> None:
    if "callback_query" in update:
        await callbacks.handle(update["callback_query"])
        return
    message = update.get("message")
    if isinstance(message, dict):
        text = message.get("text")
        if isinstance(text, str) and text.startswith("/"):
            await commands.handle(message)
