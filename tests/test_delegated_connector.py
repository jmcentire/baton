"""Tests for provider dispatch orchestration without credential material."""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from baton.delegated_connector import (
    AuthorizationDenied,
    CapabilityReference,
    Channel,
    ConnectorRoute,
    DelegatedConnectorExecutor,
    DeliveryOutcome,
    DeliveryStatus,
    DispatchInProgress,
    DispatchRequest,
    DispatchSignal,
    DispatchSignalKind,
    MonitoringUnavailable,
    ProviderAttemptOutcome,
    VerifiedDispatchGrant,
)


def _request(idempotency_key: str = "dispatch-once-1") -> DispatchRequest:
    return DispatchRequest(
        workflow_id="workflow-1",
        channel=Channel.SMS,
        recipient_ref="recipient-ref-1",
        payload_ref="payload-ref-1",
        idempotency_key=idempotency_key,
    )


def _route(
    connector_id: str,
    priority: int,
    *,
    max_attempts: int = 1,
    threshold: int = 3,
    timeout_ms: int = 5000,
) -> ConnectorRoute:
    return ConnectorRoute(
        connector_id=connector_id,
        provider_key=f"provider-{connector_id}",
        channel=Channel.SMS,
        credential_handle=f"opaque-handle-{connector_id}",
        priority=priority,
        max_attempts=max_attempts,
        circuit_breaker_threshold=threshold,
        timeout_ms=timeout_ms,
    )


class AcceptedVerifier:
    async def verify(
        self, _capability: CapabilityReference, request: DispatchRequest
    ) -> VerifiedDispatchGrant:
        return VerifiedDispatchGrant(
            principal="comms-runtime",
            channel=request.channel,
            allowed_connectors=frozenset({"primary", "backup"}),
            not_after=datetime.now(timezone.utc) + timedelta(minutes=5),
            max_attempts=4,
        )


class DeniedVerifier:
    async def verify(
        self, _capability: CapabilityReference, _request: DispatchRequest
    ) -> VerifiedDispatchGrant:
        raise AuthorizationDenied("denied")


class OutcomeInvoker:
    def __init__(self, outcomes: list[ProviderAttemptOutcome]):
        self._outcomes = list(outcomes)
        self.calls: list[str] = []

    async def invoke(
        self, route: ConnectorRoute, _request: DispatchRequest
    ) -> ProviderAttemptOutcome:
        self.calls.append(route.connector_id)
        return self._outcomes.pop(0)


class HangingInvoker:
    async def invoke(
        self, _route: ConnectorRoute, _request: DispatchRequest
    ) -> ProviderAttemptOutcome:
        await asyncio.sleep(60)
        raise AssertionError("unreachable")


class MemoryJournal:
    def __init__(self):
        self.running: set[str] = set()
        self.results: dict[str, DeliveryOutcome] = {}

    async def completed(self, idempotency_key: str) -> DeliveryOutcome | None:
        return self.results.get(idempotency_key)

    async def begin(self, idempotency_key: str) -> bool:
        if idempotency_key in self.running:
            return False
        self.running.add(idempotency_key)
        return True

    async def complete(self, idempotency_key: str, outcome: DeliveryOutcome) -> None:
        self.running.discard(idempotency_key)
        self.results[idempotency_key] = outcome

    async def abort(self, idempotency_key: str) -> None:
        self.running.discard(idempotency_key)


class SignalSink:
    def __init__(self, failures_remaining: int = 0):
        self.failures_remaining = failures_remaining
        self.signals: list[DispatchSignal] = []

    async def emit(self, signal: DispatchSignal) -> None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("signal unavailable")
        self.signals.append(signal)


def _success(audit_ref: str = "audit-success") -> ProviderAttemptOutcome:
    return ProviderAttemptOutcome(
        status=DeliveryStatus.ACCEPTED,
        audit_ref=audit_ref,
    )


def _failure(
    code: str = "provider_unavailable",
    *,
    retryable: bool = False,
    failover_allowed: bool = False,
    counts_toward_circuit: bool = False,
) -> ProviderAttemptOutcome:
    return ProviderAttemptOutcome(
        status=DeliveryStatus.FAILED,
        audit_ref=f"audit-{code}",
        failure_code=code,
        retryable=retryable,
        failover_allowed=failover_allowed,
        counts_toward_circuit=counts_toward_circuit,
    )


def _executor(invoker, journal=None, sink=None, routes=None) -> DelegatedConnectorExecutor:
    return DelegatedConnectorExecutor(
        routes or [_route("primary", 1), _route("backup", 2)],
        AcceptedVerifier(),
        invoker,
        journal or MemoryJournal(),
        sink or SignalSink(),
        sleep=lambda _delay: asyncio.sleep(0),
    )


async def test_success_returns_sanitized_outcome_only():
    invoker = OutcomeInvoker([_success()])
    sink = SignalSink()
    outcome = await _executor(invoker, sink=sink).dispatch(
        CapabilityReference("authorization-ref-1"), _request()
    )

    assert outcome.status is DeliveryStatus.ACCEPTED
    assert outcome.provider_key == "provider-primary"
    assert outcome.attempt_count == 1
    fields = {field.name for field in dataclasses.fields(outcome)}
    assert fields == {
        "dispatch_id",
        "workflow_id",
        "channel",
        "provider_key",
        "status",
        "attempt_count",
        "failover_used",
        "audit_ref",
        "failure_code",
    }
    assert [signal.kind for signal in sink.signals] == [DispatchSignalKind.ATTEMPT_SUCCEEDED]


async def test_authorization_denial_prevents_invocation_and_emits_signal():
    invoker = OutcomeInvoker([_success()])
    sink = SignalSink()
    executor = DelegatedConnectorExecutor(
        [_route("primary", 1)],
        DeniedVerifier(),
        invoker,
        MemoryJournal(),
        sink,
    )

    with pytest.raises(AuthorizationDenied):
        await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())

    assert invoker.calls == []
    assert sink.signals[0].kind is DispatchSignalKind.AUTHORIZATION_DENIED


async def test_failed_primary_fails_over_to_backup_with_sanitized_signals():
    invoker = OutcomeInvoker([_failure(failover_allowed=True), _success("audit-backup")])
    sink = SignalSink()
    outcome = await _executor(invoker, sink=sink).dispatch(
        CapabilityReference("authorization-ref-1"), _request()
    )

    assert invoker.calls == ["primary", "backup"]
    assert outcome.provider_key == "provider-backup"
    assert outcome.failover_used is True
    assert outcome.attempt_count == 2
    assert [signal.kind for signal in sink.signals] == [
        DispatchSignalKind.ATTEMPT_FAILED,
        DispatchSignalKind.FAILOVER_USED,
        DispatchSignalKind.ATTEMPT_SUCCEEDED,
    ]


async def test_provider_failure_without_failover_approval_does_not_send_to_backup():
    invoker = OutcomeInvoker([_failure("invalid_payload")])
    outcome = await _executor(invoker).dispatch(CapabilityReference("authorization-ref-1"), _request())

    assert outcome.status is DeliveryStatus.EXHAUSTED
    assert invoker.calls == ["primary"]
    assert outcome.failover_used is False


async def test_open_circuit_skips_failing_primary_on_next_dispatch():
    invoker = OutcomeInvoker(
        [_failure(failover_allowed=True, counts_toward_circuit=True), _success(), _success()]
    )
    executor = _executor(
        invoker,
        routes=[_route("primary", 1, threshold=1), _route("backup", 2)],
    )
    first = await executor.dispatch(CapabilityReference("authorization-ref-1"), _request("one"))
    second = await executor.dispatch(CapabilityReference("authorization-ref-2"), _request("two"))

    assert first.provider_key == "provider-backup"
    assert second.provider_key == "provider-backup"
    assert invoker.calls == ["primary", "backup", "backup"]


async def test_delivery_rejection_does_not_open_provider_circuit():
    invoker = OutcomeInvoker([_failure("invalid_payload"), _success()])
    executor = _executor(
        invoker,
        routes=[_route("primary", 1, threshold=1), _route("backup", 2)],
    )
    first = await executor.dispatch(CapabilityReference("authorization-ref-1"), _request("one"))
    second = await executor.dispatch(CapabilityReference("authorization-ref-2"), _request("two"))

    assert first.status is DeliveryStatus.EXHAUSTED
    assert second.provider_key == "provider-primary"
    assert invoker.calls == ["primary", "primary"]


async def test_timeout_is_sanitized_and_fails_over():
    invoker = HangingInvoker()
    executor = _executor(
        invoker,
        routes=[_route("primary", 1, timeout_ms=1)],
    )
    outcome = await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())

    assert outcome.status is DeliveryStatus.EXHAUSTED
    assert outcome.failure_code == "provider_timeout"


async def test_completed_idempotency_key_returns_without_second_invocation():
    invoker = OutcomeInvoker([_success()])
    journal = MemoryJournal()
    executor = _executor(invoker, journal=journal)
    first = await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())
    second = await executor.dispatch(CapabilityReference("authorization-ref-2"), _request())

    assert first == second
    assert invoker.calls == ["primary"]


async def test_in_progress_idempotency_key_fails_closed():
    journal = MemoryJournal()
    journal.running.add("dispatch-once-1")
    executor = _executor(OutcomeInvoker([_success()]), journal=journal)

    with pytest.raises(DispatchInProgress):
        await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())


async def test_signal_failure_prevents_unaudited_authorization_denial():
    executor = DelegatedConnectorExecutor(
        [_route("primary", 1)],
        DeniedVerifier(),
        OutcomeInvoker([_success()]),
        MemoryJournal(),
        SignalSink(failures_remaining=1),
    )

    with pytest.raises(MonitoringUnavailable):
        await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())


async def test_success_is_not_resent_when_terminal_signal_must_be_retried():
    invoker = OutcomeInvoker([_success()])
    journal = MemoryJournal()
    sink = SignalSink(failures_remaining=1)
    executor = _executor(invoker, journal=journal, sink=sink)

    with pytest.raises(MonitoringUnavailable):
        await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())
    outcome = await executor.dispatch(CapabilityReference("authorization-ref-2"), _request())

    assert outcome.status is DeliveryStatus.ACCEPTED
    assert invoker.calls == ["primary"]
    assert [signal.kind for signal in sink.signals] == [DispatchSignalKind.ATTEMPT_SUCCEEDED]
