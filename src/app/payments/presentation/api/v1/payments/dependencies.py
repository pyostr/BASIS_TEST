"""Общие FastAPI-зависимости для маршрутов платежей.

Предоставляет защиту аутентификации ``X-API-Key``, используемую
маршрутизатором платежей.
"""

from fastapi import Header, HTTPException, Request, status

from src.config.settings import get_settings


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(None, alias='X-API-Key'),
) -> None:
    """Отклоняет запрос, если не предоставлен валидный ``X-API-Key``.

    Значение заголовка должно присутствовать и совпадать с одним из ключей
    в ``Settings.PAYMENTS_API_KEYS``. Предпочитает настройки, уже сохранённые
    в ``app.state``, а при их отсутствии переходит к кэшированным настройкам процесса.

    Raises:
        HTTPException: 401, когда ключ отсутствует или не разрешён.
    """
    settings = getattr(request.app.state, 'settings', None) or get_settings()
    if not x_api_key or x_api_key not in settings.PAYMENTS_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid API key',
        )


__all__ = ['require_api_key']
