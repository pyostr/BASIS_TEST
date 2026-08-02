"""Типы, описывающие API-модули и их контекст монтирования."""

from dataclasses import dataclass
from typing import Protocol

from fastapi import FastAPI

from src.config.settings import Settings


@dataclass
class ModuleContext:
    """Контекст, передаваемый модулям при монтировании (сейчас — только настройки)."""

    settings: Settings


class APIModule(Protocol):
    """Протокол монтируемого API-модуля с проверками порядка и готовности."""

    name: str
    order: int

    def mount(self, app: FastAPI, context: ModuleContext) -> None:
        """Монтирует маршрутизаторы и связывание модуля в FastAPI-приложение."""

    def ready(self) -> bool:
        """Проверяет, удовлетворены ли зависимости модуля."""
        return True
