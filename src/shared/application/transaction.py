"""Транзакционный декоратор, выполняющий обработчик внутри Unit of Work, управляемого через контекст.

Декоратор создаёт UoW через ``self.uow_factory`` и делает его доступным
обработчику через ``current_uow()``; это исключает изменяемое состояние
на самом обработчике (он может быть синглтоном, как в консьюмере).
Доставка доменных событий выполняется не здесь, а транзакционным outbox:
события пишутся в таблицу outbox в той же транзакции и публикуются воркером.
"""

from contextvars import ContextVar
from functools import wraps
from typing import Any

_current_uow: ContextVar[Any] = ContextVar('current_uow', default=None)


def current_uow() -> Any:
    """Возвращает единицу работы, установленную декоратором ``transactional``.

    Вызывается из тела обработчика, чтобы получить доступ к репозиториям,
    не полагаясь на изменяемое состояние самого обработчика.
    """
    uow = _current_uow.get()
    if uow is None:
        raise RuntimeError('No active UnitOfWork in this context')
    return uow


def transactional(*, commit: bool = True):
    """Выполняет обработчик внутри Unit of Work (UoW).

    Декоратор создаёт UoW через ``self.uow_factory``, делает его доступным
    через ``current_uow()`` и коммитит после успешного возврата, если
    ``commit`` истинно. При ошибке ``UoW.__aexit__`` выполняет откат; контекст
    всегда сбрасывается, чтобы UoW не мог утечь между вызовами.
    """

    def decorator(fn):
        """Оборачивает ``fn`` так, чтобы она выполнялась внутри UoW с коммитом."""

        @wraps(fn)
        async def wrapper(self, *args, **kwargs):
            """Выполняет обработчик в UoW, коммитит и сбрасывает контекст."""
            async with self.uow_factory() as uow:
                token = _current_uow.set(uow)
                try:
                    result = await fn(self, *args, **kwargs)
                    if commit:
                        await uow.commit()
                    return result
                finally:
                    _current_uow.reset(token)

        return wrapper

    return decorator


__all__ = ['current_uow', 'transactional']
