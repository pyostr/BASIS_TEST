"""Модульные тесты домена payments: value-objects money и idempotency-key,
машина состояний агрегата Payment, платёжные попытки и доставки вебхуков."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.app.payments.domain.aggregates.payment import Payment, PaymentStatus
from src.app.payments.domain.entities.attempt import (
    PaymentAttempt,
    PaymentAttemptStatus,
)
from src.app.payments.domain.entities.webhook_delivery import (
    WebhookDelivery,
    WebhookDeliveryStatus,
)
from src.app.payments.domain.events.payment_events import (
    PaymentCreated,
    PaymentFailed,
    PaymentProcessingStarted,
    PaymentSucceeded,
)
from src.app.payments.domain.exceptions.payment_exceptions import InvalidStateTransition
from src.app.payments.domain.gateway import GatewayResult
from src.app.payments.domain.value_objects.idempotency_key import IdempotencyKey
from src.app.payments.domain.value_objects.money import Currency, Money
from src.app.payments.domain.value_objects.retry_policy import RetryPolicy
from src.shared.utils.uuid import uuid7

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)


def make_payment(status=PaymentStatus.PENDING, version=0):
    """Создаёт агрегат Payment в заданном состоянии, подходящий для тестов машины состояний."""
    return Payment(
        id=uuid7(),
        idempotency_key=IdempotencyKey('test-key-1'),
        money=Money('100.00', Currency.RUB),
        description='test',
        metadata={},
        webhook_url='https://example.com/hook',
        correlation_id='corr-1',
        status=status,
        created_at=NOW,
        processed_at=None if status == PaymentStatus.PENDING else NOW,
        version=version,
    )


class TestMoney:
    """Сценарии для value-object Money: разбор и валидация суммы и валюты."""

    def test_valid(self):
        """Корректная сумма и валюта разбираются и нормализуются до перечисления RUB."""
        money = Money('10.50', 'RUB')
        assert money.amount == Decimal('10.50')
        assert money.currency is Currency.RUB

    @pytest.mark.parametrize('amount', ['0', '-5', '10.001', 'abc', ''])
    def test_invalid_amount(self, amount):
        """Неположительные, некорректные или слишком точные суммы отклоняются."""
        with pytest.raises(ValueError):
            Money(amount, 'RUB')

    @pytest.mark.parametrize('currency', ['GBP', 'rub', ''])
    def test_invalid_currency(self, currency):
        """Неподдерживаемые или строчные коды валют отклоняются."""
        with pytest.raises(ValueError):
            Money('1', currency)


class TestIdempotencyKey:
    """Сценарии для value-object IdempotencyKey: валидация формата и равенство."""

    def test_valid(self):
        """Корректно сформированный idempotency-ключ принимается без изменений."""
        key = IdempotencyKey('client-ref-123')
        assert str(key) == 'client-ref-123'

    def test_empty_rejected(self):
        """Пустой ключ отклоняется."""
        with pytest.raises(ValueError):
            IdempotencyKey('')

    def test_too_long_rejected(self):
        """Слишком длинный ключ отклоняется."""
        with pytest.raises(ValueError):
            IdempotencyKey('x' * 256)

    def test_non_printable_rejected(self):
        """Ключ, содержащий пробелы, отклоняется."""
        with pytest.raises(ValueError):
            IdempotencyKey('has space')

    def test_equal(self):
        """Два ключа с одинаковым значением считаются равными."""
        assert IdempotencyKey('a') == IdempotencyKey('a')


class TestPaymentStateMachine:
    """Сценарии жизненного цикла агрегата Payment и порождаемых им событий."""

    def test_create_emits_created_event(self):
        """Создание платежа начинается в PENDING с версией 0 и порождает PaymentCreated."""
        payment = Payment.create(
            id=uuid7(),
            idempotency_key=IdempotencyKey('k'),
            money=Money('10', Currency.RUB),
            description=None,
            metadata={},
            webhook_url='https://example.com',
            correlation_id='c',
            created_at=NOW,
        )
        assert payment.status is PaymentStatus.PENDING
        assert payment.version == 0
        assert [type(e) for e in payment.events] == [PaymentCreated]

    def test_full_success_flow(self):
        """Путь processing -> succeeded увеличивает версию и порождает соответствующие события."""
        payment = make_payment()
        payment.mark_processing(NOW)
        assert payment.status is PaymentStatus.PROCESSING
        assert payment.version == 1

        payment.mark_succeeded(NOW)
        assert payment.status is PaymentStatus.SUCCEEDED
        assert payment.processed_at == NOW
        assert payment.version == 2

        types = [type(e) for e in payment.events]
        assert types == [PaymentProcessingStarted, PaymentSucceeded]

    def test_full_failure_flow(self):
        """Путь processing -> failed порождает события о начале обработки и о неудаче."""
        payment = make_payment()
        payment.mark_processing(NOW)
        payment.mark_failed(NOW, reason='declined')
        assert payment.status is PaymentStatus.FAILED
        types = [type(e) for e in payment.events]
        assert types == [PaymentProcessingStarted, PaymentFailed]

    def test_terminal_is_final(self):
        """Платёж в терминальном состоянии отклоняет любые дальнейшие переходы состояния."""
        payment = make_payment(status=PaymentStatus.SUCCEEDED, version=2)
        with pytest.raises(InvalidStateTransition):
            payment.mark_failed(NOW)
        with pytest.raises(InvalidStateTransition):
            payment.mark_processing(NOW)

    def test_direct_transition_to_terminal_rejected(self):
        """Платёж в статусе pending не может перейти сразу в терминальное состояние."""
        payment = make_payment()
        with pytest.raises(InvalidStateTransition):
            payment.mark_succeeded(NOW)

    def test_pull_events_clears(self):
        """Извлечение записанных событий очищает список ожидающих событий."""
        payment = Payment.create(
            id=uuid7(),
            idempotency_key=IdempotencyKey('k'),
            money=Money('10', Currency.RUB),
            description=None,
            metadata={},
            webhook_url='https://example.com',
            correlation_id='c',
            created_at=NOW,
        )
        assert payment.pull_events()
        assert payment.events == []


class TestPaymentAttempt:
    """Сценарии жизненного цикла сущности PaymentAttempt."""

    def test_flow(self):
        """Попытка проходит через created -> processing -> succeeded и сохраняет ответ шлюза."""
        attempt = PaymentAttempt.create(
            id=uuid7(),
            payment_id=uuid7(),
            attempt_number=1,
            correlation_id=None,
            created_at=NOW,
        )
        assert attempt.status is PaymentAttemptStatus.CREATED

        attempt.start(NOW)
        assert attempt.status is PaymentAttemptStatus.PROCESSING

        result = GatewayResult(success=True, gateway_id='g-1', raw={'ok': True})
        attempt.succeed(NOW, result)
        assert attempt.status is PaymentAttemptStatus.SUCCEEDED
        assert attempt.gateway_response == {'ok': True}

    def test_fail(self):
        """Попытка может быть помечена как неудачная с причиной ошибки шлюза."""
        attempt = PaymentAttempt.create(
            id=uuid7(),
            payment_id=uuid7(),
            attempt_number=1,
            correlation_id=None,
            created_at=NOW,
        )
        attempt.start(NOW)
        attempt.fail(NOW, 'declined')
        assert attempt.status is PaymentAttemptStatus.FAILED
        assert attempt.error == 'declined'

    def test_created_cannot_succeed(self):
        """Попытка, которая не была начата, не может быть успешно завершена."""
        attempt = PaymentAttempt.create(
            id=uuid7(),
            payment_id=uuid7(),
            attempt_number=1,
            correlation_id=None,
            created_at=NOW,
        )
        with pytest.raises(InvalidStateTransition):
            attempt.succeed(NOW, GatewayResult(success=True, gateway_id='g'))


class TestPaymentAggregateAttempts:
    """Сценарии управления платёжными попытками в корневом агрегате Payment."""

    def make_processing(self):
        """Создаёт агрегат, переведённый в статус PROCESSING."""
        payment = make_payment()
        payment.mark_processing(NOW)
        return payment

    @staticmethod
    def make_attempt(attempt_number, status=PaymentAttemptStatus.SUCCEEDED):
        """Создаёт попытку как восстановленную из БД (минуя агрегат)."""
        return PaymentAttempt(
            id=uuid7(),
            payment_id=uuid7(),
            attempt_number=attempt_number,
            status=status,
            error=None,
            gateway_response=None,
            correlation_id=None,
            created_at=NOW,
            updated_at=NOW,
        )

    def test_begin_attempt_requires_processing(self):
        """Попытка может быть начата только для платежа в статусе PROCESSING."""
        payment = make_payment()
        with pytest.raises(InvalidStateTransition):
            payment.begin_attempt(attempt_id=uuid7(), correlation_id=None, now=NOW)

    def test_begin_attempt_requires_processing_in_terminal(self):
        """Платёж в терминальном состоянии не может начинать новые попытки."""
        payment = make_payment(status=PaymentStatus.SUCCEEDED, version=2)
        with pytest.raises(InvalidStateTransition):
            payment.begin_attempt(attempt_id=uuid7(), correlation_id=None, now=NOW)

    def test_begin_attempt_numbers_sequentially(self):
        """begin_attempt нумерует попытки последовательно, начиная с 1."""
        payment = self.make_processing()
        first = payment.begin_attempt(attempt_id=uuid7(), correlation_id='c-1', now=NOW)
        second = payment.begin_attempt(
            attempt_id=uuid7(), correlation_id='c-2', now=NOW
        )
        assert first.attempt_number == 1
        assert second.attempt_number == 2
        assert [a.attempt_number for a in payment.attempts] == [1, 2]

    def test_begin_attempt_continues_hydrated_numbering(self):
        """Нумерация продолжается после восстановления уже сохранённых попыток."""
        payment = self.make_processing()
        payment.hydrate_attempts([self.make_attempt(1), self.make_attempt(2)])
        attempt = payment.begin_attempt(
            attempt_id=uuid7(), correlation_id=None, now=NOW
        )
        assert attempt.attempt_number == 3
        assert len(payment.attempts) == 3

    def test_begin_attempt_returns_processing_attempt(self):
        """Новая попытка сразу находится в статусе PROCESSING."""
        payment = self.make_processing()
        attempt = payment.begin_attempt(attempt_id=uuid7(), correlation_id='c', now=NOW)
        assert attempt.status is PaymentAttemptStatus.PROCESSING

    def test_succeed_attempt_requires_processing(self):
        """succeed_attempt доступен только для платежа в статусе PROCESSING."""
        payment = make_payment()
        with pytest.raises(InvalidStateTransition):
            payment.succeed_attempt(NOW, GatewayResult(success=True, gateway_id='g'))

    def test_succeed_attempt_requires_current_attempt(self):
        """succeed_attempt без начатой попытки отклоняется."""
        payment = self.make_processing()
        with pytest.raises(InvalidStateTransition):
            payment.succeed_attempt(NOW, GatewayResult(success=True, gateway_id='g'))

    def test_succeed_attempt_finishes_current(self):
        """succeed_attempt завершает текущую попытку и сохраняет ответ шлюза."""
        payment = self.make_processing()
        attempt = payment.begin_attempt(attempt_id=uuid7(), correlation_id='c', now=NOW)
        result = GatewayResult(success=True, gateway_id='g-1', raw={'ok': True})
        finished = payment.succeed_attempt(NOW, result)
        assert finished is attempt
        assert attempt.status is PaymentAttemptStatus.SUCCEEDED
        assert attempt.gateway_response == {'ok': True}

    def test_fail_attempt_requires_processing(self):
        """fail_attempt доступен только для платежа в статусе PROCESSING."""
        payment = make_payment()
        with pytest.raises(InvalidStateTransition):
            payment.fail_attempt(NOW, 'declined')

    def test_fail_attempt_requires_current_attempt(self):
        """fail_attempt без начатой попытки отклоняется."""
        payment = self.make_processing()
        with pytest.raises(InvalidStateTransition):
            payment.fail_attempt(NOW, 'declined')

    def test_fail_attempt_marks_current_failed(self):
        """fail_attempt помечает текущую попытку неудачной с указанием причины."""
        payment = self.make_processing()
        attempt = payment.begin_attempt(attempt_id=uuid7(), correlation_id='c', now=NOW)
        finished = payment.fail_attempt(NOW, 'declined')
        assert finished is attempt
        assert attempt.status is PaymentAttemptStatus.FAILED
        assert attempt.error == 'declined'

    def test_retry_after_failed_attempt(self):
        """После неудачной попытки платёж может начать новую попытку с большим номером."""
        payment = self.make_processing()
        payment.begin_attempt(attempt_id=uuid7(), correlation_id=None, now=NOW)
        payment.fail_attempt(NOW, 'timeout')
        retry = payment.begin_attempt(attempt_id=uuid7(), correlation_id=None, now=NOW)
        assert retry.attempt_number == 2
        assert len(payment.attempts) == 2

    def test_attempts_returns_snapshot(self):
        """Свойство attempts возвращает копию списка, не открывая внутреннее состояние."""
        payment = self.make_processing()
        payment.begin_attempt(attempt_id=uuid7(), correlation_id=None, now=NOW)
        snapshot = payment.attempts
        snapshot.clear()
        assert len(payment.attempts) == 1

    def test_full_success_with_attempt(self):
        """Полный путь processing -> attempt -> succeeded корректно комбинируется."""
        payment = make_payment()
        payment.mark_processing(NOW)
        payment.begin_attempt(attempt_id=uuid7(), correlation_id='c', now=NOW)
        payment.succeed_attempt(
            NOW,
            GatewayResult(success=True, gateway_id='g', raw={'ok': True}),
        )
        payment.mark_succeeded(NOW)
        assert payment.status is PaymentStatus.SUCCEEDED
        assert payment.attempts[0].status is PaymentAttemptStatus.SUCCEEDED


class TestWebhookDelivery:
    """Сценарии жизненного цикла сущности WebhookDelivery и планирования повторов."""

    def test_flow(self):
        """Доставка начинается в статусе pending с попытки 1 и может быть отмечена как успешная."""
        delivery = WebhookDelivery.create(
            id=uuid7(),
            payment_id=uuid7(),
            event_type='payment.succeeded',
            correlation_id=None,
            created_at=NOW,
        )
        assert delivery.status is WebhookDeliveryStatus.PENDING
        assert delivery.attempt == 1

        delivery.mark_success(NOW, 200, '{}')
        assert delivery.status is WebhookDeliveryStatus.SUCCESS

    def test_schedule_retry(self):
        """Планирование повтора увеличивает счётчик попыток и сохраняет время следующего повтора."""
        delivery = WebhookDelivery.create(
            id=uuid7(),
            payment_id=uuid7(),
            event_type='payment.succeeded',
            correlation_id=None,
            created_at=NOW,
        )
        delivery.schedule_retry(NOW, NOW, 500, 'err')
        assert delivery.attempt == 2
        assert delivery.status is WebhookDeliveryStatus.PENDING
        assert delivery.next_retry_at == NOW

    def test_mark_failed(self):
        """Доставка может быть помечена как неудачная после исчерпания попыток."""
        delivery = WebhookDelivery.create(
            id=uuid7(),
            payment_id=uuid7(),
            event_type='payment.succeeded',
            correlation_id=None,
            created_at=NOW,
        )
        delivery.mark_failed(NOW, 500, 'err')
        assert delivery.status is WebhookDeliveryStatus.FAILED

    def test_record_failure_schedules_retry_with_backoff(self):
        """Неудача до исчерпания попыток планирует повтор с линейным backoff и остаётся в pending."""
        delivery = WebhookDelivery.create(
            id=uuid7(),
            payment_id=uuid7(),
            event_type='payment.succeeded',
            correlation_id=None,
            created_at=NOW,
        )
        policy = RetryPolicy(max_attempts=3, base_delay=2.0)

        delivery.record_failure(NOW, 500, 'err', policy)

        assert delivery.status is WebhookDeliveryStatus.PENDING
        assert delivery.attempt == 2
        assert delivery.next_retry_at == NOW + timedelta(seconds=2)

    def test_record_failure_exhausted_marks_failed(self):
        """Неудача на последней попытке помечает доставку терминально неудачной."""
        delivery = WebhookDelivery.create(
            id=uuid7(),
            payment_id=uuid7(),
            event_type='payment.succeeded',
            correlation_id=None,
            created_at=NOW,
        )
        policy = RetryPolicy(max_attempts=1, base_delay=1.0)

        delivery.record_failure(NOW, 500, 'err', policy)

        assert delivery.status is WebhookDeliveryStatus.FAILED
        assert delivery.next_retry_at is None

    def test_terminal_rejects_further_transitions(self):
        """Терминальная доставка отклоняет любые дальнейшие переходы состояния."""
        delivery = WebhookDelivery.create(
            id=uuid7(),
            payment_id=uuid7(),
            event_type='payment.succeeded',
            correlation_id=None,
            created_at=NOW,
        )
        delivery.mark_failed(NOW, 500, 'err')
        with pytest.raises(InvalidStateTransition):
            delivery.mark_success(NOW, 200, '{}')
        with pytest.raises(InvalidStateTransition):
            delivery.record_failure(
                NOW, 500, 'err', RetryPolicy(max_attempts=3, base_delay=1.0)
            )


class TestRetryPolicy:
    """Сценарии для value-object RetryPolicy: валидация и правила повторов с backoff."""

    def test_valid(self):
        """Корректная политика принимается и хранит максимальное число попыток и базовую задержку."""
        policy = RetryPolicy(max_attempts=3, base_delay=2.5)
        assert policy.max_attempts == 3
        assert policy.base_delay == 2.5

    def test_zero_attempts_rejected(self):
        """Политика без возможности хотя бы одной попытки отклоняется."""
        with pytest.raises(ValueError):
            RetryPolicy(max_attempts=0, base_delay=1.0)

    def test_negative_delay_rejected(self):
        """Отрицательная базовая задержка отклоняется."""
        with pytest.raises(ValueError):
            RetryPolicy(max_attempts=3, base_delay=-1.0)

    def test_zero_delay_allowed(self):
        """Нулевая базовая задержка допустима."""
        policy = RetryPolicy(max_attempts=3, base_delay=0.0)
        assert policy.base_delay == 0.0

    def test_should_retry_before_exhaustion(self):
        """Попытки ниже максимума допускают повтор."""
        policy = RetryPolicy(max_attempts=3, base_delay=1.0)
        assert policy.should_retry(1) is True
        assert policy.should_retry(2) is True
        assert policy.should_retry(3) is False

    def test_next_retry_at_grows_linearly(self):
        """Время следующей попытки растёт линейно с номером неудачной попытки."""
        policy = RetryPolicy(max_attempts=3, base_delay=2.0)
        assert policy.next_retry_at(1, NOW) == NOW + timedelta(seconds=2)
        assert policy.next_retry_at(2, NOW) == NOW + timedelta(seconds=4)
