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
  compat.py           # Static + runtime compatibility analysis (validate_service_runtime)
  taint.py            # Taint analysis: canary data generation, boundary tracking, fingerprint scanning
  adapter.py          # Async reverse proxy with A/B routing, HTTP health checks, latency percentiles, taint scanning
  adapter_control.py  # Adapter management API (/health, /metrics, /status, /routing, /taint, POST /events)
  service_log.py      # System-controlled service log capture, severity parsing, JSONL persistence
  constrain.py        # Constrain component_map.yaml -> baton.yaml generation
  arbiter.py          # Arbiter REST API client (trust scores, declaration gaps)
  arbiter_exporter.py # Fire-and-forget span forwarding to Arbiter OTLP
  audit_sidecar.py    # Local audit event receiver (127.0.0.1 only)
  canary_test.py      # Canary soak test orchestration
  ledger.py           # Ledger client: egress node sync, field masking, mock records
  routing.py          # Pre-baked routing patterns (ab_split, canary, header_route, weighted_split)
  canary.py           # CanaryController: auto-promotion/rollback with per-target metrics
  image.py            # ImageBuilder: runtime detection, Dockerfile generation, build/push
  mock.py             # Mock server generation
  custodian.py        # Health monitoring + repair
  process.py          # Subprocess management with log capture (stdout/stderr -> ServiceLogCollector)
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
baton slot <node> <command>            # slot live service (validates contract if set)
baton slot <node> <cmd> --skip-validate # skip runtime interface validation
baton swap <node> <command>            # hot-swap service (validates contract if set)
baton collapse [--live n1,n2]          # collapse circuit to partial mock
baton status                           # show health
baton watch                            # start custodian
baton down                             # tear down

# Taint Analysis
baton taint seed [--node N]            # seed canary data into services
baton taint status                     # show active canary data and violations
baton taint violations                 # list all taint violations
baton taint clear                      # remove all canary data

# Arbiter Integration
baton trust <node>                    # show Arbiter trust score
baton audit <node>                    # show recent audit events
baton arbiter status                  # Arbiter connectivity check
baton test --canary [--tiers T]       # canary soak test
baton test --canary --ledger-mocks    # canary test with Ledger mock data
baton init --constrain-dir <path>     # generate from Constrain component_map
baton sync-ledger                     # sync egress nodes from Ledger

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
baton logs [--node N] [--level L]     # service logs (system-captured stdout/stderr)
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
- Runtime validation: `slot()` and `swap()` probe live services against their OpenAPI contract before accepting them. Skippable with `validate=False` or `--skip-validate`. Only active for HTTP-mode nodes with a `contract` field.
- Arbiter integration: optional via `arbiter` section in `CircuitConfig`. All Arbiter calls use 2s timeout and degrade gracefully (return None/empty). Slot validation checks trust score and declaration gaps when configured. Classification tagging reads `x-data-classification` from OpenAPI specs.
- Audit sidecar: `AuditSidecar` binds to 127.0.0.1 only. Services POST to `POST /audit-event` on the configured port (default 9000). Events buffered in memory, queryable by node.
- Constrain integration: `baton init --constrain-dir` reads `component_map.yaml` and generates baton.yaml v2 skeleton with data_access, authority, and edge tiers.
- Ledger integration: optional via `ledger` section in `CircuitConfig`. `baton sync-ledger` fetches egress node configs from Ledger. Adapter applies field masks (`_apply_field_masks`) to JSON response bodies before forwarding — encrypted-at-rest fields are replaced with `[ENCRYPTED]`. `--ledger-mocks` on canary test uses Ledger-generated mock records.
- Taint analysis: `taint.py` seeds PII-shaped canary data with 8-char hex fingerprints (SSN, email, credit card, phone, name). `TaintScanner` hooks into adapter proxy and service logs to detect fingerprints crossing boundary violations. Opt-in via `taint.enabled: true` in `CircuitConfig`. Data stored in `.baton/taint_canaries.jsonl` and `.baton/taint_violations.jsonl`.
- Service event channel: Services POST structured events to `POST /events` on their adapter's control port (`BATON_CONTROL_PORT` env var). Events buffered on `AdapterControlServer`, drainable via `drain_service_events()`. Persisted to `.baton/events.jsonl` as `service_event` type.
- System-controlled logging: `ServiceLogCollector` captures service stdout/stderr via `ProcessManager` line-reader callbacks. Each line is structured with node attribution, stream source, severity (auto-parsed from common patterns: ERROR, WARNING, DEBUG, etc.), and timestamp. Persisted to `.baton/service_logs.jsonl`. Taint scanner also scans log output for canary fingerprints.
- Environment: Services receive `BATON_SERVICE_PORT`, `BATON_NODE_NAME`, and `BATON_CONTROL_PORT` env vars at startup.

## Research-Backed Features

Derived from McEntire AI/ML papers (Papers 19-24, 43):

- **Hop Saturation** (Paper 24): `longest_path()` and `topology_warnings()` in circuit.py. Multi-hop degradation saturates by hop 5. Topologies deeper than 5 are warned but not blocked.
- **Two-Phase Repair** (Paper 23): Custodian `RepairPlaybook` separates fault classification (mode boundary) from recovery selection (domain prime). These are orthogonal decisions (rho = 0.858).
- **Centroid Selection** (Paper 19): `centroid_select()` in canary.py. For canary evaluation with multiple candidates, selects the one closest to ensemble centroid. Closes 48.9% of coordination gap vs 9.1% for state injection.
- **Signal Deduplication** (Paper 20): `SignalAggregator` suppresses repeated identical signals within a configurable time window. Paper 20: repetition degrades performance +0.07 nats per repeat.
- **Specialist Nodes** (Paper 43): `topology_warnings()` flags nodes with >2 concerns in metadata. Universal entanglement is reduced by specialist architectures (lower d/k ratio).
