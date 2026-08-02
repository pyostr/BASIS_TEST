"""Точка входа плагина платежей.

Объявляет плагин платежей и при подключении встраивает маршрутизатор
платежей в FastAPI-приложение под префиксом ``/api/v1``.
"""

import logging

from src.app.payments.presentation.api.v1.payments.payments_router import (
    router as payments_router,
)
from src.runtime.modules import ModuleContext, register

logger = logging.getLogger(__name__)


@register
class PaymentsModule:
    """FastAPI-плагин, подключающий HTTP API платежей.

    Регистрируется в рантайме через декоратор ``@register``; механизм
    обнаружения/загрузки инстанцирует его и вызывает ``mount`` с приложением
    и общим ``ModuleContext``, несущим настройки DI.
    """

    name = 'payments'
    order = 0

    def ready(self) -> bool:
        """Возвращает, выполнены ли зависимости модуля.

        Всегда готов: у модуля платежей нет внешних предусловий.
        """
        return True

    def mount(self, app, context: ModuleContext) -> None:
        """Регистрирует маршрутизатор платежей на ``app`` под ``/api/v1``.

        Args:
            app: Инстанс FastAPI-приложения, которое загружается.
            context: Общий контекст модуля с настройками DI.
        """
        app.include_router(prefix='/api/v1', router=payments_router)
        logger.info('PaymentsModule mounted')
