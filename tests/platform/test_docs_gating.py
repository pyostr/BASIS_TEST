"""Тесты того, что эндпоинты API-документации управляются окружением и настройкой DOCS_ENABLED."""

from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.runtime.bootstrap import app_factory


def _settings(**overrides) -> Settings:
    """Создаёт минимальные Settings для тестов фабрики приложения; переопределения применяются по ключу."""
    return Settings(
        POSTGRES_USER='test',
        POSTGRES_PASSWORD='test',
        POSTGRES_DB='test',
        **overrides,
    )


def test_docs_disabled_in_production(monkeypatch):
    """Эндпоинты документации и OpenAPI отключены в production, при этом health остаётся доступным."""
    monkeypatch.setattr(
        app_factory,
        'get_settings',
        lambda: _settings(ENVIRONMENT='production', DOCS_ENABLED=False),
    )
    app = app_factory.create_app()
    client = TestClient(app)

    assert client.get('/docs').status_code == 404
    assert client.get('/openapi.json').status_code == 404
    assert client.get('/scalar').status_code == 404
    assert client.get('/redoc').status_code == 404

    assert client.get('/health/liveness').status_code == 200


def test_docs_enabled_in_development(monkeypatch):
    """Эндпоинты документации и OpenAPI доступны в development, когда задан DOCS_ENABLED."""
    monkeypatch.setattr(
        app_factory,
        'get_settings',
        lambda: _settings(ENVIRONMENT='development', DOCS_ENABLED=True),
    )
    app = app_factory.create_app()
    client = TestClient(app)

    assert client.get('/docs').status_code == 200
    assert client.get('/openapi.json').status_code == 200
    assert client.get('/scalar').status_code == 200
