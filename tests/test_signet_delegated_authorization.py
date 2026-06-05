"""Key-free contract checks for the trusted Signet-to-Baton adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from baton.delegated_connector import (
    AuthorizationDenied,
    CapabilityReference,
    Channel,
    DispatchRequest,
    dispatch_request_fingerprint,
)
from baton.delegated_runtime import DelegatedAuthorizationContext
from baton.signet_delegated_authorization import (
    SignetDelegatedAuthorizationAdapter,
    SignetDelegatedProviderVerificationContext,
    VerifiedSignetDelegatedProviderAuthorization,
)


NOW = datetime(2026, 6, 4, 22, 5, tzinfo=timezone.utc)
FINGERPRINT = dispatch_request_fingerprint(
    dispatch_id="dispatch-1",
    workflow_id="operation-1",
    channel=Channel.SMS,
    recipient_ref="recipient-ref-1",
    payload_ref="payload-ref-1",
    idempotency_key="dispatch-once-1",
)


def _request() -> DispatchRequest:
    return DispatchRequest(
        dispatch_id="dispatch-1",
        workflow_id="operation-1",
        channel=Channel.SMS,
        recipient_ref="recipient-ref-1",
        payload_ref="payload-ref-1",
        idempotency_key="dispatch-once-1",
        request_fingerprint=FINGERPRINT,
    )


def _runtime_context() -> DelegatedAuthorizationContext:
    return DelegatedAuthorizationContext(
        audience="baton://delegated-provider-executor",
        workload_id="mea-comms",
        purpose="case_notification",
        available_connector_ids=frozenset({"sms-primary", "sms-backup"}),
        issuer_policy_ref="signet://issuer-policy/mea-comms",
        rotation_policy_ref="signet://rotation-policy/mea-comms",
    )


def _outcome() -> VerifiedSignetDelegatedProviderAuthorization:
    return VerifiedSignetDelegatedProviderAuthorization(
        authorization_id="authorization-1",
        issuer="signet://issuer/mea",
        audience="baton://delegated-provider-executor",
        workload_id="mea-comms",
        issued_at=(NOW - timedelta(minutes=5)).isoformat(),
        not_before=(NOW - timedelta(minutes=4)).isoformat(),
        not_after=(NOW + timedelta(minutes=5)).isoformat(),
        channel="sms",
        allowed_connector_ids=("sms-primary", "sms-backup"),
        allowed_purposes=("case_notification",),
        request_fingerprint=FINGERPRINT,
        max_uses=1,
        max_provider_attempts=2,
        issuer_policy_ref="signet://issuer-policy/mea-comms",
        rotation_policy_ref="signet://rotation-policy/mea-comms",
    )


class StaticSignetClient:
    def __init__(self, outcome: VerifiedSignetDelegatedProviderAuthorization):
        self.outcome = outcome
        self.calls: list[tuple[str, SignetDelegatedProviderVerificationContext]] = []

    async def verify(
        self,
        reference: str,
        context: SignetDelegatedProviderVerificationContext,
    ) -> VerifiedSignetDelegatedProviderAuthorization:
        self.calls.append((reference, context))
        return self.outcome


def _adapter(client: StaticSignetClient) -> SignetDelegatedAuthorizationAdapter:
    return SignetDelegatedAuthorizationAdapter(
        client,
        issuer="signet://issuer/mea",
        clock=lambda: NOW,
    )


async def test_maps_one_trusted_signet_outcome_into_shared_baton_authorization():
    client = StaticSignetClient(_outcome())
    adapter = _adapter(client)

    verified = await adapter.verify(
        CapabilityReference("opaque-signet-authorization-ref"),
        _request(),
        _runtime_context(),
    )

    assert verified.authorization_id == "authorization-1"
    assert verified.principal == "mea-comms"
    assert verified.channel is Channel.SMS
    assert verified.allowed_connectors == frozenset({"sms-primary", "sms-backup"})
    assert verified.allowed_purposes == frozenset({"case_notification"})
    assert verified.max_uses == 1
    assert verified.max_attempts == 2
    assert verified.issuer_policy_ref == "signet://issuer-policy/mea-comms"
    assert verified.rotation_policy_ref == "signet://rotation-policy/mea-comms"
    assert client.calls == [
        (
            "opaque-signet-authorization-ref",
            SignetDelegatedProviderVerificationContext(
                issuer="signet://issuer/mea",
                audience="baton://delegated-provider-executor",
                workload_id="mea-comms",
                channel="sms",
                available_connector_ids=("sms-backup", "sms-primary"),
                purpose="case_notification",
                request_fingerprint=FINGERPRINT,
                issuer_policy_ref="signet://issuer-policy/mea-comms",
                rotation_policy_ref="signet://rotation-policy/mea-comms",
            ),
        )
    ]


@pytest.mark.parametrize(
    "replacements",
    [
        {"issuer": "signet://issuer/other"},
        {"audience": "baton://other-executor"},
        {"workload_id": "other-workload"},
        {"channel": "email"},
        {"request_fingerprint": "b" * 64},
        {"issuer_policy_ref": "signet://issuer-policy/other"},
        {"rotation_policy_ref": "signet://rotation-policy/other"},
        {"max_uses": 2},
        {"max_provider_attempts": 0},
        {"allowed_connector_ids": ("sms-primary", "sms-unapproved")},
        {"allowed_connector_ids": ("sms-primary", "sms-primary")},
        {"allowed_purposes": ("other_purpose",)},
        {"allowed_purposes": ("case_notification", "other_purpose")},
        {"allowed_purposes": ("case_notification", "case_notification")},
        {"issued_at": (NOW + timedelta(minutes=1)).isoformat()},
        {"not_before": (NOW + timedelta(minutes=1)).isoformat()},
        {"not_after": NOW.isoformat()},
        {"not_after": "not-a-time"},
    ],
)
async def test_rejects_rebound_or_invalid_signet_outcome(replacements):
    adapter = _adapter(StaticSignetClient(replace(_outcome(), **replacements)))

    with pytest.raises(AuthorizationDenied):
        await adapter.verify(
            CapabilityReference("opaque-signet-authorization-ref"),
            _request(),
            _runtime_context(),
        )


async def test_accepts_signet_scope_narrower_than_runtime_connector_ceiling():
    client = StaticSignetClient(replace(_outcome(), allowed_connector_ids=("sms-primary",)))
    adapter = _adapter(client)

    verified = await adapter.verify(
        CapabilityReference("opaque-signet-authorization-ref"),
        _request(),
        _runtime_context(),
    )

    assert verified.allowed_connectors == frozenset({"sms-primary"})
