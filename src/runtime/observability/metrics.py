"""Prometheus-метрики приложения.

Метрики регистрируются в глобальном реестре ``prometheus_client`` (REGISTRY),
поэтому экспортируются через ``/metrics`` (API) и ``start_http_server`` (воркер).
Все гистограммы используют фиксированные bounded-бакеты — без роста памяти.
"""

from prometheus_client import Counter, Gauge, Histogram


class Metrics:
    """Явно объявленный набор бизнес-метрик приложения."""

    def __init__(self) -> None:
        self.payments_total = Counter(
            'payments_total',
            'Итоговое количество обработанных платежей',
            ['status'],
        )
        self.payments_inflight = Gauge(
            'payments_inflight',
            'Платежи, обрабатываемые в данный момент',
        )
        self.payments_processing_duration_seconds = Histogram(
            'payments_processing_duration_seconds',
            'Длительность обработки платежа в секундах',
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
        )
        self.payments_retry_count = Counter(
            'payments_retry_count',
            'Сообщения платежей, отправленные в повтор',
        )
        self.webhook_failures_total = Counter(
            'webhook_failures_total',
            'Неудачные доставки вебхуков',
        )
        self.outbox_messages_total = Counter(
            'outbox_messages_total',
            'Сообщения outbox, опубликованные в брокер',
            ['status'],
        )
        self.worker_cycles_total = Counter(
            'worker_cycles_total',
            'Циклы опроса воркеров',
            ['worker'],
        )


metrics = Metrics()

__all__ = ['Metrics', 'metrics']
