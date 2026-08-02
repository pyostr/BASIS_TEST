"""Структурированное JSON-логирование, middleware для request/correlation ID и контекстные фильтры."""

import logging
import sys
import uuid
from collections.abc import Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Контекстные переменные для отслеживания запросов
_request_id_ctx: ContextVar[str] = ContextVar('request_id', default='none')
_correlation_id_ctx: ContextVar[str] = ContextVar('correlation_id', default='none')


def get_request_id() -> str:
    """Возвращает текущий request ID из контекста (``"none"`` вне запроса)."""
    return _request_id_ctx.get()


def get_correlation_id() -> str:
    """Возвращает текущий correlation ID из контекста (``"none"`` вне запроса)."""
    return _correlation_id_ctx.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Добавляет request_id и correlation_id во все запросы."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Берёт request/correlation ID из заголовков (генерируя их при отсутствии) и возвращает их в ответе."""
        request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
        correlation_id = request.headers.get('X-Correlation-ID', request_id)

        # Устанавливаем в контекстные переменные
        request_token = _request_id_ctx.set(request_id)
        correlation_token = _correlation_id_ctx.set(correlation_id)

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        try:
            response = await call_next(request)

            response.headers['X-Request-ID'] = request_id
            response.headers['X-Correlation-ID'] = correlation_id

            return response
        finally:
            _request_id_ctx.reset(request_token)
            _correlation_id_ctx.reset(correlation_token)


class RequestContextFilter(logging.Filter):
    """Добавляет контекст запроса в записи логов."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Прикрепляет текущие request/correlation ID к записи лога."""
        record.request_id = _request_id_ctx.get()
        record.correlation_id = _correlation_id_ctx.get()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """Настраивает структурированное логирование с контекстом запроса."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s", "request_id": "%(request_id)s", "correlation_id": "%(correlation_id)s"}'
        )
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    logging.getLogger('uvicorn').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Возвращает именованный логгер (тонкая обёртка над ``logging.getLogger``)."""
    return logging.getLogger(name)
