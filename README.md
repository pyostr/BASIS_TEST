# БАЗИС тестовое

Асинхронный сервис обработки платежей: FastAPI + PostgreSQL + RabbitMQ.
Создаёшь платёж через API - дальше он сам обрабатывается (шлюз, вебхуки),
а за всем можно следить в Grafana: метрики, логи, дашборды.

## Пометка
1. В scalar по умолчанию добавлен X-API-Key заголовок с ключом авторизации
2. Так же кнопка генерации UUID7 для Idempotency-Key
3. Поля для схем API имеют значения по умолчанию

Просто для удобства просмотра и теста
Так же работает воркер для имитации проведения платежей (до 1200 запросов в час)

## Документация

- [Модуль payments](docs/payments.md) — архитектура, потоки данных, конечные автоматы, outbox, webhook.
- [Инфраструктура](docs/инфраструктура.md) — docker-compose, nginx, мониторинг, blue-green, запуск.
- [Тестовое задание (форматированное)](docs/ТЗ.md)

## Что умеет система

Один запрос к API запускает цепочку:

1. **API** принимает платёж (`POST /api/v1/payments`) и сразу отвечает `202 Accepted`.
2. Платёж сохраняется в БД и через **outbox** (таблица `outbox_messages`) попадает в очередь **RabbitMQ**.
3. **Consumer** (воркер) забирает сообщение и «проводит» платёж через платёжный шлюз.
4. **Шлюз** - эмулятор: думает 2-5 секунд и с вероятностью 10% отклоняет платёж
   (чтобы в системе была и статистика отказов). Отказ сохраняется как попытка.
5. Результат: платёж получает статус `succeeded` или `failed`.
6. **Вебхук**: на `webhook_url` уходит уведомление о результате (с подписью HMAC),
   при неудаче - повторы с backoff.

Метрики и логи собираются в **Prometheus** и **Loki**, дашборды - в **Grafana**.

## Стек

- FastAPI + Pydantic v2, SQLAlchemy 2.0 (async) + asyncpg
- PostgreSQL, Alembic (миграции)
- RabbitMQ + FastStream (outbox / consumer / retry / DLQ)
- Prometheus + Grafana + Loki + Promtail (метрики и логи)
- Docker + docker compose, nginx (единая точка входа)
- Ruff + pytest (качество кода)

## Продакшен (уже развёрнуто)

| Что                                 | URL                                                |
|-------------------------------------|----------------------------------------------------|
| Документация API (Scalar)           | https://demo-market.ru/scalar                      |
| API (корневой адрес)                | https://demo-market.ru/api/v1                      |
| Дашборды Grafana (admin / admin123) | https://grafana.demo-market.ru/dashboards          |
| Дашборд «Payments Overview»         | https://grafana.demo-market.ru/d/payments-overview |
| Healthcheck                         | https://demo-market.ru/healthz                     |
| Вебхук уведомлений платежа          | https://smee.io/QdTdSWuNct1STc1                    |

В проде API работает по **blue-green** схеме (два контейнера, ротация без простоя),
все внутренние сервисы (БД, RabbitMQ, consumer, Prometheus, Loki, Grafana) наружу
не открыты - снаружи смотрит только nginx.

## Запуск локально с Grafana и мониторингом (всё сразу)

```bash
poetry install
cp .env.example .env    # при желании поправьте POSTGRES_*
docker compose up --build
```

Миграции применяются автоматически при старте API. Всё открывается через один
nginx на порту **8601**, поддомены `*.localhost` резолвятся сами (без /etc/hosts):

| Сервис | Адрес |
| --- | --- |
| Список всех сервисов | http://localhost:8601 |
| API + документация (Scalar) | http://api.localhost:8601 |
| Метрики API | http://api.localhost:8601/metrics |
| Метрики consumer | http://consumer.localhost:8601/metrics |
| Prometheus | http://prometheus.localhost:8601 |
| Grafana (admin/admin) | http://grafana.localhost:8601 |
| Логи (Loki) | см. Grafana → Explore → Loki |
| RabbitMQ Management (guest/guest) | http://rabbitmq.localhost:8601 |

Проверка, что всё поднялось: `http://api.localhost:8601/health/readiness` → `{"status":"ready"}`.

## Запуск только приложения (без мониторинга)

Самый простой способ - без Docker для приложения, только БД в контейнере:

```bash
poetry install
cp .env.example .env

# БД (в контейнере)
docker run -d --name basis-pg \
  -e POSTGRES_USER=pyostr -e POSTGRES_PASSWORD=1503oreolMYSQL \
  -e POSTGRES_DB=demo_platform_db -p 5432:5432 postgres:17-alpine

# миграции и запуск API
poetry run alembic upgrade head
poetry run python -m src.main
```

Открывается http://localhost:8000/scalar.

Если нужна полная обработка платежей (consumer с outbox/вебхуками), вторым процессом:

```bash
poetry run python -m src.runtime.bootstrap.worker_main
```

Версия «только приложение» через docker: `docker compose up --build api consumer`
(поднимет также БД и RabbitMQ, но без nginx наружу API не публикуется - удобнее вариант выше).

## Создать тестовый платёж

```bash
curl -X POST http://api.localhost:8601/api/v1/payments \
  -H "X-API-Key: dev-key" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 199.90,
    "currency": "RUB",
    "description": "Подписка Pro",
    "metadata": {"user_id": "u42"},
    "webhook_url": "http://localhost:9000/webhook"
  }'
```

Ответ `202 Accepted` c `payment_id`. Через 2–5 секунд платёж окажется
`succeeded` или `failed` (см. Grafana или `GET /api/v1/payments/{id}`).

## Генератор нагрузки

`active_worker.py` эмулирует «пользователей», которые создают платежи по одному
и пачками (случайные суммы/валюты, иногда повторяют idempotency-ключ).
Удобно, чтобы набить статистику в Grafana.

```bash
LOAD_BASE_URL=http://api.localhost:8601 poetry run python active_worker.py
```

Параметры через переменные `LOAD_*`: `LOAD_USERS`, `LOAD_RATE`, `LOAD_MAX_BATCH`,
`LOAD_RUN_SECONDS`, `LOAD_WEBHOOK_URL`, `LOAD_API_KEYS` и др. (см. `Config.from_env`).

## Конфигурация (env)

| Переменная | По умолчанию                         | Описание |
| --- |--------------------------------------| --- |
| `ENVIRONMENT` | `development`                        | `development` / `production` |
| `POSTGRES_USER/PASSWORD/DB` | -                                    | данные БД |
| `POSTGRES_HOST/PORT` | `localhost`/`5432`                   | адрес БД |
| `PAYMENTS_API_KEYS` | `["dev-key"]`                        | ключи доступа к API (заголовок `X-API-Key`) |
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | адрес брокера |
| `GATEWAY_MIN_DELAY/MAX_DELAY` | `2.0`/`5.0`                          | задержка эмулятора шлюза, сек |
| `GATEWAY_FAILURE_RATE` | `0.1`                                | доля отказов шлюза (0.0–1.0) |
| `WEBHOOK_SECRET` | `webhook-dev-secret`                 | секрет для подписи вебхуков |
| `METRICS_PORT` | `8001`                               | порт метрик consumer |

## Где смотреть логи и ошибки

Логи всех контейнеров собираются через Promtail в **Loki**. Открыть:
Grafana → **Explore** → datasource **Loki**.

Примеры запросов:

```
{container="basis-test-consumer-1"} |= "finalized: failed"     # почему упали платежи
{container="basis-test-consumer-1"} |= "<payment_id>"          # всё по одному платежу
{container="basis-test-blue"} |= "error"                       # ошибки API
```

Причина упавшего платежа также лежит в БД: таблица `payment_attempts`
(колонки `error`, `gateway_response`).

## Health endpoints

- `GET /health` - сервис жив
- `GET /health/liveness` - процесс работает
- `GET /health/readiness` - готовность (проверка БД)

## Качество кода

```bash
poetry run ruff check src tests alembic
poetry run pytest
```

## Структура проекта

```
src/
├── config/     # настройки (pydantic-settings, .env)
├── runtime/    # связующее: bootstrap, DI, БД, HTTP, логирование, метрики
├── shared/     # общие блоки (исключения, утилиты)
└── app/        # модули (payments): domain / application / infrastructure / presentation
alembic/        # миграции
tests/          # тесты
deploy/         # мониторинг и прод-конфиги: prometheus, grafana, loki, promtail, nginx
active_worker.py  # генератор нагрузки
```
