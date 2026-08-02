"""Тест миграций: запускает `alembic upgrade head` на чистой базе Postgres
и проверяет, что ожидаемые таблицы созданы."""

import os
import shutil
import subprocess
from urllib.parse import urlparse

from sqlalchemy import create_engine, text


def _container_db_url(pg_container) -> str:
    """Возвращает URL подключения к контейнеру (оставлен для совместимости с асинхронным вариантом)."""
    return pg_container.get_connection_url().replace('psycopg2', 'psycopg2')


def _parse(url: str) -> dict:
    """Разбирает URL подключения Postgres на переменные окружения POSTGRES_*."""
    parsed = urlparse(url)
    return {
        'POSTGRES_USER': parsed.username or 'test',
        'POSTGRES_PASSWORD': parsed.password or 'test',
        'POSTGRES_HOST': parsed.hostname or 'localhost',
        'POSTGRES_PORT': str(parsed.port or 5432),
        'POSTGRES_DB': parsed.path.lstrip('/') or 'test',
    }


def _create_database(base_url: str, db_name: str) -> None:
    """Создаёт новую базу данных на сервере Postgres."""
    admin = create_engine(base_url + '/postgres')
    with admin.connect() as conn:
        conn.execution_options(isolation_level='AUTOCOMMIT')
        conn.execute(text(f'CREATE DATABASE {db_name}'))
    admin.dispose()


def _drop_database(base_url: str, db_name: str) -> None:
    """Удаляет базу данных, если она существует (идемпотентная очистка)."""
    admin = create_engine(base_url + '/postgres')
    with admin.connect() as conn:
        conn.execution_options(isolation_level='AUTOCOMMIT')
        conn.execute(text(f'DROP DATABASE IF EXISTS {db_name}'))
    admin.dispose()


def test_alembic_upgrade_head(pg_container):
    """Запуск alembic upgrade head на пустой базе создаёт все ожидаемые таблицы."""
    base = _parse(pg_container.get_connection_url())
    base_url = f'postgresql://{base["POSTGRES_USER"]}:{base["POSTGRES_PASSWORD"]}@{base["POSTGRES_HOST"]}:{base["POSTGRES_PORT"]}'

    db_name = 'alembic_test'
    _drop_database(base_url, db_name)
    _create_database(base_url, db_name)

    env = os.environ.copy()
    env.update(
        {
            'POSTGRES_USER': base['POSTGRES_USER'],
            'POSTGRES_PASSWORD': base['POSTGRES_PASSWORD'],
            'POSTGRES_HOST': base['POSTGRES_HOST'],
            'POSTGRES_PORT': base['POSTGRES_PORT'],
            'POSTGRES_DB': db_name,
        }
    )

    try:
        alembic_bin = shutil.which('alembic')
        assert alembic_bin, 'alembic executable not found on PATH'
        result = subprocess.run(
            [alembic_bin, 'upgrade', 'head'],
            capture_output=True,
            text=True,
            env=env,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        assert result.returncode == 0, result.stdout + result.stderr

        engine = create_engine(f'{base_url}/{db_name}')
        with engine.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            }
        engine.dispose()

        assert {
            'payments',
            'payment_attempts',
            'outbox_messages',
            'webhook_deliveries',
        } <= tables
    finally:
        _drop_database(base_url, db_name)
