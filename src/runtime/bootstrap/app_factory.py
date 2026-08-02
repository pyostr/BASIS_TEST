"""Композиционный корень HTTP: сборка FastAPI-приложения с middleware, i18n, обработчиками и маршрутами."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config.settings import get_settings
from src.runtime.bootstrap.scalar_route import register_scalar_route
from src.runtime.http.api.routes.health import router as health_router
from src.runtime.http.api.routes.metrics import router as metrics_router
from src.runtime.http.handlers import register_exception_handlers
from src.runtime.i18n.middleware import LocaleMiddleware
from src.runtime.i18n.translator import JsonTranslator
from src.runtime.lifespan.lifespan import lifespan
from src.runtime.logging.logger import RequestIDMiddleware, setup_logging


def create_app() -> FastAPI:
    """Собирает и связывает FastAPI-приложение.

    Настраивает логирование, стек middleware (CORS -> Locale -> RequestID),
    переводимые обработчики исключений, маршрутизаторы health/metrics и документацию Scalar.
    """
    setup_logging()

    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url='/docs' if settings.docs_available else None,
        redoc_url='/redoc' if settings.docs_available else None,
        openapi_url='/openapi.json' if settings.docs_available else None,
    )

    # Порядок важен: CORS -> Locale -> RequestID -> приложение
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=['*'],
        allow_headers=['*'],
    )
    app.add_middleware(LocaleMiddleware, settings=settings)
    app.add_middleware(RequestIDMiddleware)

    translator = JsonTranslator(settings)
    register_exception_handlers(app, translator)

    app.include_router(health_router)
    app.include_router(metrics_router)

    if settings.docs_available:
        register_scalar_route(app, settings=settings)

    return app


app = create_app()
