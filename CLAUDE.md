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
- **Canary** — auto-promotion controller evaluates error rate + latency vs thresholds, promotes through weight steps or rolls back.
- **Mock** — auto-generated from OpenAPI/JSON Schema contracts.
- **Collapse** — compress circuit: full mock (one process) through partial to full live.
- **Custodian** — monitors adapters, self-heals with atomic repairs.
- **Node Roles** — `service` (default), `ingress` (entry from outside), `egress` (outbound to external APIs, auto-mocked).
- **Image Building** — auto-detect runtime (Python/Node), generate Dockerfiles, build/push container images.
- **Providers** — deployment backends: local (default), GCP Cloud Run (with `--build`), AWS (planned).

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
  canary.py           # CanaryController: auto-promotion/rollback with per-target metrics
  image.py            # ImageBuilder: runtime detection, Dockerfile generation, build/push
  mock.py             # Mock server generation
  custodian.py        # Health monitoring + repair
  process.py          # Subprocess management
  state.py            # .baton/ persistence + JSONL utilities
  lifecycle.py        # Circuit lifecycle orchestration (slot, swap, slot_ab, route_ab, lock/unlock)
  collapse.py         # Collapse algorithm (egress nodes always mocked)
  dashboard.py        # Aggregated metrics snapshot across all nodes
  dora.py             # DORA metrics derivation from lifecycle events
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
baton route canary <node> <cmd> --promote # auto-promote/rollback canary
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

# Images
baton image build [--node N] [--path P] # detect runtime, generate Dockerfile, build
baton image push [--node N] [--tag T]   # push image to registry
baton image list                        # list built images

# Deployment
baton deploy [--provider local|gcp]    # deploy circuit to provider
baton deploy --provider gcp --build    # auto-build + deploy to Cloud Run
baton teardown [--provider local|gcp]  # tear down deployment
baton deploy-status [--provider ...]   # check deployment status
```

## Conventions

- Python 3.12+, Pydantic v2, argparse, hatchling, pytest
- Frozen models for topology definitions, mutable for runtime state
- Protocol-based DI for extensible components (DeploymentProvider)
- All async operations use asyncio (no external server frameworks)
- Tests: 804 total (701 hand-written + 103 pact-generated smoke tests), one test file per source module, pytest-asyncio
- Smoke tests: `tests/smoke/` -- 35 files covering all 36 source modules, auto-generated via `pact adopt`. Verify imports and public function callability.
- Egress nodes cannot have live services slotted in (auto-mocked only)
- Routing: when RoutingConfig is None, adapter behaves as single-backend (backwards compatible)
- Lock guards: locked routing prevents set_backend, set_routing, clear_routing, slot, swap
- Process ownership: `CircuitState.owner_pid` tracks the PID of the `baton up`/`baton apply` process. `baton down` sends SIGTERM to the owner so it cleans up via its `finally` block (drain adapters, stop control servers, kill child processes).
- Mock wiring: both `baton up --mock` and `baton apply` wire mock backends for nodes without live services via `build_mock_server()`/`compute_mock_backends()`. The mock server is stopped in the owning process's cleanup path.
- DORA metrics: `dora.py` derives deployment frequency, lead time, change failure rate, and MTTR from lifecycle events recorded in `.baton/events.jsonl`.

## Research-Backed Features

Derived from McEntire AI/ML papers (Papers 19-24, 43):

- **Hop Saturation** (Paper 24): `longest_path()` and `topology_warnings()` in circuit.py. Multi-hop degradation saturates by hop 5. Topologies deeper than 5 are warned but not blocked.
- **Two-Phase Repair** (Paper 23): Custodian `RepairPlaybook` separates fault classification (mode boundary) from recovery selection (domain prime). These are orthogonal decisions (rho = 0.858).
- **Centroid Selection** (Paper 19): `centroid_select()` in canary.py. For canary evaluation with multiple candidates, selects the one closest to ensemble centroid. Closes 48.9% of coordination gap vs 9.1% for state injection.
- **Signal Deduplication** (Paper 20): `SignalAggregator` suppresses repeated identical signals within a configurable time window. Paper 20: repetition degrades performance +0.07 nats per repeat.
- **Specialist Nodes** (Paper 43): `topology_warnings()` flags nodes with >2 concerns in metadata. Universal entanglement is reduced by specialist architectures (lower d/k ratio).
