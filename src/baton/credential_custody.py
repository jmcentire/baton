"""Cloud-neutral provider credential custody contracts.

This module defines the boundary between a business workflow and a
single-purpose provider executor. No public type carries credential values.
A concrete resolver may access provider material only while executing an
already authorized operation inside the custody boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from collections.abc import Callable, Mapping
from typing import Protocol

from .delegated_connector import (
    AuthorizationDenied as DelegatedAuthorizationDenied,
    CapabilityReference,
    ConnectorRoute,
    CustodiedProviderInvoker,
    DeliveryStatus,
    DispatchRequest,
    ProviderAttemptOutcome,
    VerifiedDispatchGrant,
)


_FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ProviderChannel(StrEnum):
    SMS = "sms"
    EMAIL = "email"


class CustodyResultStatus(StrEnum):
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    FAILED = "failed"


class CustodyAuditKind(StrEnum):
    AUTHORIZATION_DENIED = "authorization_denied"
    AUTHORIZATION_ACCEPTED = "authorization_accepted"
    RESERVATION_REQUIRED = "reservation_required"
    REPLAY_REJECTED = "replay_rejected"
    INVOCATION_COMPLETED = "invocation_completed"
    INVOCATION_FAILED = "invocation_failed"


class CustodyError(Exception):
    """Base error for the non-material custody boundary."""


class CustodyAuthorizationDenied(CustodyError):
    """A verified outcome cannot authorize this provider operation."""


class ConsumptionReservationRequired(CustodyAuthorizationDenied):
    """Bounded-use authority lacks an atomic consumption reservation."""


@dataclass(frozen=True)
class ProviderCredentialHandle:
    """Opaque lookup handle configured by an administrator.

    ``handle_id`` is not a provider credential, secret-store URI, or ciphertext.
    The custody implementation owns the mapping to a concrete backend record.
    """

    handle_id: str
    connector_id: str
    provider_key: str
    channel: ProviderChannel
    version_ref: str

    def __post_init__(self) -> None:
        for name in ("handle_id", "connector_id", "provider_key", "version_ref"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")


@dataclass(frozen=True)
class WorkloadAuthorizationReference:
    """Opaque reference to a signed authorization checked by a trusted verifier."""

    reference: str

    def __post_init__(self) -> None:
        if not self.reference:
            raise ValueError("authorization reference is required")


@dataclass(frozen=True)
class CredentialUseRequest:
    """Immutable provider-use scope supplied to the custody boundary."""

    operation_id: str
    dispatch_id: str
    workload_id: str
    connector_id: str
    channel: ProviderChannel
    purpose: str
    recipient_ref: str
    payload_ref: str
    idempotency_key: str
    request_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "operation_id",
            "dispatch_id",
            "workload_id",
            "connector_id",
            "purpose",
            "recipient_ref",
            "payload_ref",
            "idempotency_key",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        if not _FINGERPRINT_RE.fullmatch(self.request_fingerprint):
            raise ValueError("request_fingerprint must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class VerifiedWorkloadAuthorization:
    """Credential-free outcome returned after trusted signature verification."""

    authorization_id: str
    workload_id: str
    allowed_connector_ids: frozenset[str]
    allowed_channels: frozenset[ProviderChannel]
    allowed_purposes: frozenset[str]
    request_fingerprint: str
    not_before: datetime
    not_after: datetime
    max_uses: int | None
    max_provider_attempts: int

    def __post_init__(self) -> None:
        if not self.authorization_id or not self.workload_id:
            raise ValueError("authorization_id and workload_id are required")
        if not _FINGERPRINT_RE.fullmatch(self.request_fingerprint):
            raise ValueError("request_fingerprint must be a lowercase SHA-256 digest")
        if self.not_before.tzinfo is None or self.not_after.tzinfo is None:
            raise ValueError("authorization timestamps must be timezone-aware")
        if self.not_after <= self.not_before:
            raise ValueError("authorization expiry must be after not_before")
        if self.max_uses is not None and self.max_uses < 1:
            raise ValueError("max_uses must be positive when bounded")
        if self.max_provider_attempts < 1:
            raise ValueError("max_provider_attempts must be positive")


@dataclass(frozen=True)
class ConsumptionReservation:
    """Atomic bounded-use reservation produced by a durable ledger."""

    reservation_id: str
    authorization_id: str
    request_fingerprint: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.reservation_id or not self.authorization_id or not self.idempotency_key:
            raise ValueError("reservation identifiers are required")
        if not _FINGERPRINT_RE.fullmatch(self.request_fingerprint):
            raise ValueError("request_fingerprint must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class AuthorizedCredentialUse:
    """Non-material authorization passed to a custody-internal invoker."""

    authorization_id: str
    handle_id: str
    connector_id: str
    provider_key: str
    operation_id: str
    dispatch_id: str
    recipient_ref: str
    payload_ref: str
    idempotency_key: str
    request_fingerprint: str
    reservation_id: str = ""


@dataclass(frozen=True)
class AuthorizedProviderDispatch:
    """Reserved provider dispatch that may select only scoped connector handles."""

    authorization_id: str
    workload_id: str
    allowed_connector_ids: frozenset[str]
    channel: ProviderChannel
    purpose: str
    operation_id: str
    dispatch_id: str
    recipient_ref: str
    payload_ref: str
    idempotency_key: str
    request_fingerprint: str
    reservation_id: str
    max_provider_attempts: int

    def authorize_handle(self, handle: ProviderCredentialHandle) -> AuthorizedCredentialUse:
        if handle.connector_id not in self.allowed_connector_ids:
            raise CustodyAuthorizationDenied("connector is outside authorization scope")
        if handle.channel is not self.channel:
            raise CustodyAuthorizationDenied("channel is outside authorization scope")
        return AuthorizedCredentialUse(
            authorization_id=self.authorization_id,
            handle_id=handle.handle_id,
            connector_id=handle.connector_id,
            provider_key=handle.provider_key,
            operation_id=self.operation_id,
            dispatch_id=self.dispatch_id,
            recipient_ref=self.recipient_ref,
            payload_ref=self.payload_ref,
            idempotency_key=self.idempotency_key,
            request_fingerprint=self.request_fingerprint,
            reservation_id=self.reservation_id,
        )


@dataclass(frozen=True)
class SanitizedCustodyOutcome:
    """Result safe to emit outside the provider custody boundary."""

    operation_id: str
    dispatch_id: str
    provider_key: str
    status: CustodyResultStatus
    audit_ref: str
    failure_code: str = ""
    retryable: bool = False
    failover_allowed: bool = False
    counts_toward_circuit: bool = False

    def __post_init__(self) -> None:
        if not self.operation_id or not self.dispatch_id or not self.provider_key:
            raise ValueError("outcome identity fields are required")
        if not self.audit_ref:
            raise ValueError("audit_ref is required")
        if self.failure_code and not _CODE_RE.fullmatch(self.failure_code):
            raise ValueError("failure_code must be a sanitized identifier")
        if self.status is CustodyResultStatus.FAILED and not self.failure_code:
            raise ValueError("failed outcomes require a failure_code")
        if self.status is not CustodyResultStatus.FAILED and self.failure_code:
            raise ValueError("successful outcomes cannot contain a failure_code")
        if self.status is not CustodyResultStatus.FAILED and (
            self.retryable or self.failover_allowed or self.counts_toward_circuit
        ):
            raise ValueError("successful outcomes cannot contain failure policy flags")


@dataclass(frozen=True)
class CustodyAuditEvent:
    """Sanitized accountability event, suitable for alerting and audit sinks."""

    kind: CustodyAuditKind
    operation_id: str
    dispatch_id: str
    workload_id: str
    connector_id: str
    provider_key: str
    authorization_id: str = ""
    failure_code: str = ""

    def __post_init__(self) -> None:
        for name in (
            "operation_id",
            "dispatch_id",
            "workload_id",
            "connector_id",
            "provider_key",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        if self.failure_code and not _CODE_RE.fullmatch(self.failure_code):
            raise ValueError("failure_code must be a sanitized identifier")


class SignedWorkloadAuthorizationVerifier(Protocol):
    """Validate origin and scope of a signed workload authorization."""

    async def verify(
        self,
        reference: WorkloadAuthorizationReference,
        request: CredentialUseRequest,
    ) -> VerifiedWorkloadAuthorization:
        ...


class AuthorizationConsumptionLedger(Protocol):
    """Reserve bounded authority atomically and persist terminal outcomes.

    A concrete implementation must reject reuse with a different request
    fingerprint. The delegated executor journal is responsible for returning
    an already completed sanitized delivery outcome rather than invoking twice.
    """

    async def reserve_once(
        self,
        authorization: VerifiedWorkloadAuthorization,
        request: CredentialUseRequest,
    ) -> ConsumptionReservation:
        ...

    async def complete(
        self,
        reservation: ConsumptionReservation,
        outcome: SanitizedCustodyOutcome,
    ) -> None:
        ...


class CustodiedReferenceResolver(Protocol):
    """Invoke a provider operation while keeping resolved material internal."""

    async def invoke(
        self,
        handle: ProviderCredentialHandle,
        authorized_use: AuthorizedCredentialUse,
    ) -> SanitizedCustodyOutcome:
        ...


class CustodyAuditSink(Protocol):
    """Persist sanitized custody transitions for accountability."""

    async def emit(self, event: CustodyAuditEvent) -> None:
        ...


class CustodyFailureNotifier(Protocol):
    """Raise sanitized operational notifications for custody failures."""

    async def notify(self, event: CustodyAuditEvent) -> None:
        ...


async def authorize_provider_dispatch(
    initial_handle: ProviderCredentialHandle,
    request: CredentialUseRequest,
    authorization: VerifiedWorkloadAuthorization,
    *,
    ledger: AuthorizationConsumptionLedger,
    provider_attempt_budget: int | None = None,
    required_connector_ids: frozenset[str] | None = None,
    now: datetime | None = None,
) -> AuthorizedProviderDispatch:
    """Validate and reserve a credential-free verifier outcome for one dispatch.

    Provider-use authority must describe exactly one dispatch and cannot cross
    this boundary unless a ledger has atomically reserved the exact
    authorization, request fingerprint, and idempotency key.
    """

    current_time = now or datetime.now(timezone.utc)
    if current_time < authorization.not_before or current_time >= authorization.not_after:
        raise CustodyAuthorizationDenied("workload authorization is outside its validity window")
    if authorization.workload_id != request.workload_id:
        raise CustodyAuthorizationDenied("workload identity is outside authorization scope")
    if authorization.request_fingerprint != request.request_fingerprint:
        raise CustodyAuthorizationDenied("request fingerprint is outside authorization scope")
    if initial_handle.connector_id != request.connector_id:
        raise CustodyAuthorizationDenied(
            "initial credential handle does not match requested connector"
        )
    if request.connector_id not in authorization.allowed_connector_ids:
        raise CustodyAuthorizationDenied("initial connector is outside authorization scope")
    if required_connector_ids and not required_connector_ids.issubset(
        authorization.allowed_connector_ids
    ):
        raise CustodyAuthorizationDenied("route policy is outside authorization scope")
    if (
        initial_handle.channel is not request.channel
        or request.channel not in authorization.allowed_channels
    ):
        raise CustodyAuthorizationDenied("channel is outside authorization scope")
    if request.purpose not in authorization.allowed_purposes:
        raise CustodyAuthorizationDenied("purpose is outside authorization scope")
    if (
        provider_attempt_budget is not None
        and provider_attempt_budget > authorization.max_provider_attempts
    ):
        raise CustodyAuthorizationDenied(
            "dispatch attempt budget exceeds credential custody scope"
        )

    if authorization.max_uses != 1:
        raise CustodyAuthorizationDenied(
            "provider invocation requires single-dispatch authorization"
        )
    reservation = await ledger.reserve_once(authorization, request)
    if (
        reservation.authorization_id != authorization.authorization_id
        or reservation.request_fingerprint != request.request_fingerprint
        or reservation.idempotency_key != request.idempotency_key
    ):
        raise ConsumptionReservationRequired(
            "ledger reservation does not bind this authorization request"
        )

    return AuthorizedProviderDispatch(
        authorization_id=authorization.authorization_id,
        workload_id=request.workload_id,
        allowed_connector_ids=authorization.allowed_connector_ids,
        channel=request.channel,
        purpose=request.purpose,
        operation_id=request.operation_id,
        dispatch_id=request.dispatch_id,
        recipient_ref=request.recipient_ref,
        payload_ref=request.payload_ref,
        idempotency_key=request.idempotency_key,
        request_fingerprint=request.request_fingerprint,
        reservation_id=reservation.reservation_id,
        max_provider_attempts=authorization.max_provider_attempts,
    )


class CredentialCustodyAuthorizer:
    """Obtain verified authority and reserve its exact provider operation."""

    def __init__(
        self,
        verifier: SignedWorkloadAuthorizationVerifier,
        ledger: AuthorizationConsumptionLedger,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self._verifier = verifier
        self._ledger = ledger
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def authorize(
        self,
        reference: WorkloadAuthorizationReference,
        handle: ProviderCredentialHandle,
        request: CredentialUseRequest,
        *,
        provider_attempt_budget: int | None = None,
        required_connector_ids: frozenset[str] | None = None,
    ) -> AuthorizedProviderDispatch:
        authorization = await self._verifier.verify(reference, request)
        reserved_dispatch = await authorize_provider_dispatch(
            handle,
            request,
            authorization,
            ledger=self._ledger,
            provider_attempt_budget=provider_attempt_budget,
            required_connector_ids=required_connector_ids,
            now=self._clock(),
        )
        return reserved_dispatch


class CredentialCustodyInvokerFactory:
    """Connect delegated dispatch to a single reserved custody execution path."""

    def __init__(
        self,
        authorizer: CredentialCustodyAuthorizer,
        resolver: CustodiedReferenceResolver,
        handles: Mapping[str, ProviderCredentialHandle],
        *,
        workload_id: str,
        purpose: str,
    ):
        if not workload_id or not purpose:
            raise ValueError("workload_id and purpose are required")
        self._authorizer = authorizer
        self._resolver = resolver
        self._handles = dict(handles)
        self._workload_id = workload_id
        self._purpose = purpose

    def _handle_for_route(self, route: ConnectorRoute) -> ProviderCredentialHandle:
        handle = self._handles.get(route.connector_id)
        expected_channel = ProviderChannel(route.channel.value)
        if (
            handle is None
            or handle.handle_id != route.credential_handle
            or handle.provider_key != route.provider_key
            or handle.channel is not expected_channel
        ):
            raise DelegatedAuthorizationDenied("connector custody binding is invalid")
        return handle

    async def prepare(
        self,
        capability: CapabilityReference,
        request: DispatchRequest,
        grant: VerifiedDispatchGrant,
        initial_route: ConnectorRoute,
        authorized_routes: tuple[ConnectorRoute, ...],
    ) -> CustodiedProviderInvoker:
        if initial_route not in authorized_routes:
            raise DelegatedAuthorizationDenied("initial route is outside dispatch policy")
        initial_handle = self._handle_for_route(initial_route)
        for route in authorized_routes:
            self._handle_for_route(route)
        custody_request = CredentialUseRequest(
            operation_id=request.workflow_id,
            dispatch_id=request.dispatch_id,
            workload_id=self._workload_id,
            connector_id=initial_route.connector_id,
            channel=ProviderChannel(request.channel.value),
            purpose=self._purpose,
            recipient_ref=request.recipient_ref,
            payload_ref=request.payload_ref,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
        )
        try:
            reserved_dispatch = await self._authorizer.authorize(
                WorkloadAuthorizationReference(capability.reference),
                initial_handle,
                custody_request,
                provider_attempt_budget=grant.max_attempts,
                required_connector_ids=frozenset(
                    route.connector_id for route in authorized_routes
                ),
            )
        except CustodyAuthorizationDenied as exc:
            raise DelegatedAuthorizationDenied("credential custody authorization denied") from exc
        return _ReservedCustodiedProviderInvoker(
            resolver=self._resolver,
            handles=self._handles,
            dispatch=reserved_dispatch,
            request=request,
        )


class _ReservedCustodiedProviderInvoker:
    def __init__(
        self,
        *,
        resolver: CustodiedReferenceResolver,
        handles: Mapping[str, ProviderCredentialHandle],
        dispatch: AuthorizedProviderDispatch,
        request: DispatchRequest,
    ):
        self._resolver = resolver
        self._handles = dict(handles)
        self._dispatch = dispatch
        self._request = request

    async def invoke(
        self, route: ConnectorRoute, request: DispatchRequest
    ) -> ProviderAttemptOutcome:
        if (
            request.dispatch_id != self._request.dispatch_id
            or request.request_fingerprint != self._request.request_fingerprint
            or request.idempotency_key != self._request.idempotency_key
        ):
            raise DelegatedAuthorizationDenied("prepared custody dispatch was rebound")
        handle = self._handles.get(route.connector_id)
        if (
            handle is None
            or handle.handle_id != route.credential_handle
            or handle.provider_key != route.provider_key
            or handle.channel.value != route.channel.value
        ):
            raise DelegatedAuthorizationDenied("connector custody binding is invalid")
        try:
            authorized_use = self._dispatch.authorize_handle(handle)
            outcome = await self._resolver.invoke(handle, authorized_use)
        except CustodyAuthorizationDenied as exc:
            raise DelegatedAuthorizationDenied("provider custody invocation denied") from exc
        if (
            outcome.operation_id != self._dispatch.operation_id
            or outcome.dispatch_id != request.dispatch_id
            or outcome.provider_key != route.provider_key
        ):
            raise DelegatedAuthorizationDenied("custody outcome binding is invalid")
        return ProviderAttemptOutcome(
            status=DeliveryStatus(outcome.status.value),
            audit_ref=outcome.audit_ref,
            failure_code=outcome.failure_code,
            retryable=outcome.retryable,
            failover_allowed=outcome.failover_allowed,
            counts_toward_circuit=outcome.counts_toward_circuit,
        )
