"""Сервис перевода, загружающий JSON-файлы локалей и подставляющий параметры в сообщения."""

import json
import logging
from pathlib import Path
from typing import Protocol

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class TranslationService(Protocol):
    """Протокол сервисов, переводящих ключи сообщений в строки локали."""

    def translate(self, key: str, locale: str, **params) -> str:
        """Переводит ``key`` для ``locale``, подставляя ``params`` в плейсхолдеры."""

    def load(self) -> None:
        """Загружает переводы для всех настроенных локалей."""


class JsonTranslator:
    """Переводит точечные ключи с помощью JSON-файлов локалей, с запасным вариантом на локаль по умолчанию."""

    def __init__(
        self,
        settings: Settings,
        translations_dir: Path | None = None,
    ):
        self._dir = translations_dir or (Path(__file__).resolve().parent / 'locales')
        self._cache: dict[str, dict] = {}
        self.default = settings.DEFAULT_LOCALE
        self._load()

    def _load(self) -> None:
        for f in self._dir.rglob('*.json'):
            locale = f.stem
            with open(f, encoding='utf-8') as fh:
                self._cache[locale] = json.load(fh)
        logger.info('Loaded locales: %s', list(self._cache.keys()))

    def translate(self, key: str, locale: str, **params) -> str:
        """Разрешает ``key`` для ``locale`` с запасным вариантом на локаль по умолчанию; возвращает ключ, если он неизвестен.

        ``params`` заменяют плейсхолдеры ``{name}`` в найденном тексте.
        """
        text = self._resolve(key, locale) or self._resolve(key, self.default)
        if text is None:
            return key
        for k, v in params.items():
            text = text.replace(f'{{{k}}}', str(v))
        return text

    def _resolve(self, key: str, locale: str) -> str | None:
        parts = key.split('.')
        obj = self._cache.get(locale)
        for p in parts:
            if isinstance(obj, dict):
                obj = obj.get(p)
            else:
                return None
        return obj
