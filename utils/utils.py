from fastapi import Request
from .config import settings


def get_lang(request: Request) -> str:
    accept = request.headers.get("Accept-Language", settings.default_language)
    return "ru" if accept.lower().startswith("ru") else "en"
