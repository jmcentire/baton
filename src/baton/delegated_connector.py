"""Cloud-neutral delegated external-provider dispatch orchestration.

This module is the Baton-side runtime boundary for provider-backed delivery.
It accepts opaque authorization and connector references, orchestrates retries,
failover, and circuit breakers, and returns sanitized outcomes only. The
``CustodiedProviderInvoker`` implementation is the single-purpose boundary
allowed to resolve and use provider credential material internally.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Awaitable, Callable, Protocol, Sequence


_SAFE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")


class Channel(StrEnum):
    SMS = "sms"
    EMAIL = "email"


class DeliveryStatus(StrEnum):
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


class DispatchSignalKind(StrEnum):
    AUTHORIZATION_DENIED = "authorization_denied"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    ATTEMPT_FAILED = "attempt_failed"
    ATTEMPT_SUCCEEDED = "attempt_succeeded"
    CIRCUIT_OPEN = "circuit_open"
    FAILOVER_USED = "failover_used"
    DELIVERY_EXHAUSTED = "delivery_exhausted"


class DelegatedConnectorError(Exception):
    """Base error for dispatch decisions that never expose provider material."""


class AuthorizationDenied(DelegatedConnectorError):
    """A capability cannot authorize this dispatch."""


class DispatchInProgress(DelegatedConnectorError):
    """The idempotency key is already executing elsewhere."""


class DispatchBindingConflict(DelegatedConnectorError):
    """An idempotency key was reused for different immutable request content."""


class MonitoringUnavailable(DelegatedConnectorError):
    """A required sanitized signal could not be persisted."""


class InvalidConnectorPolicy(ValueError):
    """Connector routes do not form a valid ordered provider policy."""


@dataclass(frozen=True)
class CapabilityReference:
    """Opaque reference to an authorization proof verified inside the stack."""

    reference: str

    def __post_init__(self) -> None:
        if not self.reference:
            raise ValueError("capability reference is required")


@dataclass(frozen=True)
class DispatchRequest:
    """A provider dispatch instruction containing references, never material."""

    dispatch_id: str
    workflow_id: str
    channel: Channel
    recipient_ref: str
    payload_ref: str
    idempotency_key: str
    request_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "dispatch_id",
            "workflow_id",
            "recipient_ref",
            "payload_ref",
            "idempotency_key",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        if not _FINGERPRINT_RE.fullmatch(self.request_fingerprint):
            raise ValueError("request_fingerprint must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class VerifiedDispatchGrant:
    """Verified authorization scope returned by a trusted verifier."""

    principal: str
    channel: Channel
    allowed_connectors: frozenset[str]
    not_after: datetime
    max_attempts: int
    request_fingerprint: str

    def __post_init__(self) -> None:
        if not self.principal:
            raise ValueError("principal is required")
        if self.not_after.tzinfo is None:
            raise ValueError("not_after must be timezone-aware")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if not _FINGERPRINT_RE.fullmatch(self.request_fingerprint):
            raise ValueError("request_fingerprint must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class ConnectorRoute:
    """Enabled provider metadata and opaque custody binding."""

    connector_id: str
    provider_key: str
    channel: Channel
    credential_handle: str
    priority: int
    enabled: bool = True
    timeout_ms: int = 5000
    max_attempts: int = 1
    retry_backoff_ms: int = 100
    circuit_breaker_threshold: int = 3
    circuit_reset_seconds: float = 60.0

    def __post_init__(self) -> None:
        for name in ("connector_id", "provider_key", "credential_handle"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        if self.priority < 0:
            raise ValueError("priority cannot be negative")
        if self.timeout_ms < 1:
            raise ValueError("timeout_ms must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.retry_backoff_ms < 0:
            raise ValueError("retry_backoff_ms cannot be negative")
        if self.circuit_breaker_threshold < 0:
            raise ValueError("circuit_breaker_threshold cannot be negative")
        if self.circuit_reset_seconds < 0:
            raise ValueError("circuit_reset_seconds cannot be negative")


@dataclass(frozen=True)
class ProviderAttemptOutcome:
    """Sanitized result returned by the custody-internal provider invoker."""

    status: DeliveryStatus
    audit_ref: str
    failure_code: str = ""
    retryable: bool = False
    failover_allowed: bool = False
    counts_toward_circuit: bool = False

    def __post_init__(self) -> None:
        if self.status not in (DeliveryStatus.ACCEPTED, DeliveryStatus.DELIVERED, DeliveryStatus.FAILED):
            raise ValueError("attempt status must be accepted, delivered, or failed")
        if not self.audit_ref:
            raise ValueError("audit_ref is required")
        if self.failure_code and not _SAFE_CODE_RE.fullmatch(self.failure_code):
            raise ValueError("failure_code must contain sanitized identifier characters only")
        if self.status is DeliveryStatus.FAILED and not self.failure_code:
            raise ValueError("failed attempts require a sanitized failure_code")
        if self.status is not DeliveryStatus.FAILED and self.failure_code:
            raise ValueError("successful attempts cannot include a failure_code")


@dataclass(frozen=True)
class DeliveryOutcome:
    """Sanitized result safe to return to a caller such as MEA comms."""

    dispatch_id: str
    workflow_id: str
    channel: Channel
    provider_key: str
    status: DeliveryStatus
    attempt_count: int
    failover_used: bool
    audit_ref: str
    failure_code: str = ""


@dataclass(frozen=True)
class DispatchBinding:
    """Immutable journal binding for one idempotent dispatch instruction."""

    idempotency_key: str
    request_fingerprint: str

    def __post_init__(self) -> None:
        if not self.idempotency_key:
            raise ValueError("idempotency_key is required")
        if not _FINGERPRINT_RE.fullmatch(self.request_fingerprint):
            raise ValueError("request_fingerprint must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class DispatchSignal:
    """Non-sensitive operational event for audit and alert pipelines.

    Every signal carries ``dispatch_id`` so failures, failover, and terminal
    delivery can be correlated without exposing provider material.
    """

    kind: DispatchSignalKind
    workflow_id: str
    channel: Channel
    dispatch_id: str
    connector_id: str = ""
    provider_key: str = ""
    attempt_count: int = 0
    failure_code: str = ""


class ScopedAuthorizationVerifier(Protocol):
    """Verifies capability origin and dispatch scope against trusted policy."""

    async def verify(
        self, capability: CapabilityReference, request: DispatchRequest
    ) -> VerifiedDispatchGrant:
        ...


class CustodiedProviderInvoker(Protocol):
    """Executes one provider operation inside the credential custody boundary."""

    async def invoke(
        self, route: ConnectorRoute, request: DispatchRequest
    ) -> ProviderAttemptOutcome:
        """Use only the matching handle internally and return sanitized metadata."""
        ...


class DispatchJournal(Protocol):
    """Atomic idempotency journal required before any provider invocation.

    Implementations must raise ``DispatchBindingConflict`` when an
    idempotency key was previously bound to a different request fingerprint.
    """

    async def completed(self, binding: DispatchBinding) -> DeliveryOutcome | None:
        ...

    async def begin(self, binding: DispatchBinding) -> bool:
        ...

    async def complete(self, binding: DispatchBinding, outcome: DeliveryOutcome) -> None:
        ...

    async def abort(self, binding: DispatchBinding) -> None:
        ...


class DispatchSignalSink(Protocol):
    """Durably accepts sanitized events used for audit and alerting.

    Terminal events must be idempotent by ``(kind, dispatch_id)`` because
    completed dispatches retry notification delivery without resending.
    """

    async def emit(self, signal: DispatchSignal) -> None:
        ...


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None


class DelegatedConnectorExecutor:
    """Dispatches through authorized ordered connectors with fail-closed controls."""

    def __init__(
        self,
        routes: Sequence[ConnectorRoute],
        verifier: ScopedAuthorizationVerifier,
        invoker: CustodiedProviderInvoker,
        journal: DispatchJournal,
        signal_sink: DispatchSignalSink,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ):
        self._routes = self._validate_routes(routes)
        self._verifier = verifier
        self._invoker = invoker
        self._journal = journal
        self._signal_sink = signal_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._circuits: dict[str, _CircuitState] = {}

    @staticmethod
    def _validate_routes(routes: Sequence[ConnectorRoute]) -> tuple[ConnectorRoute, ...]:
        ids: set[str] = set()
        priorities: set[tuple[Channel, int]] = set()
        for route in routes:
            if route.connector_id in ids:
                raise InvalidConnectorPolicy(f"duplicate connector id: {route.connector_id}")
            ids.add(route.connector_id)
            if route.enabled:
                priority_key = (route.channel, route.priority)
                if priority_key in priorities:
                    raise InvalidConnectorPolicy(
                        f"duplicate active priority for channel: {route.channel.value}/{route.priority}"
                    )
                priorities.add(priority_key)
        return tuple(sorted(routes, key=lambda route: (route.channel.value, route.priority)))

    async def dispatch(
        self, capability: CapabilityReference, request: DispatchRequest
    ) -> DeliveryOutcome:
        """Dispatch once per key and immutable request fingerprint after verification."""
        try:
            grant = await self._verifier.verify(capability, request)
            self._validate_grant(grant, request)
        except Exception as exc:
            await self._emit(
                DispatchSignal(
                    kind=DispatchSignalKind.AUTHORIZATION_DENIED,
                    workflow_id=request.workflow_id,
                    channel=request.channel,
                    dispatch_id=request.dispatch_id,
                    failure_code="authorization_denied",
                )
            )
            if isinstance(exc, AuthorizationDenied):
                raise
            raise AuthorizationDenied("dispatch authorization denied") from exc

        binding = DispatchBinding(request.idempotency_key, request.request_fingerprint)
        try:
            completed = await self._journal.completed(binding)
        except DispatchBindingConflict:
            await self._emit(
                DispatchSignal(
                    kind=DispatchSignalKind.IDEMPOTENCY_CONFLICT,
                    workflow_id=request.workflow_id,
                    channel=request.channel,
                    dispatch_id=request.dispatch_id,
                    failure_code="idempotency_binding_conflict",
                )
            )
            raise
        if completed is not None:
            await self._emit_terminal(completed)
            return completed
        try:
            if not await self._journal.begin(binding):
                raise DispatchInProgress("dispatch with this idempotency key is already in progress")
        except DispatchBindingConflict:
            await self._emit(
                DispatchSignal(
                    kind=DispatchSignalKind.IDEMPOTENCY_CONFLICT,
                    workflow_id=request.workflow_id,
                    channel=request.channel,
                    dispatch_id=request.dispatch_id,
                    failure_code="idempotency_binding_conflict",
                )
            )
            raise

        try:
            outcome = await self._dispatch_authorized(grant, request)
            await self._journal.complete(binding, outcome)
        except Exception:
            await self._journal.abort(binding)
            raise

        await self._emit_terminal(outcome)
        return outcome

    def _validate_grant(self, grant: VerifiedDispatchGrant, request: DispatchRequest) -> None:
        if grant.request_fingerprint != request.request_fingerprint:
            raise AuthorizationDenied("dispatch fingerprint is outside authorization scope")
        if grant.channel is not request.channel:
            raise AuthorizationDenied("dispatch channel is outside authorization scope")
        if self._clock() >= grant.not_after:
            raise AuthorizationDenied("dispatch authorization has expired")
        enabled = {
            route.connector_id
            for route in self._routes
            if route.channel is request.channel and route.enabled
        }
        if not enabled.intersection(grant.allowed_connectors):
            raise AuthorizationDenied("no authorized active connector for dispatch")

    async def _dispatch_authorized(
        self, grant: VerifiedDispatchGrant, request: DispatchRequest
    ) -> DeliveryOutcome:
        routes = [
            route
            for route in self._routes
            if route.channel is request.channel
            and route.enabled
            and route.connector_id in grant.allowed_connectors
        ]
        attempt_count = 0
        last_provider = ""
        last_audit_ref = ""
        last_failure = "provider_unavailable"
        failover_used = False
        attempted_or_skipped_route = False
        allow_next_route = True

        for route in routes:
            if not allow_next_route:
                break
            if self._circuit_is_open(route):
                await self._emit(
                    DispatchSignal(
                        kind=DispatchSignalKind.CIRCUIT_OPEN,
                        workflow_id=request.workflow_id,
                        channel=request.channel,
                        dispatch_id=request.dispatch_id,
                        connector_id=route.connector_id,
                        provider_key=route.provider_key,
                        attempt_count=attempt_count,
                        failure_code="circuit_open",
                    )
                )
                attempted_or_skipped_route = True
                continue
            if attempted_or_skipped_route:
                failover_used = True
                await self._emit(
                    DispatchSignal(
                        kind=DispatchSignalKind.FAILOVER_USED,
                        workflow_id=request.workflow_id,
                        channel=request.channel,
                        dispatch_id=request.dispatch_id,
                        connector_id=route.connector_id,
                        provider_key=route.provider_key,
                        attempt_count=attempt_count,
                    )
                )
            attempted_or_skipped_route = True
            allow_next_route = False

            for local_attempt in range(route.max_attempts):
                if attempt_count >= grant.max_attempts:
                    break
                attempt_count += 1
                last_provider = route.provider_key
                attempt = await self._invoke(route, request)
                last_audit_ref = attempt.audit_ref
                if attempt.status in (DeliveryStatus.ACCEPTED, DeliveryStatus.DELIVERED):
                    self._record_success(route)
                    return DeliveryOutcome(
                        dispatch_id=request.dispatch_id,
                        workflow_id=request.workflow_id,
                        channel=request.channel,
                        provider_key=route.provider_key,
                        status=attempt.status,
                        attempt_count=attempt_count,
                        failover_used=failover_used,
                        audit_ref=attempt.audit_ref,
                    )

                last_failure = attempt.failure_code
                allow_next_route = attempt.failover_allowed
                if attempt.counts_toward_circuit:
                    self._record_failure(route)
                await self._emit(
                    DispatchSignal(
                        kind=DispatchSignalKind.ATTEMPT_FAILED,
                        workflow_id=request.workflow_id,
                        channel=request.channel,
                        dispatch_id=request.dispatch_id,
                        connector_id=route.connector_id,
                        provider_key=route.provider_key,
                        attempt_count=attempt_count,
                        failure_code=attempt.failure_code,
                    )
                )
                if not attempt.retryable:
                    break
                if local_attempt < route.max_attempts - 1 and attempt_count < grant.max_attempts:
                    await self._sleep(route.retry_backoff_ms / 1000)

            if attempt_count >= grant.max_attempts:
                break

        return DeliveryOutcome(
            dispatch_id=request.dispatch_id,
            workflow_id=request.workflow_id,
            channel=request.channel,
            provider_key=last_provider,
            status=DeliveryStatus.EXHAUSTED,
            attempt_count=attempt_count,
            failover_used=failover_used,
            audit_ref=last_audit_ref,
            failure_code=last_failure,
        )

    async def _invoke(
        self, route: ConnectorRoute, request: DispatchRequest
    ) -> ProviderAttemptOutcome:
        try:
            return await asyncio.wait_for(
                self._invoker.invoke(route, request),
                timeout=route.timeout_ms / 1000,
            )
        except TimeoutError:
            return ProviderAttemptOutcome(
                status=DeliveryStatus.FAILED,
                audit_ref=f"timeout:{request.workflow_id}:{route.connector_id}",
                failure_code="provider_timeout",
                retryable=True,
                failover_allowed=True,
                counts_toward_circuit=True,
            )
        except Exception:
            return ProviderAttemptOutcome(
                status=DeliveryStatus.FAILED,
                audit_ref=f"error:{request.workflow_id}:{route.connector_id}",
                failure_code="provider_error",
                retryable=True,
                failover_allowed=True,
                counts_toward_circuit=True,
            )

    def _circuit_is_open(self, route: ConnectorRoute) -> bool:
        if route.circuit_breaker_threshold == 0:
            return False
        state = self._circuits.get(route.connector_id)
        if state is None or state.opened_at is None:
            return False
        if self._monotonic() - state.opened_at >= route.circuit_reset_seconds:
            state.opened_at = None
            return False
        return True

    def _record_success(self, route: ConnectorRoute) -> None:
        self._circuits[route.connector_id] = _CircuitState()

    def _record_failure(self, route: ConnectorRoute) -> None:
        state = self._circuits.setdefault(route.connector_id, _CircuitState())
        state.failures += 1
        if (
            route.circuit_breaker_threshold > 0
            and state.failures >= route.circuit_breaker_threshold
        ):
            state.opened_at = self._monotonic()

    async def _emit(self, signal: DispatchSignal) -> None:
        try:
            await self._signal_sink.emit(signal)
        except Exception as exc:
            raise MonitoringUnavailable("sanitized dispatch signal persistence failed") from exc

    async def _emit_terminal(self, outcome: DeliveryOutcome) -> None:
        kind = (
            DispatchSignalKind.DELIVERY_EXHAUSTED
            if outcome.status is DeliveryStatus.EXHAUSTED
            else DispatchSignalKind.ATTEMPT_SUCCEEDED
        )
        await self._emit(
            DispatchSignal(
                kind=kind,
                dispatch_id=outcome.dispatch_id,
                workflow_id=outcome.workflow_id,
                channel=outcome.channel,
                provider_key=outcome.provider_key,
                attempt_count=outcome.attempt_count,
                failure_code=outcome.failure_code,
            )
        )
