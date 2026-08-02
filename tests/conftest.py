"""Общие pytest-фикстуры: Postgres/RabbitMQ testcontainers, асинхронный SQLAlchemy
движок и sessionmaker, in-memory ASGI HTTP-клиент и очистка БД между тестами."""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

os.environ['TESTING'] = '1'

from src.app.module_loader import mount_all
from src.config.settings import Settings
from src.runtime.bootstrap.app_factory import app
from src.runtime.di.containers.payments import PaymentsContainer
from src.runtime.persistence.base import Base


@pytest.fixture(scope='session')
def pg_container():
    """Postgres testcontainer в области видимости сессии."""
    container = PostgresContainer('postgres:18')
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope='session')
def rabbitmq_container():
    """RabbitMQ testcontainer в области видимости сессии."""
    from testcontainers.rabbitmq import RabbitMqContainer

    container = RabbitMqContainer('rabbitmq:3.13')
    container.start()
    yield container
    container.stop()


@pytest_asyncio.fixture()
async def engine(pg_container):
    """Асинхронный движок на основе Postgres-контейнера: схема создаётся при установке и удаляется по завершении."""
    url = pg_container.get_connection_url().replace('psycopg2', 'asyncpg')

    engine = create_async_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture()
async def sessionmaker(engine):
    """Асинхронный sessionmaker, привязанный к тестовому движку."""
    return async_sessionmaker(bind=engine, expire_on_commit=False)


@pytest_asyncio.fixture()
async def client(engine):
    """AsyncClient, запускающий FastAPI-приложение in-memory поверх тестовой базы данных."""
    async_session = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    app.state.engine = engine
    app.state.sessionmaker = async_session
    app.state.payments_container = PaymentsContainer(
        sessionmaker=async_session,
    )
    app.state.settings = Settings()

    if not getattr(app.state, 'modules_mounted', False):
        mount_all(app, Settings())
        app.state.modules_mounted = True

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url='http://test',
    ) as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True)
async def cleanup_db(engine):
    """Autouse-фикстура, очищающая все таблицы перед каждым тестом, чтобы состояние не перетекало между тестами."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
        """)
        )

        tables = [row[0] for row in result]

        if tables:
            tables_sql = ', '.join(tables)
            await conn.execute(
                text(f'TRUNCATE TABLE {tables_sql} RESTART IDENTITY CASCADE')
            )

    yield
