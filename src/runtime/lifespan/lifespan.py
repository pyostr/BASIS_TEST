"""Хук lifespan FastAPI: связывает инфраструктуру при запуске и освобождает ресурсы при остановке."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from src.app.module_loader import mount_all
from src.config.settings import SettingsProvider
from src.runtime.di.containers.payments import PaymentsContainer
from src.runtime.persistence.session import dispose_engine, get_engine, get_sessionmaker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """При запуске настраивает engine, sessionmaker, DI-контейнеры и модули приложения; при остановке корректно освобождает ресурсы."""
    settings_provider = SettingsProvider()
    settings = await settings_provider.load()

    engine = await get_engine(settings)
    sessionmaker = await get_sessionmaker(settings)

    if settings.STRICT_STARTUP:
        async with engine.connect() as conn:
            await conn.execute(text('SELECT 1'))
        logger.info('Database connectivity verified (fail-fast startup)')

    payments_container = PaymentsContainer(sessionmaker=sessionmaker)

    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.payments_container = payments_container

    mount_all(app, settings)

    logger.info('Application started (env=%s)', settings.ENVIRONMENT)

    try:
        yield
    finally:
        await dispose_engine()
        app.state.engine = None
        app.state.sessionmaker = None
        logger.info('Application shut down cleanly')
