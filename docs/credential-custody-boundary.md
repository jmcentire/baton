# Provider Credential Custody Boundary

## Purpose

Baton owns the cloud-neutral egress control boundary for provider-backed
operations. A business workflow may select a connector and provide opaque
recipient and payload references, but it must never receive or invoke with an email,
telephony, or other external-provider credential value.

`src/baton/credential_custody.py` defines the reusable boundary:

- `ProviderCredentialHandle` is an administrator-configured opaque handle,
  not a secret-store URI or credential value.
- `SignedWorkloadAuthorizationVerifier` converts a signed authorization
  reference into a verified, credential-free outcome.
- `CredentialCustodyAuthorizer` obtains a trusted verifier outcome and
  `authorize_provider_dispatch` binds it to the exact workload, initial
  connector handle, channel, purpose, opaque recipient and payload references,
  request fingerprint, and provider-attempt budget before consuming the
  reservation.
- `AuthorizationConsumptionLedger` is required for every provider operation and
  is invoked inside authorization to atomically bind authorization, request
  fingerprint, and idempotency key.
- `CustodiedReferenceResolver` is the only permitted provider-operation
  boundary. It resolves material internally and returns a sanitized outcome.
- `CredentialCustodyInvokerFactory` is the adapter required by
  `DelegatedConnectorExecutor`: after dispatch idempotency begins and only
  immediately before an actual provider attempt, it validates route-to-handle
  bindings and the complete configured failover scope, consumes one
  authorization reservation, and returns an invoker that can call only
  `CustodiedReferenceResolver`.
- The resulting `AuthorizedProviderDispatch` carries one ledger reservation
  across primary and backup attempts, but can select only connector handles
  already included in its verified scope and is bounded by its verified
  provider-attempt budget.

## Failure Semantics

- Missing, expired, mismatched, or out-of-scope authority is denied before any
  provider operation.
- Only single-dispatch authority with an exact durable ledger reservation is
  accepted. This prevents a provider send from accepting reusable authority or
  a `one_time` claim without replay enforcement.
- Sanitized outcomes carry provider identity, status, correlation identifiers,
  audit reference, and bounded failure code only. They do not carry material,
  provider response bodies, recipient data, or message data.
- Delegated terminal outcomes carry connector identity as well as provider
  identity, so audits and failure notifications can identify the configured
  connector without revealing custody material.

## Integration Gate

These modules are a connected contract surface, not a configured production
custody store. The delegated executor no longer accepts a direct provider
invoker; production construction must supply `CredentialCustodyInvokerFactory`
or an equivalently audited custody implementation. Its protocol seam exists
for testing and alternate approved backends, so deployment wiring remains an
enforcement gate.
MEA integration remains blocked until all of the following exist:

1. A trusted Signet-compatible verifier implementation with issuer and rotation
   policy.
2. A durable consumption ledger and dispatch journal with defined atomic
   reserve/complete/replay and crash-recovery behavior.
3. A custody-internal resolver implementation, potentially backed by OpenBao
   after license, deployment, assurance, and operational review.
4. Tamper-evident audit and failure notification sink implementations.
5. Key-free executable evidence for each boundary and the provider executor.

No provider credential values or signing keys are used or packaged by this
contract or its tests.

## OpenBao Candidate Evidence

OpenBao is a candidate implementation backend for the internal resolver, not
an adopted dependency in this change. Official project documentation checked
on 2026-06-04 records:

- Source licensing as MPL-2.0 with OSI and FSF recognition:
  <https://openbao.org/docs/policies/osps-baseline/>
- Versioned arbitrary secret storage and ACL separation through KV v2:
  <https://openbao.org/docs/secrets/kv/kv-v2/>
- Cryptographic processing without retaining submitted data through Transit:
  <https://openbao.org/docs/secrets/transit/>
- Request audit-device behavior:
  <https://openbao.org/docs/audit/>
- JWT/OIDC authentication capability:
  <https://openbao.org/docs/auth/jwt/>

These documents establish candidate fit and commercial open-source eligibility;
they do not establish certification, deployment security, high availability,
unseal policy, vulnerability disposition, or approval for MEA production use.
