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
- **Self-healing** -- custodian monitors health, restarts failed services, escalates when repairs fail
- **Two workflows** -- topology-first (hand-author `baton.yaml`) or service-first (derive from `baton-service.yaml` manifests)
- **Cloud deployment** -- local processes or GCP Cloud Run; provider protocol for extensibility

## Quickstart

```bash
pip install baton-orchestrator

# Create a circuit
baton init myproject
cd myproject
baton node add api --port 8001
baton node add service --port 8002
baton edge add api service

# Boot with mocks
baton up --mock

# Slot in a real service
baton slot api "python -m http.server 8001"

# Check health
baton status

# A/B test a new version
baton route ab api "python -m http.server 8003" --split 80/20
baton route show api

# Lock routing to prevent accidental changes
baton route lock api

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
baton route set <node> --strategy ...     # custom routing config
baton route lock <node>                   # lock routing (prevents slot/swap)
baton route unlock <node>                 # unlock routing
baton route clear <node>                  # remove routing, back to single backend
```

### Deployment

```bash
baton deploy [--provider local|gcp]       # deploy circuit
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
baton deploy --provider gcp --project my-project --region us-central1 \
  --image "us-docker.pkg.dev/cloudrun/container/hello:latest"
```

Each node becomes a Cloud Run service. Edges are realized via environment variables.

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

## Development

```bash
git clone https://github.com/jmcentire/baton.git
cd baton
pip install -e ".[dev]"
pytest
```

## License

MIT
