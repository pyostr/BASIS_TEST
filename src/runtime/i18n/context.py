"""Состояние локали в контексте запроса, используемое для выбора активного языка."""

from contextvars import ContextVar

from pydantic import BaseModel


class Locale(BaseModel):
    """Активная локаль для текущего запроса с опциональным кодом запасной локали."""

    code: str = 'en'
    fallback: str | None = None


locale_ctx: ContextVar[Locale | None] = ContextVar('locale', default=None)


def get_locale_code(default: str = 'en') -> str:
    """Возвращает код активной локали из контекста или ``default``, если ничего не задано."""
    locale = locale_ctx.get()
    return locale.code if locale is not None else default
