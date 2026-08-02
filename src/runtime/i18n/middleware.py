"""HTTP middleware, определяющий локаль запроса из заголовка Accept-Language."""

import logging
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.config.settings import Settings
from src.runtime.i18n.context import Locale, locale_ctx

logger = logging.getLogger(__name__)


class LocaleMiddleware(BaseHTTPMiddleware):
    """Устанавливает локаль запроса из ``Accept-Language`` и предоставляет её через contextvars."""

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.default = settings.DEFAULT_LOCALE
        self.supported = set(settings.SUPPORTED_LOCALES)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Определяет локаль из заголовка запроса и сохраняет её на время всего запроса."""
        raw = request.headers.get('accept-language', '').split(',')[0].strip()
        lang = raw.split(';')[0].split('-')[0]  # упрощение ru-RU -> ru

        if lang in self.supported:
            locale = Locale(code=lang, fallback=self.default)
        else:
            locale = Locale(code=self.default, fallback=None)

        request.state.locale = locale.code

        token = locale_ctx.set(locale)
        try:
            return await call_next(request)
        finally:
            locale_ctx.reset(token)
