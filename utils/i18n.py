from babel.dates import format_datetime
from babel.numbers import format_currency
from datetime import datetime

# простые словари переводов (добавлять по мере нужды)
TRANSLATIONS = {
    "insufficient_funds": {
        "en": "Insufficient funds",
        "ru": "Недостаточно средств",
    },
    "account_not_found": {"en": "Account not found", "ru": "Счёт не найден"},
    "unauthorized": {"en": "Unauthorized", "ru": "Не авторизован"},
    "invalid_credentials": {
        "en": "Invalid credentials",
        "ru": "Неверные учетные данные",
    },
    "user_exists": {
        "en": "User already exists",
        "ru": "Пользователь уже существует",
    },
}


def t(key: str, lang: str = "en") -> str:
    values = TRANSLATIONS.get(key)
    if not values:
        return key
    return values.get(lang, values.get("en", key))


def get_locale(lang: str) -> str:
    if lang.lower().startswith("ru"):
        return "ru_RU"
    return "en_US"


def format_money(amount: float, currency: str, lang: str = "en") -> str:
    loc = get_locale(lang)
    return format_currency(amount, currency, locale=loc)


def format_dt(dt: datetime, lang: str = "en") -> str:
    loc = get_locale(lang)
    return format_datetime(dt, locale=loc)
