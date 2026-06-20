# Provider Credential Custody Boundary

## Purpose

Baton owns the cloud-neutral egress control boundary for provider-backed
operations. A business workflow may select a connector and provide opaque
recipient and payload references, but it must never receive or invoke with an email,
telephony, or other external-provider credential value.

`src/baton/credential_custody.py` defines the reusable boundary:

- `ProviderCredentialHandle` is an administrator-configured opaque handle,
  not a secret-store URI or credential value.
- `SignedWorkloadAuthorizationVerifier` supports standalone custody consumers.
  The composed delegated runtime does not invoke it after dispatch admission.
- `CredentialCustodyAuthorizer` either obtains a standalone trusted verifier
  outcome or accepts the composed runtime's already verified shared outcome.
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
- Every custody request and provider-attempt reservation is bound to the exact
  active dispatch claim. An expired or reclaimed claim cannot reserve authority,
  invoke a provider, renew itself, or complete the dispatch.

## Runtime Composition

`src/baton/delegated_runtime.py` supplies the reusable composition boundary:

- `DelegatedRuntimeComponents` requires an explicit durable dispatch journal,
  authorization ledger, dispatch signal sink, custody audit sink, failure
  notifier, and the journal's real claim-lease duration.
- `DelegatedConnectorRuntime.compose` validates route-to-handle bindings and
  requires the claim lease to exceed every bounded provider-attempt timeout
  before constructing an executor.
- `SinglePurposeProviderOperationFactory` is the only operation factory used by
  the concrete resolver. Provider material may exist inside its prepared
  operation, but no Baton request, authorization, outcome, event, or runtime
  state type contains that material.
- `ConfiguredVerifierBundle` supplies one verifier with the exact audience,
  workload, purpose, per-channel available-connector ceiling, issuer-policy
  reference, and rotation-policy reference before dispatch admission. The
  verifier must return one
  `VerifiedDelegatedAuthorization`; Baton derives both dispatch and custody
  views from that same immutable outcome.
- `SignetDelegatedAuthorizationAdapter` sends the exact runtime context to a
  trusted Signet delegated-provider verifier client, requires its verified
  policy metadata to match, and maps the wire-shaped outcome into Baton's
  shared authorization. It is key-free mapping evidence, not a cryptographic
  verifier or trusted transport implementation.
  The runtime derives the per-channel available-connector ceiling from its
  enabled routes; a Signet outcome may narrow that set but cannot authorize a
  connector outside it. Issuer and trust-policy configuration must come from
  an audited high-administration control plane; the adapter constructor is not
  that control plane.
- `SqliteDelegatedRuntimeState` and
  `DelegatedConnectorRuntime.build_sqlite_reference` are single-node reference
  implementations for executable recovery evidence. They are not a
  multi-replica production state backend.

## Exact Delegated Authorization Contract

The trusted Signet-compatible verifier receives the opaque authorization
reference, the exact `DispatchRequest`, and a `DelegatedAuthorizationContext`.
The context's per-channel available connector IDs are the runtime ceiling: the
verified authorization may narrow to a non-empty subset but cannot authorize
an unavailable connector.
Its verified outcome must bind:

- authorization ID and issuer;
- Baton delegated-executor audience;
- the exact issuer-policy and rotation-policy references applied by the
  verifier;
- workload ID/principal;
- exactly one channel;
- allowed connector IDs and exactly one purpose matching the runtime;
- `not_before` and `not_after`;
- `max_uses=1` and a provider-attempt budget; and
- the exact canonical request fingerprint.

The configured Baton verifier bundle must also supply a positive provider-attempt
ceiling no greater than `3` and an authorization-lifetime ceiling no greater
than `15` minutes. Baton sends those ceilings to the Signet verifier, rejects a
Signet result that exceeds either one, and rechecks the bounded verified result
before dispatch admission.

The request fingerprint is a domain-separated SHA-256 digest over
`dispatch_id`, workflow/operation ID, channel, opaque recipient reference,
opaque payload reference, and idempotency key. `DispatchRequest` and
`CredentialUseRequest` both reject a fingerprint that does not match those
fields. Recipient and payload references therefore must identify immutable or
versioned data; the digest does not make a mutable reference immutable.

`dispatch_claim_id` is acquired only after verification and is intentionally
outside the signed fingerprint. The durable journal and authorization ledger
bind it to the active exact dispatch before reservation or provider use.

The verified outcome contains no provider credential, credential handle,
recipient value, payload value, or provider response. `authorization_id` is the
sanitized correlation reference carried through custody audit events.
Issuer-policy and rotation-policy references are verified trust metadata, not
signed provider-operation claims; they must exactly match the configured
verifier bundle.

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
- A provider attempt is atomically reserved in the durable authorization ledger
  before invocation. Its verified attempt budget remains consumed across
  process crashes, dispatch aborts, and stale-claim recovery.
- A successful provider operation followed by custody outcome or audit
  persistence failure returns non-retryable `custody_state_unavailable`; the
  executor does not automatically send again.
- A provider operation followed by dispatch-journal completion failure raises
  `DispatchStateUnavailable` and leaves the claim for explicit recovery. It
  does not erase or abort the post-provider claim.
- After a dispatch claim is acquired, exceptional execution paths do not
  automatically abort it. Because the executor may not know whether a provider
  operation occurred, the lease remains in place until controlled recovery.

## Recovery Windows

The runtime deliberately fails closed around these crash windows:

1. Before provider-attempt reservation, an expired claim may be reclaimed. The
   old claim can no longer reserve or invoke.
2. After provider-attempt reservation but before provider invocation, the
   durable budget remains consumed. Recovery does not blindly repeat that
   attempt.
3. After provider invocation but before custody outcome or dispatch-journal
   completion, delivery is uncertain. The custody-internal provider operation
   must enforce the supplied idempotency key; without that provider-side
   guarantee, at-least-once recovery can duplicate delivery.
4. After dispatch-journal completion but before terminal signal persistence, a
   replay returns the completed sanitized outcome and retries the idempotent
   signal without invoking the provider again.

The SQLite reference hash chain detects mutation when verified against its
current anchor, but it is tamper-evident rather than tamper-proof. A privileged
actor could rewrite the database and recompute the chain. Its failure queue is
durable and acknowledgeable, but does not prove that an external operator was
paged.

## Integration Gate

These modules are a connected runtime and executable reference, not a
configured production custody deployment. The delegated executor no longer
accepts a direct provider invoker. Production construction must use explicit
durable components and an audited custody implementation; the protocol seams
exist for approved cloud-neutral backends.

MEA integration remains blocked until all of the following exist:

1. A concrete trusted Signet delegated-provider verifier client and transport
   with issuer and rotation enforcement. The key-free Baton adapter does not
   establish that trust.
2. A shared, highly available multi-replica implementation of the durable
   component contracts, including atomic claim, reservation, attempt-budget,
   completion, replay, and recovery behavior.
3. A custody-internal resolver implementation, potentially backed by OpenBao
   after license, deployment, assurance, and operational review.
4. An externally anchored audit pipeline and an operated failure-notification
   consumer with tested acknowledgement and escalation.
5. Provider-operation idempotency and operator reconciliation for uncertain
   post-invocation outcomes.
6. A shared circuit-breaker implementation or an explicit decision to accept
   process-local circuit state. The current executor's circuit state is local
   to one process.
7. Key-free executable evidence for each boundary and the provider executor.

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
