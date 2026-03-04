# Baton

Cloud-agnostic circuit orchestration. Pre-wired topologies with smart adapters, mock collapse, A/B routing, and self-healing.

## Architecture

Circuit board metaphor: define the topology (nodes + edges) once, then slot services in and out.

Two workflows:
- **Topology-first** — hand-author `baton.yaml` with nodes/edges, then slot services in.
- **Service-first** — each service self-describes via `baton-service.yaml` (API spec, mocks, dependencies). Circuit is derived from manifests.

Core concepts:
- **Circuit** — the board. Nodes + edges + addresses. First-class artifact.
- **Adapter** — async reverse proxy at each node. Handles hot-swap, drain, health, A/B routing.
- **Routing** — weighted, header-based, or canary routing at the adapter level. Config locking prevents accidental overrides.
- **Mock** — auto-generated from OpenAPI/JSON Schema contracts.
- **Collapse** — compress circuit: full mock (one process) through partial to full live.
- **Custodian** — monitors adapters, self-heals with atomic repairs.
- **Node Roles** — `service` (default), `ingress` (entry from outside), `egress` (outbound to external APIs, auto-mocked).
- **Providers** — deployment backends: local (default), GCP Cloud Run, AWS (planned).

## Structure

```
src/baton/
  schemas.py          # All Pydantic v2 models (RoutingConfig, NodeRole, ServiceManifest, etc.)
  config.py           # YAML config loader (topology-first + service-first)
  cli.py              # argparse entry point
  circuit.py          # Graph operations
  manifest.py         # Service manifest loading (baton-service.yaml)
  registry.py         # Circuit derivation from service manifests
  compat.py           # Static compatibility analysis
  adapter.py          # Async reverse proxy with A/B routing, HTTP health checks, latency percentiles
  adapter_control.py  # Adapter management API (/health, /metrics, /status, /routing)
  routing.py          # Pre-baked routing patterns (ab_split, canary, header_route, weighted_split)
  mock.py             # Mock server generation
  custodian.py        # Health monitoring + repair
  process.py          # Subprocess management
  state.py            # .baton/ persistence + JSONL utilities
  lifecycle.py        # Circuit lifecycle orchestration (slot, swap, slot_ab, route_ab, lock/unlock)
  collapse.py         # Collapse algorithm (egress nodes always mocked)
  dashboard.py        # Aggregated metrics snapshot across all nodes
  telemetry.py        # Persistent JSONL metrics collection + Prometheus export
  signals.py          # Cross-node signal aggregation + per-path statistics
  providers/          # Cloud deployment plugins
    local.py          # Local process deployment
    gcp.py            # GCP Cloud Run deployment
```

## Commands

```bash
# Topology-first workflow
baton init [dir]                       # create baton.yaml
baton node add <name> [--port N]       # add node to circuit
baton edge add <from> <to>             # add connection
baton contract set <node> <spec>       # attach contract

# Service-first workflow
baton service register <path>          # register a service manifest
baton service list                     # list registered services
baton service derive [--save]          # derive circuit from manifests
baton check [--service <name>]         # static compatibility analysis

# Runtime
baton up [--mock] [--services]         # boot circuit (--services for service-first)
baton slot <node> <command>            # slot live service
baton swap <node> <command>            # hot-swap service
baton collapse [--live n1,n2]          # collapse circuit to partial mock
baton status                           # show health
baton watch                            # start custodian
baton down                             # tear down

# A/B Routing
baton route show <node>                # show routing config
baton route ab <node> <cmd> [--split]  # A/B split (reuses existing as A)
baton route canary <node> <cmd> [--pct]# canary rollout
baton route set <node> --strategy ...  # custom routing config
baton route lock <node>                # lock routing (prevents slot/swap)
baton route unlock <node>              # unlock routing
baton route clear <node>               # remove routing config

# Observability
baton dashboard [--json]              # aggregated metrics table for all nodes
baton metrics [--node N] [--last N]   # persistent metrics from JSONL
baton metrics --prometheus            # Prometheus text exposition format
baton signals [--node N] [--path P]   # recent request signals
baton signals --stats                 # per-path statistics (count, avg latency, error rate)

# Deployment
baton deploy [--provider local|gcp]    # deploy circuit to provider
baton teardown [--provider local|gcp]  # tear down deployment
baton deploy-status [--provider ...]   # check deployment status
```

## Conventions

- Python 3.12+, Pydantic v2, argparse, hatchling, pytest
- Frozen models for topology definitions, mutable for runtime state
- Protocol-based DI for extensible components (DeploymentProvider)
- All async operations use asyncio (no external server frameworks)
- Tests: one test file per source module, pytest-asyncio
- Egress nodes cannot have live services slotted in (auto-mocked only)
- Routing: when RoutingConfig is None, adapter behaves as single-backend (backwards compatible)
- Lock guards: locked routing prevents set_backend, set_routing, clear_routing, slot, swap
