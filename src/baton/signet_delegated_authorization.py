"""Key-free adapter from a trusted Signet verifier outcome into Baton scope."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from baton.credential_custody import VerifiedDelegatedAuthorization
from baton.delegated_connector import (
    AuthorizationDenied,
    CapabilityReference,
    Channel,
    DispatchRequest,
)
from baton.delegated_runtime import DelegatedAuthorizationContext


@dataclass(frozen=True)
class SignetDelegatedProviderVerificationContext:
    """Exact context sent to a trusted Signet delegated-provider verifier."""

    issuer: str
    audience: str
    workload_id: str
    channel: str
    available_connector_ids: tuple[str, ...]
    purpose: str
    request_fingerprint: str
    issuer_policy_ref: str
    rotation_policy_ref: str


@dataclass(frozen=True)
class VerifiedSignetDelegatedProviderAuthorization:
    """Wire-shaped result returned only after trusted Signet verification."""

    authorization_id: str
    issuer: str
    audience: str
    workload_id: str
    issued_at: str
    not_before: str
    not_after: str
    channel: str
    allowed_connector_ids: tuple[str, ...]
    allowed_purposes: tuple[str, ...]
    request_fingerprint: str
    max_uses: int
    max_provider_attempts: int
    issuer_policy_ref: str
    rotation_policy_ref: str


class TrustedSignetDelegatedProviderClient(Protocol):
    """Trusted transport that verifies a Signet envelope before returning scope."""

    async def verify(
        self,
        reference: str,
        context: SignetDelegatedProviderVerificationContext,
    ) -> VerifiedSignetDelegatedProviderAuthorization:
        ...


class SignetDelegatedAuthorizationAdapter:
    """Map one trusted Signet result into Baton's shared verified outcome."""

    def __init__(
        self,
        client: TrustedSignetDelegatedProviderClient,
        *,
        issuer: str,
        clock: Callable[[], datetime] | None = None,
    ):
        if not issuer:
            raise ValueError("issuer is required")
        self._client = client
        self._issuer = issuer
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def verify(
        self,
        capability: CapabilityReference,
        request: DispatchRequest,
        context: DelegatedAuthorizationContext,
    ) -> VerifiedDelegatedAuthorization:
        signet_context = SignetDelegatedProviderVerificationContext(
            issuer=self._issuer,
            audience=context.audience,
            workload_id=context.workload_id,
            channel=request.channel.value,
            available_connector_ids=tuple(sorted(context.available_connector_ids)),
            purpose=context.purpose,
            request_fingerprint=request.request_fingerprint,
            issuer_policy_ref=context.issuer_policy_ref,
            rotation_policy_ref=context.rotation_policy_ref,
        )
        outcome = await self._client.verify(capability.reference, signet_context)
        return self._map_verified_outcome(outcome, signet_context)

    def _map_verified_outcome(
        self,
        outcome: VerifiedSignetDelegatedProviderAuthorization,
        context: SignetDelegatedProviderVerificationContext,
    ) -> VerifiedDelegatedAuthorization:
        self._validate_exact_context(outcome, context)
        issued_at = _parse_time(outcome.issued_at, "issued_at")
        not_before = _parse_time(outcome.not_before, "not_before")
        not_after = _parse_time(outcome.not_after, "not_after")
        current_time = self._clock()
        if current_time.tzinfo is None:
            raise AuthorizationDenied("Signet adapter clock must be timezone-aware")
        if issued_at > current_time:
            raise AuthorizationDenied("Signet authorization was issued in the future")
        if not_before < issued_at or not_after <= not_before:
            raise AuthorizationDenied("Signet authorization has an inconsistent time window")
        if current_time < not_before or current_time >= not_after:
            raise AuthorizationDenied("Signet authorization is outside its validity window")

        try:
            channel = Channel(outcome.channel)
            return VerifiedDelegatedAuthorization(
                principal=outcome.workload_id,
                channel=channel,
                allowed_connectors=frozenset(outcome.allowed_connector_ids),
                not_after=not_after,
                max_attempts=outcome.max_provider_attempts,
                request_fingerprint=outcome.request_fingerprint,
                authorization_id=outcome.authorization_id,
                issuer=outcome.issuer,
                audience=outcome.audience,
                issuer_policy_ref=outcome.issuer_policy_ref,
                rotation_policy_ref=outcome.rotation_policy_ref,
                allowed_purposes=frozenset(outcome.allowed_purposes),
                not_before=not_before,
                max_uses=outcome.max_uses,
            )
        except (TypeError, ValueError) as exc:
            raise AuthorizationDenied("Signet authorization outcome is invalid") from exc

    @staticmethod
    def _validate_exact_context(
        outcome: VerifiedSignetDelegatedProviderAuthorization,
        context: SignetDelegatedProviderVerificationContext,
    ) -> None:
        for name in (
            "authorization_id",
            "issuer",
            "audience",
            "workload_id",
            "issued_at",
            "not_before",
            "not_after",
            "channel",
            "request_fingerprint",
            "issuer_policy_ref",
            "rotation_policy_ref",
        ):
            if not getattr(outcome, name):
                raise AuthorizationDenied(f"Signet authorization is missing {name}")
        if outcome.issuer != context.issuer:
            raise AuthorizationDenied("Signet authorization issuer is outside configured scope")
        if outcome.audience != context.audience:
            raise AuthorizationDenied("Signet authorization audience is outside configured scope")
        if outcome.workload_id != context.workload_id:
            raise AuthorizationDenied("Signet authorization workload is outside configured scope")
        if outcome.channel != context.channel:
            raise AuthorizationDenied("Signet authorization channel is outside configured scope")
        if outcome.request_fingerprint != context.request_fingerprint:
            raise AuthorizationDenied("Signet authorization fingerprint is outside configured scope")
        if outcome.issuer_policy_ref != context.issuer_policy_ref:
            raise AuthorizationDenied("Signet issuer policy is outside configured scope")
        if outcome.rotation_policy_ref != context.rotation_policy_ref:
            raise AuthorizationDenied("Signet rotation policy is outside configured scope")
        if outcome.max_uses != 1:
            raise AuthorizationDenied("Signet authorization must be single-use")
        if outcome.max_provider_attempts < 1:
            raise AuthorizationDenied("Signet provider-attempt budget must be positive")
        if not outcome.allowed_connector_ids or len(set(outcome.allowed_connector_ids)) != len(
            outcome.allowed_connector_ids
        ):
            raise AuthorizationDenied("Signet connector scope is empty or contains duplicates")
        if not outcome.allowed_purposes or len(set(outcome.allowed_purposes)) != len(
            outcome.allowed_purposes
        ):
            raise AuthorizationDenied("Signet purpose scope is empty or contains duplicates")
        if not set(outcome.allowed_connector_ids).issubset(context.available_connector_ids):
            raise AuthorizationDenied("Signet connector scope exceeds runtime policy")
        if set(outcome.allowed_purposes) != {context.purpose}:
            raise AuthorizationDenied("Signet purpose scope does not exactly match runtime policy")


def _parse_time(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AuthorizationDenied(f"Signet authorization has invalid {name}") from exc
    if parsed.tzinfo is None:
        raise AuthorizationDenied(f"Signet authorization {name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)
