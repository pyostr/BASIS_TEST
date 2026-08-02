"""Пробы health, readiness и liveness."""

from fastapi import APIRouter, Request, Response, status

from src.config.settings import get_settings
from src.runtime.http.api.schema.health import HealthResponse, HealthStatus
from src.runtime.http.api.services.health import check_database

router = APIRouter(
    prefix='',
    tags=['Health'],
)


def _service_name(request: Request) -> str:
    settings = getattr(request.app.state, 'settings', None)
    if settings is not None:
        return settings.APP_NAME
    return get_settings().APP_NAME


@router.get(
    '/health',
    summary='Health check',
    description='Returns the current health status of the service.',
    response_description='Health status.',
    response_model=HealthResponse,
)
async def health_check(request: Request) -> HealthResponse:
    """
    Проверяет, что приложение запущено.

    Returns:
        HealthResponse, содержащий статус приложения.
    """

    return HealthResponse(
        status=HealthStatus.HEALTHY,
        service=_service_name(request),
    )


@router.get(
    '/health/readiness',
    summary='Readiness probe',
    description=(
        'Checks whether the application is ready to serve traffic. '
        'Currently verifies database connectivity.'
    ),
    response_description='Readiness status.',
    response_model=HealthResponse,
    responses={
        status.HTTP_200_OK: {
            'description': 'Application is ready.',
            'content': {
                'application/json': {
                    'example': {
                        'status': 'ready',
                        'service': 'Базас тестовое',
                    }
                }
            },
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            'description': 'Application is not ready.',
            'content': {
                'application/json': {
                    'example': {
                        'status': 'not_ready',
                        'service': 'Базас тестовое',
                    }
                }
            },
        },
    },
)
async def readiness(
    request: Request,
    response: Response,
) -> HealthResponse:
    """
    Проверяет, что все требуемые зависимости доступны.

    Returns:
        HealthResponse со статусом READY, если приложение может обрабатывать запросы.
        Возвращает NOT_READY с HTTP 503, если зависимость недоступна.
    """

    engine = request.app.state.engine

    if not await check_database(engine):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return HealthResponse(
            status=HealthStatus.NOT_READY,
            service=_service_name(request),
        )

    return HealthResponse(
        status=HealthStatus.READY,
        service=_service_name(request),
    )


@router.get(
    '/health/liveness',
    summary='Liveness probe',
    description='Checks whether the application process is alive.',
    response_description='Liveness status.',
    response_model=HealthResponse,
)
async def liveness(request: Request) -> HealthResponse:
    """
    Проверяет, что процесс приложения жив.

    Returns:
        HealthResponse, указывающий, что сервис жив.
    """

    return HealthResponse(
        status=HealthStatus.ALIVE,
        service=_service_name(request),
    )
