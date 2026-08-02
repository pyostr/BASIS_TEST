"""Система модулей-плагинов: регистрация, поиск и загрузка плагинов APIModule."""

from src.runtime.modules.loader import load_modules, register, register_lazy
from src.runtime.modules.types import APIModule, ModuleContext

__all__ = [
    'APIModule',
    'ModuleContext',
    'load_modules',
    'register',
    'register_lazy',
]
