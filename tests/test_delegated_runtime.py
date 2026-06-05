"""Durable delegated connector runtime tests without credential material."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest

from baton.credential_custody import (
    AuthorizedCredentialUse,
    ConsumptionReservationRequired,
    CredentialUseRequest,
    CustodyAuditEvent,
    CustodyAuditKind,
    CustodyAuthorizationDenied,
    CustodyResultStatus,
    ProviderChannel,
    ProviderCredentialHandle,
    SanitizedCustodyOutcome,
    VerifiedDelegatedAuthorization,
    VerifiedWorkloadAuthorization,
)
from baton.delegated_connector import (
    AuthorizationDenied,
    CapabilityReference,
    Channel,
    ConnectorRoute,
    DeliveryOutcome,
    DeliveryStatus,
    DispatchBinding,
    DispatchRequest,
    DispatchSignal,
    DispatchSignalKind,
    DispatchStateUnavailable,
    VerifiedDispatchGrant,
    dispatch_request_fingerprint,
)
from baton.delegated_runtime import (
    DelegatedAuthorizationVerifier,
    ConfiguredVerifierBundle,
    DelegatedAuthorizationContext,
    DelegatedConnectorRuntime,
    DelegatedRuntimeComponents,
    SinglePurposeCustodiedResolver,
    SqliteDelegatedRuntimeState,
)


NOW = datetime(2026, 6, 4, tzinfo=timezone.utc)


def _fingerprint(
    idempotency_key: str = "dispatch-once-1",
    *,
    dispatch_id: str | None = None,
) -> str:
    return dispatch_request_fingerprint(
        dispatch_id=dispatch_id or f"dispatch-{idempotency_key}",
        workflow_id="operation-1",
        channel=Channel.SMS,
        recipient_ref="recipient-ref-1",
        payload_ref="payload-ref-1",
        idempotency_key=idempotency_key,
    )


FINGERPRINT = _fingerprint()


@dataclass
class MutableClock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


def _route() -> ConnectorRoute:
    return ConnectorRoute(
        connector_id="sms-primary",
        provider_key="provider-primary",
        channel=Channel.SMS,
        credential_handle="handle-sms-primary-v3",
        priority=1,
    )


def _handle() -> ProviderCredentialHandle:
    return ProviderCredentialHandle(
        handle_id="handle-sms-primary-v3",
        connector_id="sms-primary",
        provider_key="provider-primary",
        channel=ProviderChannel.SMS,
        version_ref="active-v3",
    )


def _request(
    *,
    idempotency_key: str = "dispatch-once-1",
) -> DispatchRequest:
    dispatch_id = f"dispatch-{idempotency_key}"
    return DispatchRequest(
        dispatch_id=dispatch_id,
        workflow_id="operation-1",
        channel=Channel.SMS,
        recipient_ref="recipient-ref-1",
        payload_ref="payload-ref-1",
        idempotency_key=idempotency_key,
        request_fingerprint=_fingerprint(idempotency_key, dispatch_id=dispatch_id),
    )


def _custody_request(
    *,
    idempotency_key: str = "dispatch-once-1",
    fingerprint: str | None = None,
    claim_id: str = "claim-1",
) -> CredentialUseRequest:
    dispatch_id = f"dispatch-{idempotency_key}"
    return CredentialUseRequest(
        operation_id="operation-1",
        dispatch_id=dispatch_id,
        workload_id="mea-comms",
        connector_id="sms-primary",
        channel=ProviderChannel.SMS,
        purpose="case_notification",
        recipient_ref="recipient-ref-1",
        payload_ref="payload-ref-1",
        idempotency_key=idempotency_key,
        dispatch_claim_id=claim_id,
        request_fingerprint=fingerprint
        or _fingerprint(idempotency_key, dispatch_id=dispatch_id),
    )


def _delivery(dispatch_id: str = "dispatch-dispatch-once-1") -> DeliveryOutcome:
    return DeliveryOutcome(
        dispatch_id=dispatch_id,
        workflow_id="operation-1",
        channel=Channel.SMS,
        connector_id="sms-primary",
        provider_key="provider-primary",
        status=DeliveryStatus.ACCEPTED,
        attempt_count=1,
        failover_used=False,
        audit_ref="audit-provider-accepted",
    )


def _authorized_use(
    *,
    claim_id: str,
    idempotency_key: str = "dispatch-once-1",
    fingerprint: str = FINGERPRINT,
    reservation_id: str | None = None,
) -> AuthorizedCredentialUse:
    return AuthorizedCredentialUse(
        authorization_id=f"authorization-{idempotency_key}",
        handle_id="handle-sms-primary-v3",
        connector_id="sms-primary",
        provider_key="provider-primary",
        operation_id="operation-1",
        dispatch_id=f"dispatch-{idempotency_key}",
        recipient_ref="recipient-ref-1",
        payload_ref="payload-ref-1",
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        dispatch_claim_id=claim_id,
        reservation_id=reservation_id or f"reservation-{idempotency_key}",
    )


class DispatchVerifier:
    def __init__(self):
        self.contexts: list[DelegatedAuthorizationContext] = []

    async def verify(
        self,
        _reference,
        request: DispatchRequest,
        context: DelegatedAuthorizationContext,
    ) -> VerifiedDelegatedAuthorization:
        self.contexts.append(context)
        return VerifiedDelegatedAuthorization(
            principal="mea-comms",
            channel=request.channel,
            allowed_connectors=frozenset({"sms-primary"}),
            not_after=NOW + timedelta(minutes=10),
            max_attempts=1,
            request_fingerprint=request.request_fingerprint,
            authorization_id=f"authorization-{request.idempotency_key}",
            issuer="signet://issuer/mea",
            audience=context.audience,
            allowed_purposes=frozenset({"case_notification"}),
            not_before=NOW - timedelta(minutes=1),
            max_uses=1,
        )


class CustodyVerifier:
    async def verify(
        self,
        _reference,
        request: CredentialUseRequest,
    ) -> VerifiedWorkloadAuthorization:
        return VerifiedWorkloadAuthorization(
            authorization_id=f"authorization-{request.idempotency_key}",
            workload_id=request.workload_id,
            allowed_connector_ids=frozenset({"sms-primary"}),
            allowed_channels=frozenset({ProviderChannel.SMS}),
            allowed_purposes=frozenset({"case_notification"}),
            request_fingerprint=request.request_fingerprint,
            not_before=NOW - timedelta(minutes=1),
            not_after=NOW + timedelta(minutes=10),
            max_uses=1,
            max_provider_attempts=1,
        )


class RebindingDispatchVerifier(DispatchVerifier):
    def __init__(self, **replacements):
        super().__init__()
        self.replacements = replacements

    async def verify(
        self,
        reference,
        request: DispatchRequest,
        context: DelegatedAuthorizationContext,
    ) -> VerifiedDelegatedAuthorization:
        outcome = await super().verify(reference, request, context)
        return replace(outcome, **self.replacements)


class IndependentDispatchVerifier:
    async def verify(
        self,
        _reference,
        request: DispatchRequest,
        _context: DelegatedAuthorizationContext,
    ) -> VerifiedDispatchGrant:
        return VerifiedDispatchGrant(
            principal="mea-comms",
            channel=request.channel,
            allowed_connectors=frozenset({"sms-primary"}),
            not_after=NOW + timedelta(minutes=10),
            max_attempts=1,
            request_fingerprint=request.request_fingerprint,
        )


class StaticOperation:
    def __init__(self, outcome: SanitizedCustodyOutcome):
        self.outcome = outcome
        self.calls = 0

    async def invoke(self) -> SanitizedCustodyOutcome:
        self.calls += 1
        return self.outcome


class OperationFactory:
    def __init__(self, outcome: SanitizedCustodyOutcome):
        self.outcome = outcome
        self.prepared = []
        self.operations: list[StaticOperation] = []

    async def prepare(self, handle, authorized_use) -> StaticOperation:
        self.prepared.append((handle, authorized_use))
        operation = StaticOperation(self.outcome)
        self.operations.append(operation)
        return operation


class CompleteFailingLedger:
    def __init__(self, ledger):
        self._ledger = ledger

    async def reserve_once(self, authorization, request):
        return await self._ledger.reserve_once(authorization, request)

    async def reserve_attempt(self, reservation, authorized_use):
        return await self._ledger.reserve_attempt(reservation, authorized_use)

    async def complete(self, _reservation, _outcome):
        raise RuntimeError("injected durable outcome persistence failure")


class OutcomeFailingAuditSink:
    def __init__(self, sink):
        self._sink = sink

    async def emit(self, event):
        if event.kind in (
            CustodyAuditKind.INVOCATION_COMPLETED,
            CustodyAuditKind.INVOCATION_FAILED,
        ):
            raise RuntimeError("injected durable custody audit failure")
        await self._sink.emit(event)


def _accepted_outcome() -> SanitizedCustodyOutcome:
    return SanitizedCustodyOutcome(
        operation_id="operation-1",
        dispatch_id="dispatch-dispatch-once-1",
        provider_key="provider-primary",
        status=CustodyResultStatus.ACCEPTED,
        audit_ref="audit-provider-accepted",
    )


def _runtime(
    tmp_path,
    operation_factory,
    *,
    clock=None,
    verifier: DelegatedAuthorizationVerifier | None = None,
) -> DelegatedConnectorRuntime:
    return DelegatedConnectorRuntime.build_sqlite_reference(
        routes=[_route()],
        handles={"sms-primary": _handle()},
        verifiers=ConfiguredVerifierBundle(
            verifier=verifier or DispatchVerifier(),
            audience="baton://delegated-provider-executor",
            issuer_policy_ref="signet://issuer-policy/mea-comms",
            rotation_policy_ref="signet://rotation-policy/mea-comms",
        ),
        operation_factory=operation_factory,
        state_path=tmp_path / "delegated-runtime.sqlite3",
        workload_id="mea-comms",
        purpose="case_notification",
        clock=clock,
    )


async def test_runtime_verifies_once_and_binds_exact_policy_context(tmp_path):
    verifier = DispatchVerifier()
    factory = OperationFactory(_accepted_outcome())
    runtime = _runtime(tmp_path, factory, clock=lambda: NOW, verifier=verifier)

    await runtime.executor.dispatch(
        CapabilityReference("opaque-authorization-ref"),
        _request(),
    )

    assert verifier.contexts == [
        DelegatedAuthorizationContext(
            audience="baton://delegated-provider-executor",
            workload_id="mea-comms",
            purpose="case_notification",
            issuer_policy_ref="signet://issuer-policy/mea-comms",
            rotation_policy_ref="signet://rotation-policy/mea-comms",
        )
    ]
    assert len(factory.prepared) == 1


@pytest.mark.parametrize(
    "replacements",
    [
        {"audience": "baton://other-executor"},
        {"principal": "other-workload"},
        {"allowed_purposes": frozenset({"other_purpose"})},
        {"not_before": NOW + timedelta(minutes=1)},
    ],
)
async def test_runtime_rejects_rebound_verified_context_before_provider_use(
    tmp_path,
    replacements,
):
    factory = OperationFactory(_accepted_outcome())
    runtime = _runtime(
        tmp_path,
        factory,
        clock=lambda: NOW,
        verifier=RebindingDispatchVerifier(**replacements),
    )

    with pytest.raises(AuthorizationDenied):
        await runtime.executor.dispatch(
            CapabilityReference("opaque-authorization-ref"),
            _request(),
        )

    assert factory.prepared == []


async def test_runtime_rejects_independent_dispatch_only_verifier_outcome(tmp_path):
    factory = OperationFactory(_accepted_outcome())
    runtime = _runtime(
        tmp_path,
        factory,
        clock=lambda: NOW,
        verifier=IndependentDispatchVerifier(),
    )

    with pytest.raises(AuthorizationDenied):
        await runtime.executor.dispatch(
            CapabilityReference("opaque-authorization-ref"),
            _request(),
        )

    assert factory.prepared == []


async def test_runtime_replays_completed_dispatch_without_second_provider_operation(tmp_path):
    first_factory = OperationFactory(_accepted_outcome())
    first_runtime = _runtime(tmp_path, first_factory, clock=lambda: NOW)

    first = await first_runtime.executor.dispatch(
        CapabilityReference("opaque-authorization-ref"),
        _request(),
    )

    second_factory = OperationFactory(_accepted_outcome())
    second_runtime = _runtime(tmp_path, second_factory, clock=lambda: NOW)
    second = await second_runtime.executor.dispatch(
        CapabilityReference("another-opaque-ref"),
        _request(),
    )

    assert first == second
    assert len(first_factory.prepared) == 1
    assert second_factory.prepared == []
    assert not hasattr(first_factory.prepared[0][1], "material")
    assert second_runtime.reference_state is not None
    verification = await second_runtime.reference_state.verify_event_chain()
    assert verification.ok is True
    assert verification.event_count >= 3


async def test_stale_claim_is_reclaimed_and_old_worker_cannot_complete(tmp_path):
    clock = MutableClock()
    state = SqliteDelegatedRuntimeState(
        tmp_path / "runtime.sqlite3",
        claim_lease_seconds=5,
        clock=clock,
    )
    binding = DispatchBinding("dispatch-once-1", FINGERPRINT)
    first_claim = await state.journal.begin(binding)
    assert first_claim is not None

    clock.now += timedelta(seconds=6)
    second_claim = await state.journal.begin(binding)
    assert second_claim is not None
    assert second_claim.claim_id != first_claim.claim_id

    with pytest.raises(DispatchStateUnavailable):
        await state.journal.complete(first_claim, _delivery())

    await state.journal.complete(second_claim, _delivery())
    assert await state.journal.completed(binding) == _delivery()


async def test_sqlite_reference_serializes_competing_claims_and_attempts(tmp_path):
    state = SqliteDelegatedRuntimeState(tmp_path / "runtime.sqlite3", clock=lambda: NOW)
    binding = DispatchBinding("dispatch-once-1", FINGERPRINT)

    claims = await asyncio.gather(
        state.journal.begin(binding),
        state.journal.begin(binding),
    )
    active_claims = [claim for claim in claims if claim is not None]
    assert len(active_claims) == 1
    assert claims.count(None) == 1

    claim = active_claims[0]
    request = _custody_request(claim_id=claim.claim_id)
    authorization = await CustodyVerifier().verify(None, request)
    reservation = await state.ledger.reserve_once(authorization, request)
    use = _authorized_use(
        claim_id=claim.claim_id,
        reservation_id=reservation.reservation_id,
    )

    attempts = await asyncio.gather(
        state.ledger.reserve_attempt(reservation, use),
        state.ledger.reserve_attempt(reservation, use),
        return_exceptions=True,
    )
    assert attempts.count(1) == 1
    assert sum(isinstance(result, CustodyAuthorizationDenied) for result in attempts) == 1


async def test_expired_claim_is_inactive_before_another_worker_reclaims_it(tmp_path):
    clock = MutableClock()
    state = SqliteDelegatedRuntimeState(
        tmp_path / "runtime.sqlite3",
        claim_lease_seconds=5,
        clock=clock,
    )
    binding = DispatchBinding("dispatch-once-1", FINGERPRINT)
    claim = await state.journal.begin(binding)
    assert claim is not None
    request = _custody_request(claim_id=claim.claim_id)
    authorization = await CustodyVerifier().verify(None, request)
    reservation = await state.ledger.reserve_once(authorization, request)

    clock.now += timedelta(seconds=6)

    with pytest.raises(DispatchStateUnavailable, match="no longer active"):
        await state.journal.renew(claim)
    with pytest.raises(DispatchStateUnavailable, match="no longer active"):
        await state.journal.complete(claim, _delivery())
    with pytest.raises(ConsumptionReservationRequired, match="active exact"):
        await state.ledger.reserve_once(authorization, request)
    with pytest.raises(ConsumptionReservationRequired, match="active exact"):
        await state.ledger.reserve_attempt(
            reservation,
            _authorized_use(
                claim_id=claim.claim_id,
                reservation_id=reservation.reservation_id,
            ),
        )


async def test_durable_ledger_reuses_exact_reservation_and_rejects_rebinding(tmp_path):
    state = SqliteDelegatedRuntimeState(tmp_path / "runtime.sqlite3", clock=lambda: NOW)
    first_binding = DispatchBinding("dispatch-once-1", FINGERPRINT)
    first_claim = await state.journal.begin(first_binding)
    assert first_claim is not None
    first_request = _custody_request(claim_id=first_claim.claim_id)
    first_authorization = await CustodyVerifier().verify(None, first_request)

    first = await state.ledger.reserve_once(first_authorization, first_request)
    replay = await state.ledger.reserve_once(first_authorization, first_request)
    assert replay == first

    other_fingerprint = _fingerprint("dispatch-once-2")
    other_binding = DispatchBinding("dispatch-once-2", other_fingerprint)
    other_claim = await state.journal.begin(other_binding)
    assert other_claim is not None
    other_request = _custody_request(
        idempotency_key="dispatch-once-2",
        fingerprint=other_fingerprint,
        claim_id=other_claim.claim_id,
    )
    rebound_authorization = VerifiedWorkloadAuthorization(
        authorization_id=first_authorization.authorization_id,
        workload_id=other_request.workload_id,
        allowed_connector_ids=frozenset({"sms-primary"}),
        allowed_channels=frozenset({ProviderChannel.SMS}),
        allowed_purposes=frozenset({"case_notification"}),
        request_fingerprint=other_fingerprint,
        not_before=NOW - timedelta(minutes=1),
        not_after=NOW + timedelta(minutes=10),
        max_uses=1,
        max_provider_attempts=1,
    )
    with pytest.raises(CustodyAuthorizationDenied):
        await state.ledger.reserve_once(rebound_authorization, other_request)


async def test_provider_attempt_budget_survives_dispatch_claim_recovery(tmp_path):
    state = SqliteDelegatedRuntimeState(tmp_path / "runtime.sqlite3", clock=lambda: NOW)
    binding = DispatchBinding("dispatch-once-1", FINGERPRINT)
    first_claim = await state.journal.begin(binding)
    assert first_claim is not None
    request = _custody_request(claim_id=first_claim.claim_id)
    authorization = await CustodyVerifier().verify(None, request)
    reservation = await state.ledger.reserve_once(authorization, request)
    first_use = _authorized_use(
        claim_id=first_claim.claim_id,
        reservation_id=reservation.reservation_id,
    )

    with pytest.raises(ConsumptionReservationRequired, match="does not bind"):
        await state.ledger.reserve_attempt(
            reservation,
            _authorized_use(
                claim_id=first_claim.claim_id,
                idempotency_key="dispatch-once-2",
                fingerprint="b" * 64,
                reservation_id=reservation.reservation_id,
            ),
        )
    assert await state.ledger.reserve_attempt(reservation, first_use) == 1
    await state.journal.abort(first_claim)

    second_claim = await state.journal.begin(binding)
    assert second_claim is not None
    replay_request = _custody_request(claim_id=second_claim.claim_id)
    replay_reservation = await state.ledger.reserve_once(authorization, replay_request)
    second_use = _authorized_use(
        claim_id=second_claim.claim_id,
        reservation_id=reservation.reservation_id,
    )

    assert replay_reservation == reservation
    with pytest.raises(CustodyAuthorizationDenied, match="budget is exhausted"):
        await state.ledger.reserve_attempt(replay_reservation, second_use)


async def test_stale_claim_cannot_reserve_authorization_or_provider_attempt(tmp_path):
    clock = MutableClock()
    state = SqliteDelegatedRuntimeState(
        tmp_path / "runtime.sqlite3",
        claim_lease_seconds=5,
        clock=clock,
    )
    binding = DispatchBinding("dispatch-once-1", FINGERPRINT)
    first_claim = await state.journal.begin(binding)
    assert first_claim is not None
    first_request = _custody_request(claim_id=first_claim.claim_id)
    authorization = await CustodyVerifier().verify(None, first_request)
    reservation = await state.ledger.reserve_once(authorization, first_request)

    clock.now += timedelta(seconds=6)
    second_claim = await state.journal.begin(binding)
    assert second_claim is not None

    with pytest.raises(ConsumptionReservationRequired, match="active exact"):
        await state.ledger.reserve_once(authorization, first_request)
    with pytest.raises(ConsumptionReservationRequired, match="active exact"):
        await state.ledger.reserve_attempt(
            reservation,
            _authorized_use(
                claim_id=first_claim.claim_id,
                reservation_id=reservation.reservation_id,
            ),
        )

    assert await state.ledger.reserve_attempt(
        reservation,
        _authorized_use(
            claim_id=second_claim.claim_id,
            reservation_id=reservation.reservation_id,
        ),
    ) == 1


async def test_hash_chain_detects_tampering(tmp_path):
    state = SqliteDelegatedRuntimeState(tmp_path / "runtime.sqlite3", clock=lambda: NOW)
    await state.sink.emit(
        DispatchSignal(
            kind=DispatchSignalKind.ATTEMPT_SUCCEEDED,
            workflow_id="operation-1",
            channel=Channel.SMS,
            dispatch_id="dispatch-1",
            connector_id="sms-primary",
            provider_key="provider-primary",
            attempt_count=1,
        )
    )
    assert (await state.verify_event_chain()).ok is True

    with sqlite3.connect(state.path) as connection:
        connection.execute(
            "UPDATE operational_events SET payload_json = ? WHERE sequence = 1",
            ('{"tampered":true}',),
        )

    verification = await state.verify_event_chain()
    assert verification.ok is False
    assert verification.broken_sequence == 1


async def test_failure_notifications_are_durable_and_acknowledgeable(tmp_path):
    state = SqliteDelegatedRuntimeState(tmp_path / "runtime.sqlite3", clock=lambda: NOW)
    event = CustodyAuditEvent(
        kind=CustodyAuditKind.INVOCATION_FAILED,
        operation_id="operation-1",
        dispatch_id="dispatch-1",
        workload_id="mea-comms",
        connector_id="sms-primary",
        provider_key="provider-primary",
        authorization_id="authorization-1",
        failure_code="provider_timeout",
    )

    await state.sink.notify(event)
    await state.sink.notify(event)
    pending = await state.pending_failure_notifications()

    assert len(pending) == 1
    assert pending[0]["payload"]["failure_code"] == "provider_timeout"
    assert await state.acknowledge_failure_notification(pending[0]["notification_key"])
    assert await state.pending_failure_notifications() == []
    assert (await state.verify_event_chain()).ok is True


async def test_runtime_failure_persists_sanitized_notification(tmp_path):
    factory = OperationFactory(
        SanitizedCustodyOutcome(
            operation_id="operation-1",
            dispatch_id="dispatch-dispatch-once-1",
            provider_key="provider-primary",
            status=CustodyResultStatus.FAILED,
            audit_ref="audit-provider-timeout",
            failure_code="provider_timeout",
        )
    )
    runtime = _runtime(tmp_path, factory, clock=lambda: NOW)

    outcome = await runtime.executor.dispatch(
        CapabilityReference("opaque-authorization-ref"),
        _request(),
    )

    assert outcome.status is DeliveryStatus.EXHAUSTED
    assert outcome.failure_code == "provider_timeout"
    assert runtime.reference_state is not None
    pending = await runtime.reference_state.pending_failure_notifications()
    assert len(pending) == 1
    assert pending[0]["payload"]["failure_code"] == "provider_timeout"
    assert "recipient-ref-1" not in str(pending)
    assert "payload-ref-1" not in str(pending)


@pytest.mark.parametrize("failure_mode", ["ledger", "audit"])
async def test_post_provider_state_failure_is_non_retryable_and_does_not_resend(
    tmp_path,
    failure_mode,
):
    factory = OperationFactory(_accepted_outcome())
    state = SqliteDelegatedRuntimeState(tmp_path / "runtime.sqlite3", clock=lambda: NOW)
    ledger = CompleteFailingLedger(state.ledger) if failure_mode == "ledger" else state.ledger
    audit_sink = OutcomeFailingAuditSink(state.sink) if failure_mode == "audit" else state.sink
    runtime = DelegatedConnectorRuntime.compose(
        routes=[_route()],
        handles={"sms-primary": _handle()},
        verifiers=ConfiguredVerifierBundle(
            verifier=DispatchVerifier(),
            audience="baton://delegated-provider-executor",
            issuer_policy_ref="signet://issuer-policy/mea-comms",
            rotation_policy_ref="signet://rotation-policy/mea-comms",
        ),
        operation_factory=factory,
        components=DelegatedRuntimeComponents(
            journal=state.journal,
            ledger=ledger,
            signal_sink=state.sink,
            audit_sink=audit_sink,
            failure_notifier=state.sink,
            claim_lease_seconds=60,
        ),
        workload_id="mea-comms",
        purpose="case_notification",
        clock=lambda: NOW,
    )

    outcome = await runtime.executor.dispatch(
        CapabilityReference("opaque-authorization-ref"),
        _request(),
    )

    assert outcome.status is DeliveryStatus.EXHAUSTED
    assert outcome.failure_code == "custody_state_unavailable"
    assert outcome.attempt_count == 1
    assert sum(operation.calls for operation in factory.operations) == 1
    assert runtime.reference_state is None
    pending = await state.pending_failure_notifications()
    assert any(
        notification["payload"]["failure_code"] == "custody_state_unavailable"
        for notification in pending
    )
    assert "recipient-ref-1" not in str(pending)
    assert "payload-ref-1" not in str(pending)


async def test_single_purpose_resolver_returns_only_sanitized_outcome():
    factory = OperationFactory(_accepted_outcome())
    resolver = SinglePurposeCustodiedResolver(factory)
    use = _authorized_use(claim_id="claim-1")

    outcome = await resolver.invoke(_handle(), use)

    assert outcome == _accepted_outcome()
    assert not hasattr(factory.prepared[0][0], "material")
    assert not hasattr(factory.prepared[0][1], "material")


def test_runtime_builder_rejects_non_durable_or_incomplete_construction(tmp_path):
    with pytest.raises(ValueError, match=":memory:"):
        SqliteDelegatedRuntimeState(":memory:")

    with pytest.raises(ValueError, match="missing exact custody handle"):
        DelegatedConnectorRuntime.build_sqlite_reference(
            routes=[_route()],
            handles={},
            verifiers=ConfiguredVerifierBundle(
                verifier=DispatchVerifier(),
                audience="baton://delegated-provider-executor",
                issuer_policy_ref="signet://issuer-policy/mea-comms",
                rotation_policy_ref="signet://rotation-policy/mea-comms",
            ),
            operation_factory=OperationFactory(_accepted_outcome()),
            state_path=tmp_path / "runtime.sqlite3",
            workload_id="mea-comms",
            purpose="case_notification",
        )

    with pytest.raises(ValueError, match="claim lease must exceed"):
        DelegatedConnectorRuntime.build_sqlite_reference(
            routes=[_route()],
            handles={"sms-primary": _handle()},
            verifiers=ConfiguredVerifierBundle(
                verifier=DispatchVerifier(),
                audience="baton://delegated-provider-executor",
                issuer_policy_ref="signet://issuer-policy/mea-comms",
                rotation_policy_ref="signet://rotation-policy/mea-comms",
            ),
            operation_factory=OperationFactory(_accepted_outcome()),
            state_path=tmp_path / "short-lease.sqlite3",
            workload_id="mea-comms",
            purpose="case_notification",
            claim_lease_seconds=5,
        )
