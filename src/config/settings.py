"""Конфигурация, управляемая окружением, сгруппированная по секциям: app, auth, broker, outbox, webhook, gateway, database и i18n.

``get_settings`` кэширует единственный экземпляр Settings на весь процесс; ``SettingsProvider`` — асинхронная фасадная обёртка над ним.
"""

from enum import StrEnum
from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Environment(StrEnum):
    """Строковые константы для поддерживаемых сред развёртывания."""

    DEVELOPMENT = 'development'
    STAGING = 'staging'
    PRODUCTION = 'production'


class Settings(BaseSettings):
    """Типизированные настройки, читаемые из переменных окружения и файла .env, сгруппированные по именованным секциям."""

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )
    # ----------------------------
    # НАСТРОЙКИ ПРИЛОЖЕНИЯ
    # ----------------------------
    APP_NAME: str = 'Базас тестовое'

    ENVIRONMENT: str = Environment.DEVELOPMENT
    APP_HOST: str = '0.0.0.0'
    APP_PORT: int = 8000
    APP_RELOAD: bool = False
    LOG_LEVEL: str = 'info'

    DOCS_ENABLED: bool = True
    CORS_ORIGINS: list[str] = ['*']
    CORS_ALLOW_CREDENTIALS: bool = False

    API_MODULES: dict[str, bool] = {
        'payments': True,
    }
    API_MODULE_LAZY_LOAD: bool = False

    # ----------------------------
    # ОБСЕРВАБИЛИТИ: метрики
    # ----------------------------
    METRICS_PORT: int = 8001

    APP_VERSION: str = '0.1.0'

    # ----------------------------
    # AUTH ДЛЯ API
    # ----------------------------
    PAYMENTS_API_KEYS: list[str] = ['dev-key']

    # ----------------------------
    # RABBITMQ (брокер платежей)
    # ----------------------------
    RABBITMQ_URL: str = 'amqp://guest:guest@localhost:5672/'
    RABBITMQ_EXCHANGE: str = 'payments.exchange'
    RABBITMQ_EXCHANGE_TYPE: str = 'direct'

    RABBITMQ_ROUTING_KEY: str = 'payments.new'
    RABBITMQ_QUEUE: str = 'payments.new'
    RABBITMQ_RETRY_QUEUE: str = 'payments.retry'
    RABBITMQ_DLQ_QUEUE: str = 'payments.dlq'

    RABBITMQ_RETRY_TTL_MS: int = 5000
    RABBITMQ_MAX_RETRIES: int = 3

    # ----------------------------
    # ВОРКЕР OUTBOX
    # ----------------------------
    OUTBOX_POLL_INTERVAL: float = 1.0
    OUTBOX_BATCH_SIZE: int = 50

    # ----------------------------
    # ДОСТАВКА ВЕБХУКОВ
    # ----------------------------
    WEBHOOK_SECRET: str = 'webhook-dev-secret'
    WEBHOOK_RETRY_ATTEMPTS: int = 3
    WEBHOOK_RETRY_BASE_DELAY: float = 1.0
    WEBHOOK_TIMEOUT: float = 10.0
    WEBHOOK_POLL_INTERVAL: float = 1.0

    # ----------------------------
    # ПЛАТЁЖНЫЙ ШЛЮЗ (эмулятор)
    # ----------------------------
    GATEWAY_MIN_DELAY: float = 2.0
    GATEWAY_MAX_DELAY: float = 5.0
    GATEWAY_FAILURE_RATE: float = 0.1

    # ----------------------------
    # БАЗА ДАННЫХ
    # ----------------------------
    POSTGRES_SCHEMA: str = 'postgresql+asyncpg'
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str = 'localhost'
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str

    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_STATEMENT_TIMEOUT: int = 30000

    STRICT_STARTUP: bool = False

    # ----------------------------
    # Интернационализация (i18n)
    # ----------------------------
    DEFAULT_LOCALE: str = 'en'
    SUPPORTED_LOCALES: list[str] = ['ru', 'en']

    # ----------------------------
    # Производные помощники
    # ----------------------------
    @property
    def is_production(self) -> bool:
        """Возвращает True, если текущее окружение — production."""
        return self.ENVIRONMENT == Environment.PRODUCTION

    @property
    def docs_available(self) -> bool:
        """Документация отдаётся, когда она явно включена или вне production."""
        return self.DOCS_ENABLED or not self.is_production


@lru_cache
def get_settings() -> Settings:
    """Кэшированные на весь процесс настройки (единственный источник истины)."""
    return Settings.model_validate({})


class SettingsProvider:
    """Асинхронная фасадная обёртка над кэшированными настройками."""

    def __init__(self) -> None:
        self._settings: Settings | None = None

    async def load(self) -> Settings:
        """Возвращает кэшированные настройки, загружая их один раз при первом обращении."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings
