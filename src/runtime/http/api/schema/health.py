"""Схемы запросов/ответов для health-эндпоинтов."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class HealthStatus(StrEnum):
    """Доступные статусы health-проверки."""

    HEALTHY = 'healthy'
    READY = 'ready'
    NOT_READY = 'not_ready'
    ALIVE = 'alive'


class HealthResponse(BaseModel):
    """Ответ на health-проверку."""

    status: HealthStatus
    service: str

    model_config = ConfigDict(
        json_schema_extra={
            'example': {
                'status': 'healthy',
                'service': 'Базас тестовое',
            }
        }
    )
