"""Глобальные обработчики исключений, превращающие доменные ошибки и ошибки валидации в JSON-ответы."""

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.runtime.i18n.context import get_locale_code
from src.runtime.i18n.translator import JsonTranslator
from src.runtime.logging.logger import get_request_id
from src.shared.exceptions import DomainException

logger = logging.getLogger(__name__)

DOMAIN_HTTP_STATUS: dict[str, int] = {
    'NOT_FOUND': status.HTTP_404_NOT_FOUND,
    'ALREADY_EXISTS': status.HTTP_409_CONFLICT,
    'IDEMPOTENCY_CONFLICT': status.HTTP_409_CONFLICT,
    'INVALID_STATE_TRANSITION': status.HTTP_409_CONFLICT,
    'VALIDATION_ERROR': status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def register_exception_handlers(app: FastAPI, translator: JsonTranslator):
    """Регистрирует JSON-обработчики исключений для доменных, валидационных и необработанных ошибок.

    Доменные коды сопоставляются с HTTP-статусами через ``DOMAIN_HTTP_STATUS``,
    а сообщения ответов локализуются с помощью переданного переводчика.
    """

    @app.exception_handler(DomainException)
    async def handle_domain(request: Request, exc: DomainException):
        """Возвращает доменную ошибку в виде локализованного JSON с сопоставленным HTTP-статусом."""
        loc = get_locale_code(translator.default)
        http_status = DOMAIN_HTTP_STATUS.get(
            exc.code, status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        message = translator.translate(
            f'error.codes.{exc.code}',
            loc,
            **exc.details,
        )

        return JSONResponse(
            status_code=http_status,
            content={'code': exc.code, 'message': message, 'details': exc.details},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError):
        """Возвращает ошибки валидации FastAPI в виде локализованного JSON-ответа 422."""
        loc = get_locale_code(translator.default)
        message = translator.translate('error.codes.VALIDATION_ERROR', loc)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                'code': 'VALIDATION_ERROR',
                'message': message,
                'details': jsonable_encoder(exc.errors()),
            },
        )

    @app.exception_handler(Exception)
    async def handle_unhandled(request: Request, exc: Exception):
        """Логирует непредвиденные ошибки и возвращает общий ответ 500 с request_id."""
        request_id = get_request_id()
        logger.exception(
            'Unhandled exception on %s %s (request_id=%s)',
            request.method,
            request.url.path,
            request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                'code': 'INTERNAL_ERROR',
                'message': 'Internal server error',
                'request_id': request_id,
            },
        )
