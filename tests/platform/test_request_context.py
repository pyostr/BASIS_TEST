"""Тесты проброса request-id и correlation-id через заголовки ответа."""

from httpx import AsyncClient


async def test_echo_request_id_and_correlation_id(client: AsyncClient):
    """Входящие request id и correlation id возвращаются в ответе как есть."""
    resp = await client.get(
        '/health/liveness',
        headers={'X-Request-ID': 'req-123', 'X-Correlation-ID': 'corr-456'},
    )
    assert resp.status_code == 200
    assert resp.headers['X-Request-ID'] == 'req-123'
    assert resp.headers['X-Correlation-ID'] == 'corr-456'


async def test_request_id_auto_generated(client: AsyncClient):
    """Запросу без id автоматически генерируется новый, возвращаемый в ответе."""
    resp = await client.get('/health/liveness')
    assert resp.status_code == 200
    assert resp.headers['X-Request-ID']
