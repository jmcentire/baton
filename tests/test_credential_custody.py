"""Credential-free contract checks for the provider custody boundary."""

from datetime import datetime, timedelta, timezone

import pytest

from baton.credential_custody import (
    ConsumptionReservation,
    ConsumptionReservationRequired,
    CredentialUseRequest,
    CredentialCustodyAuthorizer,
    CustodyAuthorizationDenied,
    CustodyResultStatus,
    ProviderChannel,
    ProviderCredentialHandle,
    SanitizedCustodyOutcome,
    VerifiedWorkloadAuthorization,
    WorkloadAuthorizationReference,
    authorize_provider_dispatch,
)


FINGERPRINT = "a" * 64
NOW = datetime(2026, 6, 4, tzinfo=timezone.utc)


def _handle(
    connector_id: str = "sms-primary",
    provider_key: str = "provider-primary",
) -> ProviderCredentialHandle:
    return ProviderCredentialHandle(
        handle_id=f"handle-{connector_id}-v3",
        connector_id=connector_id,
        provider_key=provider_key,
        channel=ProviderChannel.SMS,
        version_ref="active-v3",
    )


def _request(**overrides) -> CredentialUseRequest:
    fields = {
        "operation_id": "operation-1",
        "dispatch_id": "dispatch-1",
        "workload_id": "mea-comms",
        "connector_id": "sms-primary",
        "channel": ProviderChannel.SMS,
        "purpose": "case_notification",
        "recipient_ref": "recipient-ref-1",
        "payload_ref": "payload-ref-1",
        "idempotency_key": "dispatch-once-1",
        "request_fingerprint": FINGERPRINT,
    }
    fields.update(overrides)
    return CredentialUseRequest(**fields)


def _authorization(**overrides) -> VerifiedWorkloadAuthorization:
    fields = {
        "authorization_id": "authorization-1",
        "workload_id": "mea-comms",
        "allowed_connector_ids": frozenset({"sms-primary", "sms-backup"}),
        "allowed_channels": frozenset({ProviderChannel.SMS}),
        "allowed_purposes": frozenset({"case_notification"}),
        "request_fingerprint": FINGERPRINT,
        "not_before": NOW - timedelta(minutes=1),
        "not_after": NOW + timedelta(minutes=5),
        "max_uses": None,
        "max_provider_attempts": 3,
    }
    fields.update(overrides)
    return VerifiedWorkloadAuthorization(**fields)


def _reservation(**overrides) -> ConsumptionReservation:
    fields = {
        "reservation_id": "reservation-1",
        "authorization_id": "authorization-1",
        "request_fingerprint": FINGERPRINT,
        "idempotency_key": "dispatch-once-1",
    }
    fields.update(overrides)
    return ConsumptionReservation(**fields)


class OutcomeLedger:
    def __init__(self, reservation: ConsumptionReservation | None = None):
        self.reservation = reservation or _reservation()
        self.requests: list[CredentialUseRequest] = []

    async def reserve_once(
        self,
        _authorization: VerifiedWorkloadAuthorization,
        request: CredentialUseRequest,
    ) -> ConsumptionReservation:
        self.requests.append(request)
        return self.reservation


class OutcomeVerifier:
    def __init__(self, authorization: VerifiedWorkloadAuthorization):
        self.authorization = authorization

    async def verify(
        self,
        _reference: WorkloadAuthorizationReference,
        _request: CredentialUseRequest,
    ) -> VerifiedWorkloadAuthorization:
        return self.authorization


async def test_single_dispatch_reservation_authorizes_only_opaque_handle_use():
    dispatch = await authorize_provider_dispatch(
        _handle(),
        _request(),
        _authorization(max_uses=1),
        ledger=OutcomeLedger(),
        now=NOW,
    )
    result = dispatch.authorize_handle(_handle())

    assert result.handle_id == "handle-sms-primary-v3"
    assert result.dispatch_id == "dispatch-1"
    assert result.recipient_ref == "recipient-ref-1"
    assert result.payload_ref == "payload-ref-1"
    assert result.reservation_id == "reservation-1"
    assert dispatch.max_provider_attempts == 3
    assert not hasattr(result, "material")


async def test_request_fingerprint_change_is_denied():
    with pytest.raises(CustodyAuthorizationDenied):
        await authorize_provider_dispatch(
            _handle(),
            _request(request_fingerprint="b" * 64),
            _authorization(max_uses=1),
            ledger=OutcomeLedger(_reservation(request_fingerprint="b" * 64)),
            now=NOW,
        )


async def test_connector_or_purpose_outside_scope_is_denied():
    with pytest.raises(CustodyAuthorizationDenied):
        await authorize_provider_dispatch(
            _handle(),
            _request(purpose="unapproved_operation"),
            _authorization(max_uses=1),
            ledger=OutcomeLedger(),
            now=NOW,
        )


async def test_expired_authorization_is_denied():
    with pytest.raises(CustodyAuthorizationDenied):
        await authorize_provider_dispatch(
            _handle(),
            _request(),
            _authorization(max_uses=1, not_after=NOW),
            ledger=OutcomeLedger(),
            now=NOW,
        )


async def test_unbounded_authorization_is_denied_before_ledger_reservation():
    ledger = OutcomeLedger()
    with pytest.raises(CustodyAuthorizationDenied):
        await authorize_provider_dispatch(
            _handle(), _request(), _authorization(), ledger=ledger, now=NOW
        )
    assert ledger.requests == []


async def test_bounded_authorization_reserves_through_ledger():
    ledger = OutcomeLedger()
    result = await authorize_provider_dispatch(
        _handle(),
        _request(),
        _authorization(max_uses=1),
        ledger=ledger,
        now=NOW,
    )
    assert result.reservation_id == "reservation-1"
    assert ledger.requests == [_request()]


async def test_bounded_authorization_rejects_reservation_for_other_request():
    with pytest.raises(ConsumptionReservationRequired):
        await authorize_provider_dispatch(
            _handle(),
            _request(),
            _authorization(max_uses=1),
            ledger=OutcomeLedger(_reservation(request_fingerprint="b" * 64)),
            now=NOW,
        )


async def test_authorizer_obtains_verified_outcome_then_reserves_it():
    authorizer = CredentialCustodyAuthorizer(
        OutcomeVerifier(_authorization(max_uses=1)),
        OutcomeLedger(),
        clock=lambda: NOW,
    )
    result = await authorizer.authorize(
        WorkloadAuthorizationReference("authorization-ref-1"),
        _handle(),
        _request(),
    )
    assert result.authorization_id == "authorization-1"


async def test_invalid_initial_handle_is_denied_before_ledger_reservation():
    ledger = OutcomeLedger()
    with pytest.raises(CustodyAuthorizationDenied):
        await authorize_provider_dispatch(
            _handle("sms-backup", "provider-backup"),
            _request(),
            _authorization(max_uses=1),
            ledger=ledger,
            now=NOW,
        )
    assert ledger.requests == []


async def test_one_reserved_dispatch_allows_scoped_primary_to_backup_selection():
    ledger = OutcomeLedger()
    dispatch = await authorize_provider_dispatch(
        _handle(),
        _request(),
        _authorization(max_uses=1),
        ledger=ledger,
        now=NOW,
    )

    primary = dispatch.authorize_handle(_handle())
    backup = dispatch.authorize_handle(_handle("sms-backup", "provider-backup"))
    assert primary.reservation_id == backup.reservation_id == "reservation-1"
    assert len(ledger.requests) == 1

    with pytest.raises(CustodyAuthorizationDenied):
        dispatch.authorize_handle(_handle("sms-unapproved", "provider-unapproved"))


def test_authorization_rejects_zero_provider_attempt_budget():
    with pytest.raises(ValueError):
        _authorization(max_provider_attempts=0)


def test_outcome_allows_only_sanitized_failure_identifier():
    result = SanitizedCustodyOutcome(
        operation_id="operation-1",
        dispatch_id="dispatch-1",
        provider_key="provider-primary",
        status=CustodyResultStatus.FAILED,
        audit_ref="audit-1",
        failure_code="provider_timeout",
    )
    assert result.failure_code == "provider_timeout"

    with pytest.raises(ValueError):
        SanitizedCustodyOutcome(
            operation_id="operation-1",
            dispatch_id="dispatch-1",
            provider_key="provider-primary",
            status=CustodyResultStatus.FAILED,
            audit_ref="audit-1",
            failure_code="raw upstream detail: refused",
        )
