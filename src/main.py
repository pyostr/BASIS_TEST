"""Точка входа HTTP-сервиса: запуск uvicorn с FastAPI-приложением."""

import uvicorn

from src.config.settings import get_settings


def main() -> None:
    """Запускает сервер uvicorn с host, port и флагом reload из настроек."""
    settings = get_settings()
    uvicorn.run(
        'src.runtime.bootstrap.app_factory:app',
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_RELOAD,
        log_level=settings.LOG_LEVEL,
        access_log=True,
        proxy_headers=True,
        forwarded_allow_ips='*',
    )


if __name__ == '__main__':
    main()
