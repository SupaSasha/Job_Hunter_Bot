from string import Formatter

import pytest

from src.i18n import Language, TranslationError, initial_language, t, user_language
from src.i18n.en import EN
from src.i18n.es import ES
from src.i18n.scoring import STATIC_RULES, format_score_rule
from src.models.user import UserORM


def test_catalog_parity_and_interpolation_fields():
    assert EN.keys() == ES.keys()
    formatter = Formatter()
    for key in EN:

        def fields(value):
            return {field for _, field, _, _ in formatter.parse(value) if field}

        assert fields(EN[key]) == fields(ES[key]), key
        params = {field: "value" for field in fields(EN[key])}
        assert t(key, Language.EN, **params)
        assert t(key, Language.ES, **params)


def test_locale_translation_interpolation_and_unknown_key(monkeypatch):
    assert t("settings.title", Language.EN) == "⚙️ Settings"
    assert t("settings.title", Language.ES) == "⚙️ Configuración"
    assert "5 nuevas vacantes" in t(
        "digest.summary", Language.ES, count=5, matches="Job {raw}"
    )
    assert "Job {raw}" in t("digest.summary", Language.ES, count=5, matches="Job {raw}")
    monkeypatch.delitem(ES, "settings.title")
    assert t("settings.title", Language.ES) == "⚙️ Settings"
    with pytest.raises(TranslationError, match="Missing English translation"):
        t("missing.key", Language.ES)


@pytest.mark.parametrize(
    "code,expected",
    [
        (None, Language.EN),
        ("en", Language.EN),
        ("es-UY", Language.ES),
        ("ES-mx", Language.ES),
        ("pt", Language.EN),
    ],
)
def test_initial_telegram_language_and_persisted_choice(code, expected):
    assert initial_language(code) == expected
    assert user_language(None, code) == expected
    assert user_language(UserORM(language=Language.EN), code) == Language.EN
    assert user_language(UserORM(language=Language.ES), code) == Language.ES


@pytest.mark.parametrize("rule", list(STATIC_RULES))
def test_all_static_score_explanations_translated_without_mutation(rule):
    assert format_score_rule(rule, Language.EN) == rule
    assert format_score_rule(rule, Language.ES) != rule


@pytest.mark.parametrize(
    "rule,expected",
    [
        (
            "Preferred skills matched (1/2): +10",
            "Habilidades preferidas coincidentes (1/2): +10",
        ),
        (
            "Required skills matched (1/2): +5",
            "Habilidades requeridas coincidentes (1/2): +5",
        ),
        (
            "Keywords matched (1/2): +8",
            "Palabras clave coincidentes (1/2): +8",
        ),
        (
            "Region matches user preferences: +10",
            "La región coincide con tus preferencias: +10",
        ),
        ("Timezone within 1 hour: +7", "Compatibilidad horaria (1 h): +7"),
        (
            "Timezone difference: 3 hours: no adjustment",
            "Diferencia horaria de 3h: sin ajuste",
        ),
        (
            "Inferred experience differs from user preferences: -5",
            "La experiencia inferida difiere de tus preferencias: -5",
        ),
        ("Salary meets user minimum: +5", "El salario alcanza tu mínimo: +5"),
        (
            "Employment matches user preferences: +5",
            "El empleo coincide con tus preferencias: +5",
        ),
        (
            "Remote matches user preference: +5",
            "Remoto coincide con tu preferencia: +5",
        ),
    ],
)
def test_dynamic_score_explanations(rule, expected):
    assert format_score_rule(rule, Language.ES) == expected
    assert format_score_rule(rule, Language.EN) == rule
