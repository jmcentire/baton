"""Durable composition for delegated provider connector execution.

The runtime persists only opaque identifiers, sanitized outcomes, and
hash-chained operational evidence. Provider credential material remains behind
the single-purpose provider operation factory.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from baton.credential_custody import (
    AuthorizationConsumptionLedger,
    AuthorizedCredentialUse,
    ConsumptionReservation,
    ConsumptionReservationRequired,
    CredentialUseRequest,
    CredentialCustodyAuthorizer,
    CredentialCustodyInvokerFactory,
    CustodiedReferenceResolver,
    CustodyAuditEvent,
    CustodyAuditSink,
    CustodyAuthorizationDenied,
    CustodyFailureNotifier,
    ProviderCredentialHandle,
    SanitizedCustodyOutcome,
    VerifiedDelegatedAuthorization,
    VerifiedWorkloadAuthorization,
)
from baton.delegated_connector import (
    AuthorizationDenied,
    CapabilityReference,
    ConnectorRoute,
    Channel,
    DelegatedConnectorExecutor,
    DeliveryOutcome,
    DeliveryStatus,
    DispatchBinding,
    DispatchBindingConflict,
    DispatchClaim,
    DispatchJournal,
    DispatchRequest,
    DispatchSignal,
    DispatchSignalSink,
    DispatchStateUnavailable,
    ScopedAuthorizationVerifier,
)


_ZERO_HASH = "0" * 64


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("persisted timestamp must be timezone-aware")
    return parsed


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _iso(value)
    if is_dataclass(value):
        return _primitive(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_primitive(item) for item in value)
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(_primitive(value), sort_keys=True, separators=(",", ":"))


def _delivery_outcome_payload(outcome: DeliveryOutcome) -> dict[str, Any]:
    return _primitive(outcome)


def _delivery_outcome_from_payload(payload: str) -> DeliveryOutcome:
    data = json.loads(payload)
    return DeliveryOutcome(
        dispatch_id=data["dispatch_id"],
        workflow_id=data["workflow_id"],
        channel=Channel(data["channel"]),
        connector_id=data["connector_id"],
        provider_key=data["provider_key"],
        status=DeliveryStatus(data["status"]),
        attempt_count=data["attempt_count"],
        failover_used=data["failover_used"],
        audit_ref=data["audit_ref"],
        failure_code=data["failure_code"],
    )


@dataclass(frozen=True)
class DelegatedAuthorizationContext:
    """Exact runtime and trust-policy context supplied to a trusted verifier."""

    audience: str
    workload_id: str
    purpose: str
    issuer_policy_ref: str
    rotation_policy_ref: str

    def __post_init__(self) -> None:
        for name in (
            "audience",
            "workload_id",
            "purpose",
            "issuer_policy_ref",
            "rotation_policy_ref",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")


class DelegatedAuthorizationVerifier(Protocol):
    """Verify one delegated-provider authorization against exact runtime policy."""

    async def verify(
        self,
        capability: CapabilityReference,
        request: DispatchRequest,
        context: DelegatedAuthorizationContext,
    ) -> VerifiedDelegatedAuthorization:
        ...


@dataclass(frozen=True)
class _ContextBoundDelegatedAuthorizationVerifier:
    verifier: DelegatedAuthorizationVerifier
    context: DelegatedAuthorizationContext
    clock: Callable[[], datetime]

    async def verify(
        self,
        capability: CapabilityReference,
        request: DispatchRequest,
    ) -> VerifiedDelegatedAuthorization:
        outcome = await self.verifier.verify(capability, request, self.context)
        if not isinstance(outcome, VerifiedDelegatedAuthorization):
            raise AuthorizationDenied(
                "delegated verifier did not return the required shared authorization outcome"
            )
        if outcome.audience != self.context.audience:
            raise AuthorizationDenied("authorization audience is outside runtime scope")
        if outcome.principal != self.context.workload_id:
            raise AuthorizationDenied("authorization principal is outside runtime scope")
        if self.context.purpose not in outcome.allowed_purposes:
            raise AuthorizationDenied("authorization purpose is outside runtime scope")
        current_time = self.clock()
        if current_time < outcome.not_before or current_time >= outcome.not_after:
            raise AuthorizationDenied("authorization is outside its validity window")
        return outcome


@dataclass(frozen=True)
class ConfiguredVerifierBundle:
    """One verifier plus the exact externally managed trust-policy context."""

    verifier: DelegatedAuthorizationVerifier
    audience: str
    issuer_policy_ref: str
    rotation_policy_ref: str

    def __post_init__(self) -> None:
        for name in ("audience", "issuer_policy_ref", "rotation_policy_ref"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")

    def bind(
        self,
        *,
        workload_id: str,
        purpose: str,
        clock: Callable[[], datetime] | None = None,
    ) -> ScopedAuthorizationVerifier:
        """Bind trust policy and runtime scope before any dispatch admission."""

        return _ContextBoundDelegatedAuthorizationVerifier(
            self.verifier,
            DelegatedAuthorizationContext(
                audience=self.audience,
                workload_id=workload_id,
                purpose=purpose,
                issuer_policy_ref=self.issuer_policy_ref,
                rotation_policy_ref=self.rotation_policy_ref,
            ),
            clock or _utc_now,
        )


class SinglePurposeProviderOperation(Protocol):
    """Custody-internal operation prepared for one exact authorized use."""

    async def invoke(self) -> SanitizedCustodyOutcome:
        ...


class SinglePurposeProviderOperationFactory(Protocol):
    """Prepare one operation while keeping any resolved material internal."""

    async def prepare(
        self,
        handle: ProviderCredentialHandle,
        authorized_use: AuthorizedCredentialUse,
    ) -> SinglePurposeProviderOperation:
        ...


class SinglePurposeCustodiedResolver(CustodiedReferenceResolver):
    """Concrete resolver that exposes only a one-operation invocation object."""

    def __init__(self, operation_factory: SinglePurposeProviderOperationFactory):
        self._operation_factory = operation_factory

    async def invoke(
        self,
        handle: ProviderCredentialHandle,
        authorized_use: AuthorizedCredentialUse,
    ) -> SanitizedCustodyOutcome:
        operation = await self._operation_factory.prepare(handle, authorized_use)
        return await operation.invoke()


@dataclass(frozen=True)
class HashChainVerification:
    ok: bool
    event_count: int
    anchor: str
    broken_sequence: int | None = None


class SqliteDelegatedRuntimeState:
    """Single-node durable reference state for dispatch, custody, audit, and alerts."""

    def __init__(
        self,
        path: str | Path,
        *,
        claim_lease_seconds: int = 60,
        clock: Callable[[], datetime] | None = None,
    ):
        self.path = Path(path)
        if str(self.path) == ":memory:":
            raise ValueError("durable delegated runtime state cannot use :memory:")
        if claim_lease_seconds < 1:
            raise ValueError("claim_lease_seconds must be positive")
        self._claim_lease_seconds = claim_lease_seconds
        self._clock = clock or _utc_now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.journal = SqliteDispatchJournal(self)
        self.ledger = SqliteAuthorizationLedger(self)
        self.sink = SqliteOperationalSink(self)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS dispatch_journal (
                    idempotency_key TEXT PRIMARY KEY,
                    request_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('running', 'completed', 'aborted')),
                    claim_id TEXT,
                    lease_expires_at TEXT,
                    outcome_json TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS authorization_reservations (
                    authorization_id TEXT PRIMARY KEY,
                    reservation_id TEXT NOT NULL UNIQUE,
                    request_fingerprint TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    dispatch_id TEXT NOT NULL,
                    workload_id TEXT NOT NULL,
                    max_provider_attempts INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    outcome_json TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operational_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    stream TEXT NOT NULL,
                    event_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS failure_notifications (
                    notification_key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'acknowledged')),
                    created_at TEXT NOT NULL,
                    acknowledged_at TEXT
                );
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    async def verify_event_chain(self) -> HashChainVerification:
        return await asyncio.to_thread(self._verify_event_chain)

    def _verify_event_chain(self) -> HashChainVerification:
        previous_hash = _ZERO_HASH
        event_count = 0
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT sequence, stream, event_key, payload_json, previous_hash, event_hash
                FROM operational_events
                ORDER BY sequence
                """
            ).fetchall()
        for row in rows:
            event_count += 1
            expected = self._event_hash(
                row["stream"],
                row["event_key"],
                row["payload_json"],
                previous_hash,
            )
            if row["previous_hash"] != previous_hash or row["event_hash"] != expected:
                return HashChainVerification(
                    ok=False,
                    event_count=event_count,
                    anchor=previous_hash,
                    broken_sequence=row["sequence"],
                )
            previous_hash = row["event_hash"]
        return HashChainVerification(ok=True, event_count=event_count, anchor=previous_hash)

    async def pending_failure_notifications(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._pending_failure_notifications)

    def _pending_failure_notifications(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT notification_key, payload_json, created_at
                FROM failure_notifications
                WHERE status = 'pending'
                ORDER BY created_at, notification_key
                """
            ).fetchall()
        return [
            {
                "notification_key": row["notification_key"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def acknowledge_failure_notification(self, notification_key: str) -> bool:
        if not notification_key:
            raise ValueError("notification_key is required")
        return await asyncio.to_thread(
            self._acknowledge_failure_notification,
            notification_key,
        )

    def _acknowledge_failure_notification(self, notification_key: str) -> bool:
        with closing(self._connect()) as connection:
            result = connection.execute(
                """
                UPDATE failure_notifications
                SET status = 'acknowledged', acknowledged_at = ?
                WHERE notification_key = ? AND status = 'pending'
                """,
                (_iso(self._clock()), notification_key),
            )
        return result.rowcount == 1

    @staticmethod
    def _event_hash(stream: str, event_key: str, payload_json: str, previous_hash: str) -> str:
        canonical = _canonical_json(
            {
                "stream": stream,
                "event_key": event_key,
                "payload_json": payload_json,
                "previous_hash": previous_hash,
            }
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        stream: str,
        event_key: str,
        payload: Any,
    ) -> None:
        if connection.execute(
            "SELECT 1 FROM operational_events WHERE event_key = ?",
            (event_key,),
        ).fetchone():
            return
        row = connection.execute(
            "SELECT event_hash FROM operational_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = row["event_hash"] if row is not None else _ZERO_HASH
        payload_json = _canonical_json(payload)
        event_hash = self._event_hash(stream, event_key, payload_json, previous_hash)
        connection.execute(
            """
            INSERT INTO operational_events (
                stream, event_key, payload_json, previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                stream,
                event_key,
                payload_json,
                previous_hash,
                event_hash,
                _iso(self._clock()),
            ),
        )


class SqliteDispatchJournal(DispatchJournal):
    def __init__(self, state: SqliteDelegatedRuntimeState):
        self._state = state

    async def completed(self, binding: DispatchBinding) -> DeliveryOutcome | None:
        return await asyncio.to_thread(self._completed, binding)

    def _completed(self, binding: DispatchBinding) -> DeliveryOutcome | None:
        with closing(self._state._connect()) as connection:
            row = connection.execute(
                "SELECT request_fingerprint, state, outcome_json FROM dispatch_journal "
                "WHERE idempotency_key = ?",
                (binding.idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        self._assert_fingerprint(row["request_fingerprint"], binding)
        if row["state"] != "completed":
            return None
        if not row["outcome_json"]:
            raise DispatchStateUnavailable("completed dispatch is missing its outcome")
        return _delivery_outcome_from_payload(row["outcome_json"])

    async def begin(self, binding: DispatchBinding) -> DispatchClaim | None:
        return await asyncio.to_thread(self._begin, binding)

    def _begin(self, binding: DispatchBinding) -> DispatchClaim | None:
        now = self._state._clock()
        lease_expires_at = now + timedelta(seconds=self._state._claim_lease_seconds)
        claim = DispatchClaim(
            claim_id=str(uuid.uuid4()),
            binding=binding,
            lease_expires_at=lease_expires_at,
        )
        with closing(self._state._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT request_fingerprint, state, lease_expires_at
                    FROM dispatch_journal
                    WHERE idempotency_key = ?
                    """,
                    (binding.idempotency_key,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO dispatch_journal (
                            idempotency_key, request_fingerprint, state, claim_id,
                            lease_expires_at, updated_at
                        ) VALUES (?, ?, 'running', ?, ?, ?)
                        """,
                        (
                            binding.idempotency_key,
                            binding.request_fingerprint,
                            claim.claim_id,
                            _iso(claim.lease_expires_at),
                            _iso(now),
                        ),
                    )
                    connection.commit()
                    return claim

                self._assert_fingerprint(row["request_fingerprint"], binding)
                if row["state"] == "completed":
                    connection.commit()
                    return None
                if (
                    row["state"] == "running"
                    and row["lease_expires_at"]
                    and _parse_time(row["lease_expires_at"]) > now
                ):
                    connection.commit()
                    return None
                connection.execute(
                    """
                    UPDATE dispatch_journal
                    SET state = 'running', claim_id = ?, lease_expires_at = ?,
                        outcome_json = NULL, updated_at = ?
                    WHERE idempotency_key = ?
                    """,
                    (
                        claim.claim_id,
                        _iso(claim.lease_expires_at),
                        _iso(now),
                        binding.idempotency_key,
                    ),
                )
                connection.commit()
                return claim
            except Exception:
                connection.rollback()
                raise

    async def complete(self, claim: DispatchClaim, outcome: DeliveryOutcome) -> None:
        await asyncio.to_thread(self._complete, claim, outcome)

    async def renew(self, claim: DispatchClaim) -> None:
        await asyncio.to_thread(self._renew, claim)

    def _renew(self, claim: DispatchClaim) -> None:
        now = self._state._clock()
        lease_expires_at = now + timedelta(seconds=self._state._claim_lease_seconds)
        with closing(self._state._connect()) as connection:
            result = connection.execute(
                """
                UPDATE dispatch_journal
                SET lease_expires_at = ?, updated_at = ?
                WHERE idempotency_key = ? AND request_fingerprint = ?
                  AND state = 'running' AND claim_id = ? AND lease_expires_at > ?
                """,
                (
                    _iso(lease_expires_at),
                    _iso(now),
                    claim.binding.idempotency_key,
                    claim.binding.request_fingerprint,
                    claim.claim_id,
                    _iso(now),
                ),
            )
        if result.rowcount != 1:
            raise DispatchStateUnavailable("dispatch claim is no longer active")

    def _complete(self, claim: DispatchClaim, outcome: DeliveryOutcome) -> None:
        now = self._state._clock()
        with closing(self._state._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT request_fingerprint, state, claim_id, lease_expires_at
                    FROM dispatch_journal
                    WHERE idempotency_key = ?
                    """,
                    (claim.binding.idempotency_key,),
                ).fetchone()
                if row is None:
                    raise DispatchStateUnavailable("dispatch claim is missing")
                self._assert_fingerprint(row["request_fingerprint"], claim.binding)
                if (
                    row["state"] != "running"
                    or row["claim_id"] != claim.claim_id
                    or not row["lease_expires_at"]
                    or _parse_time(row["lease_expires_at"]) <= now
                ):
                    raise DispatchStateUnavailable("dispatch claim is no longer active")
                connection.execute(
                    """
                    UPDATE dispatch_journal
                    SET state = 'completed', claim_id = NULL, lease_expires_at = NULL,
                        outcome_json = ?, updated_at = ?
                    WHERE idempotency_key = ?
                    """,
                    (
                        _canonical_json(_delivery_outcome_payload(outcome)),
                        _iso(now),
                        claim.binding.idempotency_key,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    async def abort(self, claim: DispatchClaim) -> None:
        await asyncio.to_thread(self._abort, claim)

    def _abort(self, claim: DispatchClaim) -> None:
        with closing(self._state._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT request_fingerprint, state, claim_id
                    FROM dispatch_journal
                    WHERE idempotency_key = ?
                    """,
                    (claim.binding.idempotency_key,),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return
                self._assert_fingerprint(row["request_fingerprint"], claim.binding)
                if row["state"] == "running" and row["claim_id"] == claim.claim_id:
                    connection.execute(
                        """
                        UPDATE dispatch_journal
                        SET state = 'aborted', claim_id = NULL, lease_expires_at = NULL,
                            updated_at = ?
                        WHERE idempotency_key = ?
                        """,
                        (_iso(self._state._clock()), claim.binding.idempotency_key),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _assert_fingerprint(persisted: str, binding: DispatchBinding) -> None:
        if persisted != binding.request_fingerprint:
            raise DispatchBindingConflict("idempotency key is bound to another request")


class SqliteAuthorizationLedger(AuthorizationConsumptionLedger):
    def __init__(self, state: SqliteDelegatedRuntimeState):
        self._state = state

    async def reserve_once(
        self,
        authorization: VerifiedWorkloadAuthorization,
        request: CredentialUseRequest,
    ) -> ConsumptionReservation:
        return await asyncio.to_thread(self._reserve_once, authorization, request)

    def _reserve_once(
        self,
        authorization: VerifiedWorkloadAuthorization,
        request: CredentialUseRequest,
    ) -> ConsumptionReservation:
        with closing(self._state._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                dispatch = connection.execute(
                    """
                    SELECT request_fingerprint, state, claim_id, lease_expires_at
                    FROM dispatch_journal
                    WHERE idempotency_key = ?
                    """,
                    (request.idempotency_key,),
                ).fetchone()
                if (
                    dispatch is None
                    or dispatch["request_fingerprint"] != request.request_fingerprint
                    or dispatch["state"] != "running"
                    or dispatch["claim_id"] != request.dispatch_claim_id
                    or not dispatch["lease_expires_at"]
                    or _parse_time(dispatch["lease_expires_at"]) <= self._state._clock()
                ):
                    raise ConsumptionReservationRequired(
                        "active exact dispatch journal claim is required"
                    )

                row = connection.execute(
                    """
                    SELECT reservation_id, request_fingerprint, idempotency_key,
                           dispatch_id, workload_id, max_provider_attempts
                    FROM authorization_reservations
                    WHERE authorization_id = ?
                    """,
                    (authorization.authorization_id,),
                ).fetchone()
                if row is not None:
                    if (
                        row["request_fingerprint"] != request.request_fingerprint
                        or row["idempotency_key"] != request.idempotency_key
                        or row["dispatch_id"] != request.dispatch_id
                        or row["workload_id"] != request.workload_id
                        or row["max_provider_attempts"] != authorization.max_provider_attempts
                    ):
                        raise CustodyAuthorizationDenied(
                            "authorization is already reserved for another dispatch"
                        )
                    connection.commit()
                    return ConsumptionReservation(
                        reservation_id=row["reservation_id"],
                        authorization_id=authorization.authorization_id,
                        request_fingerprint=request.request_fingerprint,
                        idempotency_key=request.idempotency_key,
                    )

                reservation = ConsumptionReservation(
                    reservation_id=str(uuid.uuid4()),
                    authorization_id=authorization.authorization_id,
                    request_fingerprint=request.request_fingerprint,
                    idempotency_key=request.idempotency_key,
                )
                connection.execute(
                    """
                    INSERT INTO authorization_reservations (
                        authorization_id, reservation_id, request_fingerprint,
                        idempotency_key, dispatch_id, workload_id,
                        max_provider_attempts, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        authorization.authorization_id,
                        reservation.reservation_id,
                        request.request_fingerprint,
                        request.idempotency_key,
                        request.dispatch_id,
                        request.workload_id,
                        authorization.max_provider_attempts,
                        _iso(self._state._clock()),
                    ),
                )
                connection.commit()
                return reservation
            except Exception:
                connection.rollback()
                raise

    async def complete(
        self,
        reservation: ConsumptionReservation,
        outcome: SanitizedCustodyOutcome,
    ) -> None:
        await asyncio.to_thread(self._complete, reservation, outcome)

    def _complete(
        self,
        reservation: ConsumptionReservation,
        outcome: SanitizedCustodyOutcome,
    ) -> None:
        with closing(self._state._connect()) as connection:
            result = connection.execute(
                """
                UPDATE authorization_reservations
                SET outcome_json = ?, updated_at = ?
                WHERE authorization_id = ? AND reservation_id = ?
                  AND request_fingerprint = ? AND idempotency_key = ?
                  AND dispatch_id = ?
                """,
                (
                    _canonical_json(outcome),
                    _iso(self._state._clock()),
                    reservation.authorization_id,
                    reservation.reservation_id,
                    reservation.request_fingerprint,
                    reservation.idempotency_key,
                    outcome.dispatch_id,
                ),
            )
        if result.rowcount != 1:
            raise ConsumptionReservationRequired("authorization reservation is missing")

    async def reserve_attempt(
        self,
        reservation: ConsumptionReservation,
        authorized_use: AuthorizedCredentialUse,
    ) -> int:
        return await asyncio.to_thread(self._reserve_attempt, reservation, authorized_use)

    def _reserve_attempt(
        self,
        reservation: ConsumptionReservation,
        authorized_use: AuthorizedCredentialUse,
    ) -> int:
        if (
            authorized_use.authorization_id != reservation.authorization_id
            or authorized_use.reservation_id != reservation.reservation_id
            or authorized_use.request_fingerprint != reservation.request_fingerprint
            or authorized_use.idempotency_key != reservation.idempotency_key
        ):
            raise ConsumptionReservationRequired(
                "authorized use does not bind the authorization reservation"
            )
        with closing(self._state._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                dispatch = connection.execute(
                    """
                    SELECT request_fingerprint, state, claim_id, lease_expires_at
                    FROM dispatch_journal
                    WHERE idempotency_key = ?
                    """,
                    (authorized_use.idempotency_key,),
                ).fetchone()
                if (
                    dispatch is None
                    or dispatch["request_fingerprint"] != authorized_use.request_fingerprint
                    or dispatch["state"] != "running"
                    or dispatch["claim_id"] != authorized_use.dispatch_claim_id
                    or not dispatch["lease_expires_at"]
                    or _parse_time(dispatch["lease_expires_at"]) <= self._state._clock()
                ):
                    raise ConsumptionReservationRequired(
                        "active exact dispatch journal claim is required for provider attempt"
                    )
                row = connection.execute(
                    """
                    SELECT attempt_count, max_provider_attempts
                    FROM authorization_reservations
                    WHERE authorization_id = ? AND reservation_id = ?
                      AND request_fingerprint = ? AND idempotency_key = ?
                      AND dispatch_id = ?
                    """,
                    (
                        reservation.authorization_id,
                        reservation.reservation_id,
                        reservation.request_fingerprint,
                        reservation.idempotency_key,
                        authorized_use.dispatch_id,
                    ),
                ).fetchone()
                if row is None:
                    raise ConsumptionReservationRequired("authorization reservation is missing")
                if row["attempt_count"] >= row["max_provider_attempts"]:
                    raise CustodyAuthorizationDenied("provider attempt budget is exhausted")
                attempt_count = row["attempt_count"] + 1
                connection.execute(
                    """
                    UPDATE authorization_reservations
                    SET attempt_count = ?, updated_at = ?
                    WHERE authorization_id = ?
                    """,
                    (
                        attempt_count,
                        _iso(self._state._clock()),
                        reservation.authorization_id,
                    ),
                )
                connection.commit()
                return attempt_count
            except Exception:
                connection.rollback()
                raise


class SqliteOperationalSink(DispatchSignalSink, CustodyAuditSink, CustodyFailureNotifier):
    def __init__(self, state: SqliteDelegatedRuntimeState):
        self._state = state

    async def emit(self, event: DispatchSignal | CustodyAuditEvent) -> None:
        await asyncio.to_thread(self._emit, event)

    def _emit(self, event: DispatchSignal | CustodyAuditEvent) -> None:
        stream, event_key = self._identity(event)
        with closing(self._state._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._state._append_event(
                    connection,
                    stream=stream,
                    event_key=event_key,
                    payload=event,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    async def notify(self, event: CustodyAuditEvent) -> None:
        await asyncio.to_thread(self._notify, event)

    def _notify(self, event: CustodyAuditEvent) -> None:
        _, base_key = self._identity(event)
        notification_key = f"failure:{base_key}"
        payload_json = _canonical_json(event)
        with closing(self._state._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO failure_notifications (
                        notification_key, payload_json, status, created_at
                    ) VALUES (?, ?, 'pending', ?)
                    """,
                    (notification_key, payload_json, _iso(self._state._clock())),
                )
                self._state._append_event(
                    connection,
                    stream="failure_notification",
                    event_key=notification_key,
                    payload=event,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _identity(event: DispatchSignal | CustodyAuditEvent) -> tuple[str, str]:
        if isinstance(event, DispatchSignal):
            return (
                "dispatch_signal",
                (
                    f"dispatch:{event.kind.value}:{event.dispatch_id}:"
                    f"{event.connector_id}:{event.attempt_count}"
                ),
            )
        if isinstance(event, CustodyAuditEvent):
            return (
                "custody_audit",
                (
                    f"custody:{event.kind.value}:{event.dispatch_id}:"
                    f"{event.connector_id}:{event.authorization_id}:{event.failure_code}"
                ),
            )
        raise TypeError("unsupported operational event")


@dataclass(frozen=True)
class DelegatedRuntimeComponents:
    """Explicit durable components required to compose a delegated runtime."""

    journal: DispatchJournal
    ledger: AuthorizationConsumptionLedger
    signal_sink: DispatchSignalSink
    audit_sink: CustodyAuditSink
    failure_notifier: CustodyFailureNotifier
    claim_lease_seconds: int

    def __post_init__(self) -> None:
        if any(
            component is None
            for component in (
                self.journal,
                self.ledger,
                self.signal_sink,
                self.audit_sink,
                self.failure_notifier,
            )
        ):
            raise ValueError("all delegated runtime components are required")
        if self.claim_lease_seconds < 1:
            raise ValueError("claim_lease_seconds must be positive")


@dataclass(frozen=True)
class DelegatedConnectorRuntime:
    """Composed delegated connector runtime with explicit durable controls."""

    executor: DelegatedConnectorExecutor
    verifier_policy: ConfiguredVerifierBundle
    reference_state: SqliteDelegatedRuntimeState | None = None

    @classmethod
    def compose(
        cls,
        *,
        routes: Sequence[ConnectorRoute],
        handles: Mapping[str, ProviderCredentialHandle],
        verifiers: ConfiguredVerifierBundle,
        operation_factory: SinglePurposeProviderOperationFactory,
        components: DelegatedRuntimeComponents,
        workload_id: str,
        purpose: str,
        clock: Callable[[], datetime] | None = None,
    ) -> DelegatedConnectorRuntime:
        if not workload_id or not purpose:
            raise ValueError("workload_id and purpose are required")
        enabled_routes = [route for route in routes if route.enabled]
        if enabled_routes and components.claim_lease_seconds * 1000 <= max(
            route.timeout_ms for route in enabled_routes
        ):
            raise ValueError("claim lease must exceed every provider attempt timeout")
        for route in enabled_routes:
            handle = handles.get(route.connector_id)
            if (
                handle is None
                or handle.handle_id != route.credential_handle
                or handle.provider_key != route.provider_key
                or handle.channel.value != route.channel.value
            ):
                raise ValueError(f"missing exact custody handle for route {route.connector_id}")

        authorizer = CredentialCustodyAuthorizer.for_verified_outcomes(
            components.ledger,
            audit_sink=components.audit_sink,
            failure_notifier=components.failure_notifier,
            clock=clock,
        )
        invoker_factory = CredentialCustodyInvokerFactory(
            authorizer,
            SinglePurposeCustodiedResolver(operation_factory),
            handles,
            workload_id=workload_id,
            purpose=purpose,
        )
        executor = DelegatedConnectorExecutor(
            routes,
            verifiers.bind(workload_id=workload_id, purpose=purpose, clock=clock),
            invoker_factory,
            components.journal,
            components.signal_sink,
            clock=clock,
        )
        return cls(executor=executor, verifier_policy=verifiers)

    @classmethod
    def build_sqlite_reference(
        cls,
        *,
        routes: Sequence[ConnectorRoute],
        handles: Mapping[str, ProviderCredentialHandle],
        verifiers: ConfiguredVerifierBundle,
        operation_factory: SinglePurposeProviderOperationFactory,
        state_path: str | Path,
        workload_id: str,
        purpose: str,
        claim_lease_seconds: int = 60,
        clock: Callable[[], datetime] | None = None,
    ) -> DelegatedConnectorRuntime:
        """Build the single-node SQLite reference, not a multi-replica backend."""

        state = SqliteDelegatedRuntimeState(
            state_path,
            claim_lease_seconds=claim_lease_seconds,
            clock=clock,
        )
        runtime = cls.compose(
            routes=routes,
            handles=handles,
            verifiers=verifiers,
            operation_factory=operation_factory,
            components=DelegatedRuntimeComponents(
                journal=state.journal,
                ledger=state.ledger,
                signal_sink=state.sink,
                audit_sink=state.sink,
                failure_notifier=state.sink,
                claim_lease_seconds=claim_lease_seconds,
            ),
            workload_id=workload_id,
            purpose=purpose,
            clock=clock,
        )
        return cls(
            executor=runtime.executor,
            verifier_policy=runtime.verifier_policy,
            reference_state=state,
        )
