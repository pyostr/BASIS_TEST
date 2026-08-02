"""Тесты глобальных HTTP-обработчиков ошибок приложения и контекста локали."""

from fastapi import APIRouter
from fastapi.testclient import TestClient

from src.runtime.bootstrap.app_factory import app
from src.runtime.i18n.context import get_locale_code
from src.shared.exceptions import NotFoundError

_test_router = APIRouter()


@_test_router.get('/_test/domain-error')
async def domain_error():
    raise NotFoundError(details={'resource': 'test'})


@_test_router.get('/_test/unhandled')
async def unhandled_error():
    """Маршрут, бросающий необработанное исключение для проверки безопасного обработчика 500."""
    raise RuntimeError('boom')


@_test_router.get('/_test/validated')
async def validated(required: int):
    return {'ok': required}


app.include_router(_test_router)

client = TestClient(app, raise_server_exceptions=False)


def test_unknown_route_returns_json_404():
    """Несопоставленный маршрут возвращает JSON-404."""
    resp = client.get('/does-not-exist')
    assert resp.status_code == 404


def test_domain_exception_mapped_to_http_status():
    """Доменное исключение преобразуется в структурированный JSON-ответ об ошибке."""
    resp = client.get('/_test/domain-error')
    assert resp.status_code == 404
    body = resp.json()
    assert body['code'] == 'NOT_FOUND'
    assert body['details'] == {'resource': 'test'}
    assert body['message']


def test_validation_error_shape():
    """Ошибки валидации запроса возвращают стандартную форму ошибки валидации."""
    resp = client.get('/_test/validated')
    assert resp.status_code == 422
    body = resp.json()
    assert body['code'] == 'VALIDATION_ERROR'
    assert body['details']


def test_unhandled_exception_returns_safe_500_with_request_id():
    """Необработанные исключения возвращают безопасный 500, скрывающий внутренности, но содержащий request id."""
    resp = client.get('/_test/unhandled')
    assert resp.status_code == 500
    body = resp.json()
    assert body['code'] == 'INTERNAL_ERROR'
    assert 'boom' not in body['message']
    assert body['request_id']


def test_locale_ctx_has_default_after_request():
    """После запроса контекст локали возвращается к английскому языку по умолчанию."""
    assert get_locale_code() == 'en'
