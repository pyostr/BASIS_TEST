"""Загрузчик API-модулей на основе реестра с прямой и ленивой регистрацией."""

import logging
from typing import Any

from src.runtime.modules.types import APIModule, ModuleContext

_REGISTRY: dict[str, type[APIModule]] = {}

_LAZY_IMPORT: dict[str, str] = {}


def register(
    module_cls: type[APIModule] | None = None,
    lazy_path: str | None = None,
) -> Any:
    """Регистрирует модуль напрямую или как ленивый импорт."""

    def decorator(cls: type[APIModule]) -> type[APIModule]:
        """Декорирует класс модуля, регистрируя его (и, опционально, его ленивый путь)."""
        module_name = getattr(cls, 'name', cls.__name__)
        _REGISTRY[module_name] = cls
        if lazy_path:
            _LAZY_IMPORT[module_name] = lazy_path
        return cls

    if module_cls is not None:
        module_name = getattr(module_cls, 'name', module_cls.__name__)
        _REGISTRY[module_name] = module_cls
        if lazy_path:
            _LAZY_IMPORT[module_name] = lazy_path
        return module_cls

    return decorator


def register_lazy(path: str) -> Any:
    """Регистрирует модуль по пути ленивого импорта."""

    def decorator(cls: type[APIModule]) -> type[APIModule]:
        """Декорирует класс модуля, регистрируя его как лениво импортируемый через ``path``."""
        module_name = getattr(cls, 'name', cls.__name__)
        _REGISTRY[module_name] = cls
        _LAZY_IMPORT[module_name] = path
        return cls

    return decorator


def get_registered_modules() -> dict[str, type[APIModule]]:
    """Возвращает копию зарегистрированных на данный момент классов модулей."""
    return _REGISTRY.copy()


def load_modules(context: ModuleContext) -> list[APIModule]:
    """Создаёт экземпляры включённых модулей, проверяя готовность, и возвращает их, отсортированными по ``order``.

    Raises:
        RuntimeError: если включённый модуль не зарегистрирован или сообщает о своей неготовности.
    """
    enabled = context.settings.API_MODULES
    loaded: list[APIModule] = []

    logger = logging.getLogger(__name__)

    logger.info('Registered plugins: %s', list(_REGISTRY.keys()))

    for name, is_enabled in enabled.items():
        if not is_enabled:
            continue

        module_cls = _REGISTRY.get(name)

        if module_cls is None:
            lazy_path = _LAZY_IMPORT.get(name)
            if lazy_path:
                module_cls = _import_lazy(lazy_path)
            if module_cls is None:
                raise RuntimeError(
                    f"Module '{name}' not registered. "
                    f'Available: {list(_REGISTRY.keys())}'
                )
            _REGISTRY[name] = module_cls

        instance = module_cls()

        if not instance.ready():
            raise RuntimeError(f"Module '{name}' not ready")

        loaded.append(instance)

    loaded.sort(key=lambda m: m.order)
    return loaded


def _import_lazy(path: str) -> type[APIModule] | None:
    """Лениво импортирует модуль по пути (module.path:ClassName)."""
    try:
        if ':' not in path:
            return None
        module_path, attr = path.rsplit(':', 1)
        import importlib

        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    except Exception:
        logging.getLogger(__name__).exception('Failed lazy import: %s', path)
        return None
