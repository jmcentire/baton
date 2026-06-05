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
    DispatchBinding,
    DispatchBindingConflict,
    DispatchClaim,
    DispatchInProgress,
    DispatchRequest,
    DispatchSignal,
    DispatchSignalKind,
    DispatchStateUnavailable,
    MonitoringUnavailable,
    ProviderAttemptOutcome,
    VerifiedDispatchGrant,
    dispatch_request_fingerprint,
)


def _fingerprint(
    idempotency_key: str = "dispatch-once-1",
    *,
    dispatch_id: str | None = None,
) -> str:
    return dispatch_request_fingerprint(
        dispatch_id=dispatch_id or f"dispatch-{idempotency_key}",
        workflow_id="workflow-1",
        channel=Channel.SMS,
        recipient_ref="recipient-ref-1",
        payload_ref="payload-ref-1",
        idempotency_key=idempotency_key,
    )


FINGERPRINT = _fingerprint()


def _request(
    idempotency_key: str = "dispatch-once-1",
    *,
    dispatch_id: str | None = None,
    request_fingerprint: str | None = None,
) -> DispatchRequest:
    resolved_dispatch_id = dispatch_id or f"dispatch-{idempotency_key}"
    return DispatchRequest(
        dispatch_id=resolved_dispatch_id,
        workflow_id="workflow-1",
        channel=Channel.SMS,
        recipient_ref="recipient-ref-1",
        payload_ref="payload-ref-1",
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint
        or _fingerprint(idempotency_key, dispatch_id=resolved_dispatch_id),
    )


def test_dispatch_request_rejects_noncanonical_fingerprint():
    with pytest.raises(ValueError, match="does not bind"):
        DispatchRequest(
            dispatch_id="dispatch-once-1",
            workflow_id="workflow-1",
            channel=Channel.SMS,
            recipient_ref="recipient-ref-1",
            payload_ref="payload-ref-1",
            idempotency_key="dispatch-once-1",
            request_fingerprint="f" * 64,
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
            request_fingerprint=request.request_fingerprint,
        )


class DeniedVerifier:
    async def verify(
        self, _capability: CapabilityReference, _request: DispatchRequest
    ) -> VerifiedDispatchGrant:
        raise AuthorizationDenied("denied")


class MismatchedFingerprintVerifier(AcceptedVerifier):
    async def verify(
        self, capability: CapabilityReference, request: DispatchRequest
    ) -> VerifiedDispatchGrant:
        grant = await super().verify(capability, request)
        return dataclasses.replace(grant, request_fingerprint="e" * 64)


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


class OutcomeInvokerFactory:
    def __init__(self, invoker):
        self.invoker = invoker
        self.prepare_calls: list[str] = []

    async def prepare(
        self,
        _capability: CapabilityReference,
        _request: DispatchRequest,
        _grant: VerifiedDispatchGrant,
        _claim: DispatchClaim,
        initial_route: ConnectorRoute,
        _authorized_routes: tuple[ConnectorRoute, ...],
    ):
        self.prepare_calls.append(initial_route.connector_id)
        return self.invoker


class JournalCheckingFactory(OutcomeInvokerFactory):
    def __init__(self, invoker, journal):
        super().__init__(invoker)
        self.journal = journal

    async def prepare(
        self,
        capability: CapabilityReference,
        request: DispatchRequest,
        grant: VerifiedDispatchGrant,
        claim: DispatchClaim,
        initial_route: ConnectorRoute,
        authorized_routes: tuple[ConnectorRoute, ...],
    ):
        assert request.idempotency_key in self.journal.running
        return await super().prepare(
            capability, request, grant, claim, initial_route, authorized_routes
        )


class MemoryJournal:
    def __init__(self):
        self.running: set[str] = set()
        self.results: dict[str, DeliveryOutcome] = {}
        self.fingerprints: dict[str, str] = {}
        self.claims: dict[str, str] = {}

    def _assert_binding(self, binding: DispatchBinding) -> None:
        fingerprint = self.fingerprints.get(binding.idempotency_key)
        if fingerprint is not None and fingerprint != binding.request_fingerprint:
            raise DispatchBindingConflict("idempotency key is bound to another request")

    async def completed(self, binding: DispatchBinding) -> DeliveryOutcome | None:
        self._assert_binding(binding)
        return self.results.get(binding.idempotency_key)

    async def begin(self, binding: DispatchBinding) -> DispatchClaim | None:
        self._assert_binding(binding)
        if binding.idempotency_key in self.running:
            return None
        self.fingerprints[binding.idempotency_key] = binding.request_fingerprint
        self.running.add(binding.idempotency_key)
        claim_id = f"claim-{binding.idempotency_key}"
        self.claims[binding.idempotency_key] = claim_id
        return DispatchClaim(
            claim_id=claim_id,
            binding=binding,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )

    async def complete(self, claim: DispatchClaim, outcome: DeliveryOutcome) -> None:
        self._assert_binding(claim.binding)
        assert self.claims[claim.binding.idempotency_key] == claim.claim_id
        self.running.discard(claim.binding.idempotency_key)
        self.results[claim.binding.idempotency_key] = outcome

    async def renew(self, claim: DispatchClaim) -> None:
        self._assert_binding(claim.binding)
        assert self.claims[claim.binding.idempotency_key] == claim.claim_id

    async def abort(self, claim: DispatchClaim) -> None:
        self._assert_binding(claim.binding)
        if self.claims.get(claim.binding.idempotency_key) == claim.claim_id:
            self.running.discard(claim.binding.idempotency_key)


class CompleteFailingJournal(MemoryJournal):
    async def complete(self, _claim: DispatchClaim, _outcome: DeliveryOutcome) -> None:
        raise RuntimeError("injected durable completion failure")


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


def _executor(invoker, journal=None, sink=None, routes=None, factory=None) -> DelegatedConnectorExecutor:
    return DelegatedConnectorExecutor(
        routes or [_route("primary", 1), _route("backup", 2)],
        AcceptedVerifier(),
        factory or OutcomeInvokerFactory(invoker),
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
        "connector_id",
        "provider_key",
        "status",
        "attempt_count",
        "failover_used",
        "audit_ref",
        "failure_code",
    }
    assert [signal.kind for signal in sink.signals] == [DispatchSignalKind.ATTEMPT_SUCCEEDED]
    assert sink.signals[0].dispatch_id == "dispatch-dispatch-once-1"
    assert sink.signals[0].connector_id == "primary"


async def test_authorization_denial_prevents_invocation_and_emits_signal():
    invoker = OutcomeInvoker([_success()])
    factory = OutcomeInvokerFactory(invoker)
    sink = SignalSink()
    executor = DelegatedConnectorExecutor(
        [_route("primary", 1)],
        DeniedVerifier(),
        factory,
        MemoryJournal(),
        sink,
    )

    with pytest.raises(AuthorizationDenied):
        await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())

    assert invoker.calls == []
    assert factory.prepare_calls == []
    assert sink.signals[0].kind is DispatchSignalKind.AUTHORIZATION_DENIED
    assert sink.signals[0].dispatch_id == "dispatch-dispatch-once-1"


async def test_authorization_fingerprint_mismatch_prevents_invocation():
    invoker = OutcomeInvoker([_success()])
    factory = OutcomeInvokerFactory(invoker)
    sink = SignalSink()
    executor = DelegatedConnectorExecutor(
        [_route("primary", 1)],
        MismatchedFingerprintVerifier(),
        factory,
        MemoryJournal(),
        sink,
    )

    with pytest.raises(AuthorizationDenied):
        await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())

    assert invoker.calls == []
    assert factory.prepare_calls == []
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
    assert {signal.dispatch_id for signal in sink.signals} == {"dispatch-dispatch-once-1"}


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
    factory = OutcomeInvokerFactory(invoker)
    journal = MemoryJournal()
    executor = _executor(invoker, journal=journal, factory=factory)
    first = await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())
    second = await executor.dispatch(CapabilityReference("authorization-ref-2"), _request())

    assert first == second
    assert invoker.calls == ["primary"]
    assert factory.prepare_calls == ["primary"]


async def test_custody_preparation_occurs_only_after_idempotency_begin():
    invoker = OutcomeInvoker([_success()])
    journal = MemoryJournal()
    factory = JournalCheckingFactory(invoker, journal)
    outcome = await _executor(invoker, journal=journal, factory=factory).dispatch(
        CapabilityReference("authorization-ref-1"), _request()
    )

    assert outcome.status is DeliveryStatus.ACCEPTED
    assert factory.prepare_calls == ["primary"]


async def test_open_circuit_without_attempt_does_not_prepare_custody_invoker():
    invoker = OutcomeInvoker([_failure(counts_toward_circuit=True)])
    factory = OutcomeInvokerFactory(invoker)
    executor = _executor(
        invoker,
        routes=[_route("primary", 1, threshold=1)],
        factory=factory,
    )
    await executor.dispatch(CapabilityReference("authorization-ref-1"), _request("one"))
    outcome = await executor.dispatch(CapabilityReference("authorization-ref-2"), _request("two"))

    assert outcome.status is DeliveryStatus.EXHAUSTED
    assert outcome.failure_code == "circuit_open"
    assert outcome.connector_id == "primary"
    assert factory.prepare_calls == ["primary"]


async def test_changed_request_fingerprint_cannot_reuse_completed_idempotency_key():
    invoker = OutcomeInvoker([_success()])
    journal = MemoryJournal()
    sink = SignalSink()
    executor = _executor(invoker, journal=journal, sink=sink)
    await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())

    with pytest.raises(DispatchBindingConflict):
        await executor.dispatch(
            CapabilityReference("authorization-ref-2"),
            _request(dispatch_id="dispatch-changed"),
        )

    assert invoker.calls == ["primary"]
    assert sink.signals[-1].kind is DispatchSignalKind.IDEMPOTENCY_CONFLICT
    assert sink.signals[-1].dispatch_id == "dispatch-changed"


async def test_in_progress_idempotency_key_fails_closed():
    journal = MemoryJournal()
    journal.running.add("dispatch-once-1")
    journal.fingerprints["dispatch-once-1"] = FINGERPRINT
    executor = _executor(OutcomeInvoker([_success()]), journal=journal)

    with pytest.raises(DispatchInProgress):
        await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())


async def test_signal_failure_prevents_unaudited_authorization_denial():
    executor = DelegatedConnectorExecutor(
        [_route("primary", 1)],
        DeniedVerifier(),
        OutcomeInvokerFactory(OutcomeInvoker([_success()])),
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


async def test_post_attempt_failure_does_not_abort_claim_or_immediately_resend():
    invoker = OutcomeInvoker([_failure("provider_unavailable")])
    journal = MemoryJournal()
    sink = SignalSink(failures_remaining=1)
    executor = _executor(invoker, journal=journal, sink=sink)

    with pytest.raises(MonitoringUnavailable):
        await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())

    assert "dispatch-once-1" in journal.running
    with pytest.raises(DispatchInProgress):
        await executor.dispatch(CapabilityReference("authorization-ref-2"), _request())
    assert invoker.calls == ["primary"]


async def test_post_provider_journal_failure_keeps_claim_and_does_not_resend():
    invoker = OutcomeInvoker([_success()])
    journal = CompleteFailingJournal()
    executor = _executor(invoker, journal=journal)

    with pytest.raises(DispatchStateUnavailable):
        await executor.dispatch(CapabilityReference("authorization-ref-1"), _request())

    assert "dispatch-once-1" in journal.running
    with pytest.raises(DispatchInProgress):
        await executor.dispatch(CapabilityReference("authorization-ref-2"), _request())
    assert invoker.calls == ["primary"]
