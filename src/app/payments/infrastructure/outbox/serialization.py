"""JSON-(де)сериализация доменных событий для payload в outbox."""

from dataclasses import fields
from datetime import datetime
from typing import Any
from uuid import UUID

from src.app.payments.domain.events.base import DomainEvent
from src.app.payments.domain.events.payment_events import EVENT_TYPES


def _to_jsonable(value: Any) -> Any:
    """Рекурсивно приводит известные типы событий к JSON-безопасным значениям.

    В отличие от ``json.dumps(default=str)`` не превращает молча в строки
    неизвестные типы, а оставляет их как есть (fail-fast на этапе сериализации).
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


def serialize_event(event: DomainEvent) -> dict[str, Any]:
    """Преобразует доменное событие в JSON-сериализуемый словарь (payload outbox)."""
    data = {
        field.name: _to_jsonable(getattr(event, field.name)) for field in fields(event)
    }
    data['event_type'] = type(event).__name__
    return data


def deserialize_event(data: dict[str, Any]) -> DomainEvent:
    """Восстанавливает доменное событие из словаря payload outbox."""
    event_type = data.get('event_type')
    if not event_type:
        raise ValueError('Missing event_type in payload')

    event_cls = EVENT_TYPES.get(event_type)
    if event_cls is None:
        raise ValueError(f'Unknown event_type: {event_type!r}')

    payload = {k: v for k, v in data.items() if k != 'event_type'}
    # JSON-цикл превращает UUID/даты в строки, поэтому восстанавливаем типизированные
    # поля перед реконструкцией события.
    for key in ('aggregate_id',):
        if key in payload and isinstance(payload[key], str):
            payload[key] = UUID(payload[key])
    for key in ('occurred_at', 'created_at', 'processed_at'):
        if payload.get(key):
            payload[key] = datetime.fromisoformat(payload[key])
    return event_cls(**payload)


__all__ = ['deserialize_event', 'serialize_event']
