"""Интеграционные тесты HTTP API payments: авторизация, валидация
и идемпотентность create-payment, а также get-payment."""

from decimal import Decimal

from src.config.settings import get_settings

PAYMENTS_URL = '/api/v1/payments'
API_KEY = get_settings().PAYMENTS_API_KEYS[0]


def _headers(**overrides):
    """Заголовки запроса по умолчанию (API-ключ + idempotency-ключ) с возможностью переопределения."""
    headers = {'X-API-Key': API_KEY, 'Idempotency-Key': 'client-ref-1'}
    headers.update(overrides)
    return headers


def _payload(**overrides):
    """Корректное тело create-payment по умолчанию с возможностью переопределения."""
    payload = {
        'amount': '150.00',
        'currency': 'RUB',
        'description': 'order #1',
        'metadata': {'user': 42},
        'webhook_url': 'https://example.com/hook',
    }
    payload.update(overrides)
    return payload


class TestCreatePaymentAuth:
    """Сценарии авторизации для эндпоинта create-payment."""

    async def test_missing_api_key_401(self, client):
        """Запрос без API-ключа отклоняется с кодом 401."""
        response = await client.post(
            PAYMENTS_URL, json=_payload(), headers={'Idempotency-Key': 'k'}
        )
        assert response.status_code == 401

    async def test_invalid_api_key_401(self, client):
        """Запрос с неизвестным API-ключом отклоняется с кодом 401."""
        response = await client.post(PAYMENTS_URL, json=_payload(), headers=_headers())
        response = await client.post(
            PAYMENTS_URL,
            json=_payload(),
            headers=_headers(**{'X-API-Key': 'wrong'}),
        )
        assert response.status_code == 401


class TestCreatePayment:
    """Сценарии create-payment: правила валидации и идемпотентная повторная отправка."""

    async def test_create_returns_202(self, client):
        """Корректный запрос принимается и возвращает платёж в статусе pending с id и created_at."""
        response = await client.post(PAYMENTS_URL, json=_payload(), headers=_headers())
        assert response.status_code == 202

        body = response.json()
        assert body['payment_id']
        assert body['status'] == 'pending'
        assert body['created_at']

    async def test_missing_idempotency_header_422(self, client):
        """Отсутствующий заголовок Idempotency-Key отклоняется с кодом 422."""
        response = await client.post(
            PAYMENTS_URL,
            json=_payload(),
            headers={'X-API-Key': API_KEY},
        )
        assert response.status_code == 422

    async def test_zero_amount_422(self, client):
        """Нулевая сумма отклоняется с кодом 422."""
        response = await client.post(
            PAYMENTS_URL,
            json=_payload(amount='0'),
            headers=_headers(),
        )
        assert response.status_code == 422

    async def test_invalid_currency_422(self, client):
        """Неподдерживаемая валюта отклоняется с кодом 422."""
        response = await client.post(
            PAYMENTS_URL,
            json=_payload(currency='GBP'),
            headers=_headers(),
        )
        assert response.status_code == 422

    async def test_invalid_webhook_url_422(self, client):
        """Не-HTTP URL вебхука отклоняется с кодом 422."""
        response = await client.post(
            PAYMENTS_URL,
            json=_payload(webhook_url='ftp://example.com'),
            headers=_headers(),
        )
        assert response.status_code == 422

    async def test_repeated_key_returns_same_payment(self, client):
        """Отправка одного и того же idempotency-ключа дважды возвращает один и тот же платёж."""
        first = await client.post(PAYMENTS_URL, json=_payload(), headers=_headers())
        second = await client.post(PAYMENTS_URL, json=_payload(), headers=_headers())

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()['payment_id'] == second.json()['payment_id']


class TestGetPayment:
    """Сценарии get-payment: получение созданного платежа, отсутствующего платежа и авторизация."""

    async def _create(self, client) -> str:
        """Создаёт платёж через API и возвращает его payment_id."""
        response = await client.post(PAYMENTS_URL, json=_payload(), headers=_headers())
        return response.json()['payment_id']

    async def test_get_payment_200(self, client):
        """Созданный платёж возвращается со своими сохранёнными полями и без попыток."""
        payment_id = await self._create(client)

        response = await client.get(
            f'{PAYMENTS_URL}/{payment_id}', headers={'X-API-Key': API_KEY}
        )

        assert response.status_code == 200
        body = response.json()
        assert body['payment_id'] == payment_id
        assert body['status'] == 'pending'
        assert Decimal(body['amount']) == Decimal('150.00')
        assert body['currency'] == 'RUB'
        assert body['idempotency_key'] == 'client-ref-1'
        assert body['attempts'] == []

    async def test_get_missing_404(self, client):
        """Неизвестный id платежа возвращает 404."""
        from src.shared.utils.uuid import uuid7

        response = await client.get(
            f'{PAYMENTS_URL}/{uuid7()}', headers={'X-API-Key': API_KEY}
        )
        assert response.status_code == 404

    async def test_get_requires_auth(self, client):
        """Запрос get без API-ключа отклоняется с кодом 401."""
        response = await client.get(
            f'{PAYMENTS_URL}/00000000-0000-0000-0000-000000000000'
        )
        assert response.status_code == 401
