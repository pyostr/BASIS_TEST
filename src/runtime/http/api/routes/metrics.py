"""Экспорт метрик приложения в формате Prometheus."""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(
    prefix='',
    tags=['Metrics'],
)


@router.get(
    '/metrics',
    summary='Prometheus metrics',
    description='Exposes application metrics in the Prometheus text exposition format.',
)
async def metrics_endpoint() -> Response:
    """Возвращает метрики Prometheus из глобального реестра."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
