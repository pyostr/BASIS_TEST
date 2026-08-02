"""Форматтер ASCII-таблиц для отладки реестра модулей.

Отображает метаданные загруженных плагинов в виде таблицы фиксированной
ширины, подходящей для вывода в терминал или журналы.
"""

from typing import Any


def format_modules_table(items: list[Any]) -> str:
    """Отрисовывает метаданные модулей плагинов в виде ASCII-таблицы.

    Args:
        items: Загруженные записи модулей, каждая из которых предоставляет объект
            ``.module`` (с атрибутами ``name`` и ``order``) и ``.path``.

    Returns:
        Строка с переносами строк, содержащая строку заголовков, разделитель
        и по одной строке на каждый элемент; все ячейки дополнены до ширины колонки.
    """
    headers = ['name', 'order', 'source']

    rows = []
    for it in items:
        m = it.module
        rows.append(
            [
                getattr(m, 'name', '-'),
                str(getattr(m, 'order', '-')),
                it.path,
            ]
        )

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt(row):
        """Отрисовывает одну строку с дополнением до вычисленной ширины колонок."""
        return ' | '.join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))

    sep = '-+-'.join('-' * w for w in widths)

    return '\n'.join([fmt(headers), sep] + [fmt(r) for r in rows])
