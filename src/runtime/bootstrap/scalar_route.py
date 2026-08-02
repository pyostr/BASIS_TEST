"""Регистрация страницы документации Scalar API."""

from fastapi import FastAPI
from scalar_fastapi import (
    AgentScalarConfig,
    Layout,
    OpenAPISource,
    get_scalar_api_reference,
)

from src.config.settings import Settings


def register_scalar_route(app: FastAPI, settings: Settings) -> None:
    """Регистрирует маршрут ``/scalar``, отдающий страницу справочника OpenAPI."""

    @app.get('/scalar', include_in_schema=False)
    async def scalar_html():
        """Отдаёт страницу справочника Scalar API для схемы OpenAPI."""
        return get_scalar_api_reference(
            title=settings.APP_NAME,
            sources=[
                OpenAPISource(
                    title='User API',
                    url='/openapi.json',
                    default=True,
                    agent=AgentScalarConfig(disabled=True),
                ),
            ],
            layout=Layout.MODERN,
            show_sidebar=True,
        )
