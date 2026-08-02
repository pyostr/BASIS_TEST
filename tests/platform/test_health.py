"""Тесты эндпоинтов liveness, health и readiness."""

from httpx import AsyncClient


async def test_liveness(client: AsyncClient):
    """Проверка liveness сообщает, что сервис жив."""
    resp = await client.get('/health/liveness')
    assert resp.status_code == 200
    body = resp.json()
    assert body['status'] == 'alive'
    assert 'service' in body


async def test_health(client: AsyncClient):
    """Эндпоинт health сообщает об общем здоровом статусе."""
    resp = await client.get('/health')
    assert resp.status_code == 200
    body = resp.json()
    assert body['status'] == 'healthy'
    assert 'service' in body


async def test_readiness_ok_with_db(client: AsyncClient):
    """Проверка readiness сообщает о готовности, когда база данных доступна."""
    resp = await client.get('/health/readiness')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'ready'
