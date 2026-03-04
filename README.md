# Baton

Cloud-agnostic circuit orchestration. Pre-wired topologies with smart adapters, mock collapse, A/B routing, multi-protocol support, federation, and self-healing.

## What is Baton?

Baton treats your service topology like a **circuit board**. Define the wiring once -- nodes, edges, contracts -- then slot services in and out at will. Every node gets an async reverse proxy (adapter) that handles health checks, traffic routing, hot-swaps, and automatic failover.

Start fully mocked. Slot in real services one at a time. Run A/B tests. Collapse back to mocks when you're done. Deploy locally or to GCP Cloud Run. Federate across clusters.

## Features

- **Circuit-first design** -- topology is a first-class artifact, not an afterthought
- **Smart adapters** -- async reverse proxies with per-request routing, draining, and health checks
- **Multi-protocol** -- HTTP, TCP, gRPC, protobuf (length-prefixed binary), and SOAP out of the box; extensible via ProtocolHandler registry
- **Mock collapse** -- auto-generate mock servers from OpenAPI/JSON Schema contracts; run your entire circuit in one process
- **Hot-swap** -- replace running services with zero downtime (drain old, start new, switch)
- **A/B routing** -- weighted splits, canary rollouts, header-based routing with config locking
- **Canary auto-promotion** -- automated canary evaluation with error rate and latency thresholds; promotes or rolls back without intervention
- **Self-healing** -- custodian monitors health, restarts failed services, escalates when repairs fail
- **Multi-cluster federation** -- heartbeat-based peer discovery, cross-cluster state sync, automatic failover and restore
- **Certificate management** -- monitor TLS certificate expiry, auto-rotate certs with zero downtime
- **MCP integration** -- Model Context Protocol server exposes circuit state to AI assistants (Claude Code, etc.)
- **Two workflows** -- topology-first (hand-author `baton.yaml`) or service-first (derive from `baton-service.yaml` manifests)
- **Image building** -- auto-detect runtime (Python/Node), generate Dockerfiles, build and push container images
- **Cloud deployment** -- local processes or GCP Cloud Run with `--build` for automatic image building; provider protocol for extensibility
- **Security hardened** -- command injection prevention, header injection protection, path traversal guards, fail-closed auth, bounded header parsing

## Quickstart

```bash
pip install baton-orchestrator

# Create a circuit
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

# Launch live dashboard
baton dashboard --serve

# Tear down
baton down
```

## Architecture

```
                    +-------------------------------------+
                    |           baton.yaml                 |
                    |  nodes: [api, service, db]           |
                    |  edges: [api->service, service->db]  |
                    +------------------+------------------+
                                       |
                    +------------------v------------------+
                    |          Circuit Board               |
                    |                                      |
                    |  +---------+    +---------+          |
                    |  | Adapter |----> Adapter |          |
                    |  |  :8001  |    |  :8002  |          |
                    |  | [ api ] |    |[service]|          |
                    |  +---------+    +----+----+          |
                    |                      |               |
                    |                 +----v----+          |
                    |                 | Adapter |          |
                    |                 |  :8003  |          |
                    |                 | [  db  ]|          |
                    |                 +---------+          |
                    |                                      |
                    |  Custodian: health polling + repair   |
                    +--------------------------------------+
```

Each adapter is an async reverse proxy that:
- Forwards traffic to the slotted service (or mock)
- Supports HTTP, TCP, gRPC, protobuf, and SOAP protocols
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

### Federation

```bash
baton federation status [--json]          # show federation config and cluster identity
baton federation peers [--json]           # list peer clusters and their state
```

### Certificates

```bash
baton certs status [--json]               # show TLS certificate info and expiry
baton certs rotate                        # force certificate rotation
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

### Declarative Config

```bash
baton apply [--dry-run]                   # converge running state to match baton.yaml
baton export [--output file.yaml]         # export running state as YAML config
```

## Protocol Support

Baton supports multiple proxy modes through a pluggable ProtocolHandler registry:

| Mode | Description | Health Check |
|------|-------------|--------------|
| `http` | HTTP/1.1 reverse proxy with tracing, circuit breaker, retries | HTTP GET to health path |
| `tcp` | Bidirectional byte pipe | TCP connectivity |
| `grpc` | Transparent HTTP/2 forwarding | TCP connectivity |
| `protobuf` | Length-prefixed binary proxy (4-byte big-endian + payload) | TCP connectivity |
| `soap` | HTTP with SOAPAction header awareness and fault detection | HTTP + SOAP fault check |

```bash
baton node add api --mode http
baton node add db --mode tcp
baton node add rpc --mode grpc
baton node add wire --mode protobuf
baton node add legacy --mode soap
```

Custom protocol handlers implement the `ProtocolHandler` protocol and register via `register_handler(mode, cls)`.

## Multi-Cluster Federation

Baton supports federating multiple clusters for cross-cluster visibility and failover:

```yaml
# baton.yaml
federation:
  enabled: true
  identity:
    name: cluster-east
    api_endpoint: 10.0.0.1:9090
    region: us-east
  peers:
    - name: cluster-west
      api_endpoint: 10.0.1.1:9090
      region: us-west
  heartbeat_interval_s: 30
  failover_threshold: 3
```

Each cluster runs a federation HTTP API and a heartbeat loop. When a peer becomes unreachable after `failover_threshold` consecutive failures, Baton generates a `federated_failover` event. When the peer recovers, a `federated_restore` event is emitted.

## Certificate Management

Baton monitors TLS certificates and can auto-rotate them with zero downtime:

```yaml
# baton.yaml
security:
  tls:
    mode: full
    cert: certs/server.pem
    key: certs/server-key.pem
    auto_rotate: true
    rotate_check_interval_s: 3600
    warning_days: 30
    critical_days: 7
```

```bash
pip install baton-orchestrator[certs]
baton certs status         # show cert details, expiry, SAN
baton certs rotate         # force reload
```

New connections automatically use the updated certificate. Existing connections are unaffected.

## MCP Integration

Baton includes a [Model Context Protocol](https://modelcontextprotocol.io/) server so AI assistants can inspect circuit state:

```bash
pip install baton-orchestrator[mcp]
baton-mcp                  # start MCP server
```

Exposes resources (`baton://status`, `baton://topology`, `baton://node/{name}`), tools (`circuit_status`, `list_nodes`, `show_routes`, `show_metrics`, `show_signals`), and prompts (`circuit_overview`).

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

Each node becomes a Cloud Run service. Edges are realized via `BATON_{NODE}_URL` environment variables injected automatically.

## Configuration

### baton.yaml

```yaml
name: myproject
version: 1
nodes:
  - name: api
    port: 8001
    proxy_mode: http       # http, tcp, grpc, protobuf, soap
    role: service           # service, ingress, egress
  - name: database
    port: 5432
    proxy_mode: tcp
    role: egress
edges:
  - source: api
    target: database

security:
  tls:
    mode: full              # off, circuit, full
    cert: certs/server.pem
    key: certs/server-key.pem

federation:
  enabled: true
  identity:
    name: cluster-east
    api_endpoint: 10.0.0.1:9090
  peers:
    - name: cluster-west
      api_endpoint: 10.0.1.1:9090
```

### Node Roles

| Role | Description |
|------|-------------|
| `service` | Internal service (default). Can slot live or mock. |
| `ingress` | Entry point from outside the circuit. |
| `egress` | External dependency (e.g., third-party API). Always mocked. |

### Optional Dependencies

```bash
pip install baton-orchestrator[gcp]       # GCP Cloud Run deployment
pip install baton-orchestrator[otel]      # OpenTelemetry tracing
pip install baton-orchestrator[mcp]       # MCP server for AI assistants
pip install baton-orchestrator[certs]     # Certificate parsing and monitoring
```

## Development

```bash
git clone https://github.com/jmcentire/baton.git
cd baton
pip install -e ".[dev]"
pytest                    # 674 tests, 80% coverage
```

## License

MIT
