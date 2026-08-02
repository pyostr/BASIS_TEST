"""Загрузка плагинов на уровне приложения.

Обнаруживает зарегистрированные плагины, загружает включённые по порядку
и подключает маршруты/DI каждого модуля к FastAPI-приложению.
"""

import logging

from fastapi import FastAPI

from src.config.settings import Settings
from src.runtime.modules.discovery import discover_modules
from src.runtime.modules.loader import ModuleContext, load_modules

logger = logging.getLogger(__name__)


def mount_all(app: FastAPI, settings: Settings):
    """Обнаруживает, загружает и подключает все включённые плагины к ``app``.

    Плагины обнаруживаются из ``src.app``, фильтруются по карте включения
    в настройках, инстанцируются через ``ModuleContext``, после чего их просят
    зарегистрировать маршруты/DI вызовом ``mount(app, context)``.
    """
    # обнаруживаем ТОЛЬКО настоящие плагины
    discover_modules()

    context = ModuleContext(settings=settings)
    loaded = load_modules(context)

    logger.info('Loaded app: %s', [m.name for m in loaded])

    for m in loaded:
        logger.info('Mounting module: %s', m.name)
        m.mount(app, context)

    logger.info('Mounted %d module(s)', len(loaded))
