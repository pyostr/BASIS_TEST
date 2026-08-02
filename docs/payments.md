# Модуль payments

Документ описывает модуль обработки платежей: архитектуру (чистая
архитектура / DDD), слои, потоки данных, конечные автоматы, outbox,
доставку webhook и точки расширения.

## Архитектура

Модуль лежит в `src/app/payments/` и построен по чистой архитектуре с
делением на четыре слоя:

```
presentation  →  application  →  domain  ←  infrastructure
```

Зависимости направлены **внутрь**: `presentation` и `infrastructure`
зависят от `application` и `domain`, но не наоборот. `domain` не знает ни о
SQLAlchemy, ни о FastAPI, ни о RabbitMQ.

| Слой | Каталог | Отвечает за |
| --- | --- | --- |
| `domain` | `domain/` | Агрегаты, сущности, value objects, доменные события, порты (репозитории, шлюз, отправитель webhook, UoW) |
| `application` | `application/` | Use cases: команды/запросы CQRS и их обработчики |
| `infrastructure` | `infrastructure/` | Адаптеры: SQLAlchemy (модели, мапперы, репозитории, UoW), RabbitMQ (брокер, consumer, outbox), webhook HTTP-клиент, fake-шлюз |
| `presentation` | `presentation/` | HTTP API v1, Pydantic-схемы, мапперы ответов |

### Ключевые принципы

- **Гексагональный интерфейс** — домен объявляет порты (Protocol):
  `PaymentGateway` (`domain/gateway.py`), `WebhookSender`
  (`domain/webhook_sender.py`), репозитории в `domain/repositories/`,
  фабрика UoW в `domain/uow.py`.
- **Единая транзакция на use case** — декоратор `@transactional()`
  (`shared/application/transaction.py`) создаёт UoW через contextvar;
  обработчики обращаются к нему через `current_uow()`.
- **Бизнес-правила в домене** — конечные автоматы, политика повторов
  (`RetryPolicy`) и валидация value objects живут в `domain`, а не в
  сервисном слое.

## Слои

### Domain

- `domain/aggregates/payment.py` — корневой агрегат `Payment` с конечным
  автоматом и доменными событиями.
- `domain/entities/attempt.py` — сущность `PaymentAttempt` (одно
  взаимодействие со шлюзом).
- `domain/entities/webhook_delivery.py` — сущность `WebhookDelivery`
  (запись доставки webhook в стиле outbox).
- `domain/value_objects/` — `Money`, `IdempotencyKey`, `RetryPolicy`.
- `domain/events/` — базовое `DomainEvent` и конкретные события
  (`PaymentCreated`, `PaymentProcessingStarted`, `PaymentSucceeded`,
  `PaymentFailed`).
- `domain/exceptions/` — `InvalidStateTransition`, `IdempotencyConflict`,
  `PaymentNotFound`, `InvalidPaymentData`.

### Application (CQRS)

- **Команды**: `CreatePaymentCommand`, `ProcessPaymentCommand`.
- **Запросы**: `GetPaymentQuery`.
- **Обработчики**:
  - `CreatePaymentHandler` — создать платёж `pending` + событие outbox в
    одной транзакции; идемпотентно по `Idempotency-Key`.
  - `ProcessPaymentHandler` — захватить платёж `pending→processing`,
    провести через шлюз, финализировать `succeeded/failed`, зафиксировать
    попытку и подготовить доставку webhook.
  - `GetPaymentHandler` — чтение платежа с попытками (без коммита).
  - `DeliverDueWebhooksHandler` — доставка «созревших» webhook батчем с
    применением `RetryPolicy`.
- **DTO**: `PaymentDTO` — проекция платежа для API.

### Infrastructure

- **SQLAlchemy**: модели (`models/`), мапперы домен↔ORM (`mappers/`),
  репозитории (`repositories/`), `SqlAlchemyPaymentsUnitOfWork` (`uow.py`).
- **RabbitMQ**: `broker.py` (брокер + топология), `consumer.py`
  (входящий адаптер с ack/nack/retry/DLQ), `outbox/worker.py` (публикация
  транзакционного outbox).
- **Webhook**: `webhook/client.py` (HTTP POST + HMAC-SHA256), `payload.py`
  (сборка тела), `webhook/worker.py` (цикл опроса).
- **Gateway**: `gateway/fake_gateway.py` — эмулятор шлюза с задержкой
  `2–5 c` и вероятностью отказа `0.1`.

### Presentation

- `presentation/api/v1/payments/payments_router.py` — эндпоинты
  `POST /api/v1/payments` и `GET /api/v1/payments/{payment_id}`, оба
  защищены `X-API-Key`.
- `presentation/schemas/payment.py` — Pydantic-схемы запросов/ответов.
- `presentation/mappers/payment.py` — маппинг DTO в ответ API.

Регистрация в приложении: `module.py` монтирует router под префиксом
`/api/v1`.

## Поток данных

### 1. Создание платежа (API)

```
POST /api/v1/payments
  → require_api_key (X-API-Key)
  → CreatePaymentHandler (транзакция)
      ├─ IdempotencyKey / Money (валидация)
      ├─ Payment.create() → событие PaymentCreated
      ├─ try_insert()  (ON CONFLICT DO NOTHING по idempotency_key)
      │    └─ если ключ уже есть → возвращаем существующий платёж (идемпотентность)
      └─ uow.collect_events() → строка в outbox_messages (та же транзакция)
  → 202 Accepted {payment_id, status: pending, created_at}
```

Атомарность: платёж и outbox-сообщение сохраняются **в одной транзакции**,
поэтому событие не может быть опубликовано без самого платежа.

### 2. Публикация в RabbitMQ (outbox-воркер)

```
OutboxWorker.run() — цикл с периодом OUTBOX_POLL_INTERVAL
  → claim_batch()   (FOR UPDATE SKIP LOCKED, processed_at IS NULL)
  → publish в exchange payments.exchange, routing_key payments.new
      ├─ успех → mark_processed() (processed_at = now)
      └─ сбой → mark_publish_failure() (attempts+1, processed_at остаётся NULL)
  → uow.commit()
```

Семантика **at-least-once**: сообщение, которое не удалось опубликовать,
будет захвачено снова при следующем опросе.

### 3. Обработка платежа (consumer)

```
RabbitMQ payments.new
  → PaymentConsumerHandler.handle()   (manual ack)
      ├─ decode тела; неразбираемое тело → сразу в DLQ
      ├─ event_type != PaymentCreated → ack (не наше)
      ├─ x-death retry_count >= RABBITMQ_MAX_RETRIES → в DLQ
      └─ ProcessPaymentHandler (транзакция)
          ├─ status != PENDING → NOT_PENDING / ALREADY_TERMINAL
          ├─ mark_processing() + begin_processing() (pending→processing,
          │    оптимистичная блокировка по version; конфликт → CLAIM_CONFLICT)
          ├─ begin_attempt() → PaymentAttempt
          ├─ gateway.charge()  (2–5 c, 10% отказ)
          ├─ succeed/fail попытку + mark_succeeded/mark_failed
          │    (маршрут тоже по version; конфликт → RuntimeError)
          ├─ WebhookDelivery.create() (event payment.succeeded|failed)
          └─ один коммит: платёж + попытка + доставка
```

Retry/DLQ управляется **топологией очередей**, а не кодом обработчика:

- основная очередь `payments.new` имеет dead-letter на `payments.retry`;
- `payments.retry` имеет TTL (`RABBITMQ_RETRY_TTL_MS`) и dead-letter обратно
  в `payments.new` (т.е. повторная доставка после задержки);
- количество повторов определяется заголовком `x-death`: при исчерпании
  `RABBITMQ_MAX_RETRIES` сообщение отправляется в `payments.dlq`;
- `nack(requeue=False)` запускает dead-lettering.

### 4. Доставка webhook (webhook-воркер)

```
WebhookWorker.run() — цикл с периодом WEBHOOK_POLL_INTERVAL
  → DeliverDueWebhooksHandler (транзакция)
      → claim_due(batch_size, now)  (SKIP LOCKED, PENDING и next_retry_at <= now)
      → для каждой доставки:
          WebhookClient.send()  (POST + HMAC-SHA256 подпись, таймаут 10 c)
            ├─ 2xx → delivery.mark_success()
            └─ не-2xx / сетевая ошибка → delivery.record_failure()
                 ├─ attempts < max → schedule_retry() (линейный backoff,
                 │    next_retry_at = now + base_delay * attempt)
                 └─ attempts исчерпаны → mark_failed() (терминально)
```

Webhook-доставка реализована как **отдельная таблица-очередь** в БД
(стиль outbox): даже если HTTP-клиент упал, запись о доставке сохраняется и
будет обработана повторно.

## Конечные автоматы

### Payment

```
              begin_processing          mark_succeeded
  PENDING  ──────────────────►  PROCESSING  ─────────────►  SUCCEEDED
                    │                    │
                    │                    └─────────────►  FAILED
                    │                       mark_failed
                    └── (терминальные состояния не имеют исходящих переходов)
```

- `PENDING → PROCESSING` — только `mark_processing()`;
- `PROCESSING → SUCCEEDED | FAILED` — только `mark_succeeded()` /
  `mark_failed()`;
- `SUCCEEDED`/`FAILED` — терминальные (переходы запрещены);
- каждый переход увеличивает `version` и порождает доменное событие;
- недопустимые переходы бросают `InvalidStateTransition`.

Переходы в БД защищены **оптимистичной блокировкой**: репозиторий выполняет
`UPDATE ... WHERE status = expected_status AND version = expected_version`;
`expected_*` берётся из агрегата до перехода, поэтому SQL не дублирует правила
конечного автомата.

### PaymentAttempt

```
  CREATED ──start()──► PROCESSING ──succeed()──► SUCCEEDED
                                   └─fail()───► FAILED
```

### WebhookDelivery

```
  PENDING ──mark_success()──► SUCCESS
      │
      ├──schedule_retry()──► PENDING (attempt+1, next_retry_at)
      └──mark_failed()───► FAILED
```

## Outbox

- **Запись**: `uow.collect_events()` кладёт доменные события в
  `outbox_messages` в той же транзакции, что и изменения агрегата.
- **Формат**: `serialize_event()` превращает dataclass-событие в JSON-словарь
  (datetime/UUID → строки), добавляет `event_type`.
- **Чтение**: `OutboxWorker` забирает батч через `FOR UPDATE SKIP LOCKED`
  (позволяет нескольким воркерам делить работу), публикует в RabbitMQ и
  помечает `processed_at`.

## Гарантии и идемпотентность

1. **Создание платежа** — уникальный `idempotency_key` +
   `ON CONFLICT DO NOTHING`: повторный запрос с тем же ключом возвращает уже
   созданный платёж.
2. **Публикация событий** — outbox в той же транзакции, что и запись;
   at-least-once доставка.
3. **Обработка платежа** — платёж захватывается атомарно
   (`pending→processing` с проверкой version); гонка воркеров приводит к
   `CLAIM_CONFLICT`, повторная финализация исключена.
4. **Доставка webhook** — отдельная таблица-очередь с повторами и backoff;
   payload подписан HMAC-SHA256 (заголовок `X-Webhook-Signature`), есть
   `X-Correlation-ID` и `X-Event-ID`.

## События домена

| Событие | Порождается | Содержимое |
| --- | --- | --- |
| `PaymentCreated` | `Payment.create()` | полные входные данные платежа |
| `PaymentProcessingStarted` | `mark_processing()` | — |
| `PaymentSucceeded` | `mark_succeeded()` | `processed_at` |
| `PaymentFailed` | `mark_failed()` | `reason`, `processed_at` |

Из событий в RabbitMQ публикуется только `PaymentCreated` (см. проверку
`event_type` в `consumer.py`); события жизненного цикла не уходят в брокер —
их финализирует сам обработчик в рамках одной транзакции.

## Конфигурация модуля

Все настройки — в `src/config/settings.py` (секции broker / outbox / webhook /
gateway / auth). Consumer дополнительно настраивается в docker-compose через
переменные окружения (см. `docs/инфраструктура.md`).

## Ключевые сценарии для проверки

1. Создать платёж → получить `202 Accepted`; через 2–5 с статус станет
   `succeeded` или `failed`.
2. Повторить `POST` с тем же `Idempotency-Key` → вернётся тот же платёж.
3. Недоступный `webhook_url` → доставка уходит в повторы, при исчерпании
   попыток становится `failed`.
4. Остановка outbox-воркера во время публикации → сообщение не потеряется,
   будет доставлено после рестарта (at-least-once).
