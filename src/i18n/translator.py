from enum import StrEnum

from src.i18n.en import EN
from src.i18n.es import ES


class Language(StrEnum):
    EN = "en"
    ES = "es"


DEFAULT_LANGUAGE = Language.EN
SUPPORTED_LANGUAGES = tuple(Language)
LANGUAGE_NAMES = {Language.EN: "English", Language.ES: "Español"}


class TranslationError(KeyError):
    """A missing English key is a programming error, never a UI label."""


class LocalizedValidationError(ValueError):
    """Carry a translation key without changing validation or business rules."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(translate(key, DEFAULT_LANGUAGE))


def resolve_language(value: object) -> Language:
    try:
        return Language(value)
    except (ValueError, TypeError):
        return DEFAULT_LANGUAGE


def initial_language(telegram_language_code: object) -> Language:
    if isinstance(
        telegram_language_code, str
    ) and telegram_language_code.lower().startswith(Language.ES.value):
        return Language.ES
    return DEFAULT_LANGUAGE


def user_language(user, telegram_language_code: object = None) -> Language:
    # A persisted choice always wins, including explicit English on Spanish Telegram.
    return (
        resolve_language(user.language)
        if user is not None
        else initial_language(telegram_language_code)
    )


def translate(key: str, language: Language = DEFAULT_LANGUAGE, **params: object) -> str:
    locale = resolve_language(language)
    if key not in EN:
        raise TranslationError(f"Missing English translation: {key}")
    catalog = ES if locale == Language.ES else EN
    return catalog.get(key, EN[key]).format(**params)


t = translate


def display_label(value: str, language: Language = DEFAULT_LANGUAGE) -> str:
    key = f"label.{value}"
    return t(key, language) if key in EN else value


def status_label(value: str, language: Language = DEFAULT_LANGUAGE) -> str:
    key = f"status.{value}"
    return t(key, language) if key in EN else value


def validation_message(error: ValueError, language: Language) -> str:
    if isinstance(error, LocalizedValidationError):
        return t(error.key, language)
    for key, value in EN.items():
        if (
            key.startswith("error.") or key == "filters.source_minimum"
        ) and value == str(error):
            return t(key, language)
    # Unknown exception text may contain input or backend details.
    return t("settings.invalid", language)
