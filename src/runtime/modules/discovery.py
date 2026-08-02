"""Поиск пакетов-плагинов, которые предоставляют точку входа ``module``."""

import importlib
import importlib.util
import logging
import pkgutil

import src.app as modules_pkg

logger = logging.getLogger(__name__)


def discover_modules() -> None:
    """
    Правило плагинов:
    - учитываются только пакеты (директории)
    - загружаются только пакеты, содержащие module.py
    """

    for module in pkgutil.iter_modules(modules_pkg.__path__):
        # пропускаем внутренние / приватные
        if module.name.startswith('_'):
            continue

        base_path = f'{modules_pkg.__name__}.{module.name}'
        try:
            spec = importlib.util.find_spec(f'{base_path}.module')
        except (ModuleNotFoundError, AttributeError):
            # не пакет ИЛИ не импортируемый → игнорируем
            continue

        # нет module.py → это не плагин
        if spec is None:
            continue

        # сначала импортируем пакет (чтобы выполнились декораторы реестра)
        importlib.import_module(base_path)

        # импортируем точку входа
        importlib.import_module(f'{base_path}.module')
