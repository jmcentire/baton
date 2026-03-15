# Baton — System Context

## What It Is
Cloud-agnostic circuit orchestration. Pre-wired topologies with smart adapters, mock collapse, A/B routing, canary promotion, taint analysis, and self-healing. Research-backed (Papers 19, 20, 23, 24, 43).

## How It Works
Circuit board metaphor: define topology (nodes + edges) once, slot services in and out. Two workflows: topology-first (hand-author baton.yaml) or service-first (derive from manifests).

## Key Constraints
- Egress nodes always mocked (C001)
- Routing lock guards protect critical nodes (C002)
- Adapter observations are ground truth (C003)
- Audit sidecar binds 127.0.0.1 only (C004)
- Arbiter calls degrade gracefully with 2s timeout (C009)
- Field masking for encrypted data in transit (C010)

## Architecture
43 source modules. Core: adapter (reverse proxy), lifecycle (orchestration), custodian (self-healing), taint (canary tracking), telemetry (metrics), signals (cross-node aggregation).

## Integrations
- Arbiter: trust scores, OTLP span forwarding (optional, graceful degradation)
- Ledger: field masking, egress node sync, mock records (optional)
- Constrain: component_map.yaml -> baton.yaml generation
- Pact: adopted, 103 smoke tests

## Done Checklist
- [ ] Circuit boots with mock and live services
- [ ] Taint analysis detects boundary violations
- [ ] Arbiter unavailability doesn't crash circuit
- [ ] Field masking replaces encrypted fields
- [ ] Canary promotion/rollback works end-to-end
