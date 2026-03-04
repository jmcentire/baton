# Baton

Cloud-agnostic circuit orchestration. Pre-wired topologies with smart adapters, mock collapse, A/B routing, and self-healing.

## What is Baton?

Baton treats your service topology like a **circuit board**. Define the wiring once -- nodes, edges, contracts -- then slot services in and out at will. Every node gets an async reverse proxy (adapter) that handles health checks, traffic routing, hot-swaps, and automatic failover.

Start fully mocked. Slot in real services one at a time. Run A/B tests. Collapse back to mocks when you're done. Deploy locally or to GCP Cloud Run.

## Features

- **Circuit-first design** -- topology is a first-class artifact, not an afterthought
- **Smart adapters** -- async reverse proxies with per-request routing, draining, and health checks
- **Mock collapse** -- auto-generate mock servers from OpenAPI/JSON Schema contracts; run your entire circuit in one process
- **Hot-swap** -- replace running services with zero downtime (drain old, start new, switch)
- **A/B routing** -- weighted splits, canary rollouts, header-based routing with config locking
- **Canary auto-promotion** -- automated canary evaluation with error rate and latency thresholds; promotes or rolls back without intervention
- **Self-healing** -- custodian monitors health, restarts failed services, escalates when repairs fail
- **Two workflows** -- topology-first (hand-author `baton.yaml`) or service-first (derive from `baton-service.yaml` manifests)
- **Image building** -- auto-detect runtime (Python/Node), generate Dockerfiles, build and push container images
- **Cloud deployment** -- local processes or GCP Cloud Run with `--build` for automatic image building; provider protocol for extensibility

## Quickstart

```bash
pip install baton-orchestrator

# Create a circuit with roles
baton init myproject
cd myproject
baton node add gateway --port 8001 --role ingress
baton node add api --port 8002
baton node add stripe --port 8003 --role egress
baton edge add gateway api
baton edge add api stripe

# Boot with mocks
baton up --mock

# Slot in a real service
baton slot api "python -m http.server 8002"

# Check health
baton status

# A/B test a new version
baton route ab api "python -m http.server 8004" --split 80/20
baton route show api

# Lock routing to prevent accidental changes
baton route lock api

# Launch live dashboard
baton dashboard --serve

# Tear down
baton down
```

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │           baton.yaml                │
                    │  nodes: [api, service, db]          │
                    │  edges: [api->service, service->db] │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │         Circuit Board                │
                    │                                      │
                    │  ┌─────────┐    ┌─────────┐         │
                    │  │ Adapter │───▶│ Adapter │         │
                    │  │  :8001  │    │  :8002  │         │
                    │  │┌───────┐│    │┌───────┐│         │
                    │  ││  api  ││    ││service││         │
                    │  │└───────┘│    │└───────┘│         │
                    │  └─────────┘    └────┬────┘         │
                    │                      │              │
                    │                 ┌────▼────┐         │
                    │                 │ Adapter │         │
                    │                 │  :8003  │         │
                    │                 │┌───────┐│         │
                    │                 ││  db   ││         │
                    │                 │└───────┘│         │
                    │                 └─────────┘         │
                    │                                      │
                    │  Custodian: health polling + repair   │
                    └──────────────────────────────────────┘
```

Each adapter is an async reverse proxy that:
- Forwards traffic to the slotted service (or mock)
- Exposes `/health`, `/metrics`, `/status`, `/routing` on a management port
- Supports weighted, header-based, and canary routing
- Drains connections gracefully during hot-swaps
- Reports metrics: request count, latency, bytes forwarded, error rate

## Commands

### Topology

```bash
baton init [dir]                          # create baton.yaml + .baton/
baton node add <name> [--port N]          # add node (auto-assigns port if omitted)
baton node rm <name>                      # remove node and its edges
baton edge add <from> <to>                # connect nodes
baton edge rm <from> <to>                 # disconnect nodes
baton contract set <node> <spec.yaml>     # attach OpenAPI/JSON Schema contract
baton status                              # show circuit topology and health
```

### Service-First Workflow

```bash
baton service register <path>             # register a baton-service.yaml manifest
baton service list                        # list registered services
baton service derive [--save]             # derive circuit from manifests
baton check [--service <name>]            # static API compatibility analysis
```

### Runtime

```bash
baton up [--mock] [--services]            # boot circuit
baton slot <node> <command>               # slot live service into node
baton swap <node> <command>               # hot-swap (zero-downtime replace)
baton collapse [--live n1,n2]             # partial mock (keep some nodes live)
baton watch [--interval 5]                # start custodian (health monitor)
baton down                                # tear down circuit
```

### Routing

```bash
baton route show <node>                   # display routing config
baton route ab <node> <cmd> [--split N/M] # A/B split (default 80/20)
baton route canary <node> <cmd> [--pct N] # canary rollout (default 10%)
baton route canary <node> <cmd> --promote # auto-promote canary (evaluate + promote/rollback)
baton route set <node> --strategy ...     # custom routing config
baton route lock <node>                   # lock routing (prevents slot/swap)
baton route unlock <node>                 # unlock routing
baton route clear <node>                  # remove routing, back to single backend
```

### Observability

```bash
baton dashboard [--json]                  # aggregated metrics table
baton dashboard --serve [--port 9900]     # launch live dashboard UI
baton metrics [--node N] [--last N]       # persistent metrics from JSONL
baton metrics --prometheus                # Prometheus text exposition format
baton signals [--node N] [--path P]       # recent request signals
baton signals --stats                     # per-path statistics
```

### Images

```bash
baton image build [--node N] [--path P]   # detect runtime, generate Dockerfile, build image
baton image push [--node N] [--tag T]     # push image to registry
baton image list                          # list built images
```

### Deployment

```bash
baton deploy [--provider local|gcp]       # deploy circuit
baton deploy --provider gcp --build       # build images + deploy to Cloud Run
baton teardown [--provider local|gcp]     # tear down deployment
baton deploy-status [--provider ...]      # check deployment status
```

## Service Manifests

Each service can self-describe with a `baton-service.yaml`:

```yaml
name: api
role: service
api_spec: specs/openapi.yaml
mock_spec: specs/openapi.yaml
dependencies:
  - name: database
    required: true
    expected_api: specs/db-api.yaml
```

Run `baton service derive --save` to automatically generate `baton.yaml` from manifests.

## Observability

Every adapter records per-request signals (method, path, status, latency) and aggregated metrics (request counts, error rates, percentile latencies). Baton provides three ways to consume this data:

- **Dashboard** -- `baton dashboard --serve` launches a live browser UI with node cards, bar charts, signal logs, and topology views. Polls every 2 seconds.
- **Signals** -- `baton signals --stats` shows per-path aggregations. Signals are persisted to `.baton/signals.jsonl` for offline analysis.
- **Metrics** -- `baton metrics --prometheus` exports all node metrics in Prometheus text exposition format. Snapshots are persisted to `.baton/metrics.jsonl`.

## Canary Auto-Promotion

```bash
baton route canary api "python app_v2.py" --pct 10 --promote \
  --error-threshold 5.0 --latency-threshold 500 --eval-interval 30
```

The canary controller evaluates the canary vs stable targets every `eval-interval` seconds:
- If canary error rate exceeds `error-threshold` (%) or p99 latency exceeds `latency-threshold` (ms): **rollback** to 100% stable
- Otherwise: **promote** through weight steps (10% -> 25% -> 50% -> 100%)
- At 100%: promotion complete, canary becomes the new primary

Per-target metrics (stable vs canary) are tracked independently by the adapter, giving accurate comparison even under mixed traffic.

## Mock Collapse

Baton auto-generates mock servers from OpenAPI specs. This means you can:

1. **Start fully mocked** -- entire circuit runs in one process, all responses generated from schemas
2. **Slot in services one at a time** -- replace mocks with real implementations as they're ready
3. **Collapse back** -- `baton collapse --live api` keeps `api` live and mocks everything else

Collapse levels: `full_mock` -> `partial` -> `full_live`

## Self-Healing

The custodian monitors adapter health via TCP probes every 5 seconds:

1. **3 consecutive failures** -- restart the service process
2. **6 consecutive failures** -- replace with mock (503)
3. **Still failing** -- escalate (mark faulted, log for manual intervention)

When a service recovers, the custodian automatically resets its status.

## Cloud Deployment

### Local (default)

```bash
baton deploy --provider local
```

Runs services as local processes with adapters.

### GCP Cloud Run

```bash
pip install baton-orchestrator[gcp]

# Deploy with pre-built images
baton deploy --provider gcp --project my-project --region us-central1 \
  --image "us-docker.pkg.dev/cloudrun/container/hello:latest"

# Or auto-build and deploy
baton deploy --provider gcp --build --project my-project --region us-central1
```

Each node becomes a Cloud Run service. Edges are realized via `BATON_{NODE}_URL` environment variables injected automatically. The `--build` flag detects runtimes, generates Dockerfiles, builds images, pushes to GCR, and deploys.

## Configuration

### baton.yaml

```yaml
name: myproject
version: 1
nodes:
  - name: api
    port: 8001
    proxy_mode: http
    role: service
  - name: database
    port: 5432
    proxy_mode: tcp
    role: egress
edges:
  - source: api
    target: database
```

### Node Roles

| Role | Description |
|------|-------------|
| `service` | Internal service (default). Can slot live or mock. |
| `ingress` | Entry point from outside the circuit. |
| `egress` | External dependency (e.g., third-party API). Always mocked. |

## Contract Governance (Pact)

This codebase is governed by [Pact](https://github.com/jmcentire/pact), a contract-first multi-agent software engineering framework. Pact reverse-engineered contracts and tests for all 25 source modules (247 functions):

```
.pact/
  contracts/          # Per-module contracts + tests
    src_baton_adapter/
      interface.py    # 40-function contract with pre/postconditions
      interface.json  # Machine-readable contract
      tests/          # Generated contract tests (82 cases)
    ...               # 24 more modules
  test-gen/
    security_audit.md # Automated security findings
  state.json          # Adoption state
```

The contracts serve as living documentation of baton's interface boundaries. Each contract specifies function signatures, type definitions, invariants, and behavioral constraints that any implementation must satisfy.

## Development

```bash
git clone https://github.com/jmcentire/baton.git
cd baton
pip install -e ".[dev]"
pytest                    # 379 tests
```

## License

MIT
