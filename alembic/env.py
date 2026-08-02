import importlib
import pkgutil
from logging.config import fileConfig

from sqlalchemy import create_engine

import src.app as app_pkg
from alembic import context
from src.config.settings import get_settings
from src.runtime.persistence.base import Base


def _import_all_models() -> None:
    """Импортирует все пакеты *.infrastructure.models, чтобы они зарегистрировались на Base.metadata."""
    for mod in pkgutil.walk_packages(app_pkg.__path__, prefix=f'{app_pkg.__name__}.'):
        if mod.name.endswith('infrastructure.models'):
            importlib.import_module(mod.name)


_import_all_models()

config = context.config

settings = get_settings()

database_url = (
    f'postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}'
    f'@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/'
    f'{settings.POSTGRES_DB}'
)

config.set_main_option('sqlalchemy.url', database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option('sqlalchemy.url')
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = create_engine(database_url)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
