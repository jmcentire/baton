# Baton: Production Hardening

## Problem

Baton is a circuit orchestration tool where adapters are topology-aware reverse proxies. The circuit graph (nodes + edges) is the source of truth for service topology. Adapters handle routing, health, metrics, and mock collapse. It works locally today. To work in production, it needs: declarative configuration, secure communication, and observability integration.

But the common infrastructure solutions (Istio-style mTLS, Consul service discovery, Terraform-style state files) don't fit Baton's model. Baton already knows the topology -- the circuit IS the service mesh. Solutions should exploit this.

## Appetite

Six weeks. Three cycles of work. The result is a baton deployment that can run in cloud environments with security, observability, and git-versionable configuration.

## Cycle 1: Declarative Config + State Serialization

### The insight

Routing, deployment, and security config are currently imperative (CLI commands at runtime). They should be declarative -- expressed in `baton.yaml` and versionable in git. But unlike Terraform, baton shouldn't need a separate state file. The circuit graph already IS the desired state. `baton apply` computes the diff between the declared circuit and the running circuit, and converges.

### What to build

**Extend `baton.yaml`** with optional sections for routing, deploy, and security:

```yaml
name: myproject
version: 1

nodes:
  - name: api
    port: 8001
    role: ingress
    routing:
      strategy: canary
      targets:
        - name: stable
          port: 28001
          weight: 90
        - name: canary
          port: 28002
          weight: 10

edges:
  - source: api
    target: service
    policy:
      timeout_ms: 5000
      retries: 2

deploy:
  provider: gcp
  project: my-project
  region: us-central1
  build: true

security:
  tls:
    mode: circuit  # or "full" or "off"
    cert: ./certs/server.crt
    key: ./certs/server.key
  control:
    auth: bearer
    token_env: BATON_CONTROL_TOKEN
```

**`baton apply [--dir .]`** -- reads full config, diffs against running state, converges. Idempotent. Like `kubectl apply` but for circuits.

**`baton export [--dir .]`** -- snapshots running state back to YAML. Lets you capture production state, commit it, reproduce it elsewhere.

**Edge-level policies** -- policies attach to EDGES, not services. The api->service edge has its own timeout/retry/circuit-breaker config. This matches how infrastructure actually works: the relationship between two services has different characteristics than either service alone.

### Files to modify

- `src/baton/schemas.py` -- add `EdgePolicy`, `SecurityConfig`, `CircuitConfig` models
- `src/baton/config.py` -- extend parser/serializer for new sections
- `src/baton/cli.py` -- add `baton apply`, `baton export` commands
- `src/baton/lifecycle.py` -- add `apply()` method that diffs and converges

### No-gos

- No external state store (consul, etcd, redis). State lives in the circuit config + `.baton/`.
- No HCL or custom DSL. YAML only.
- No breaking changes to existing baton.yaml files.

---

## Cycle 2: Secure Communication

### The insight

Typical service meshes do mTLS on every hop. But baton already knows the topology. If two nodes are connected by an edge, they trust each other by definition -- the circuit declares it. TLS is only necessary at trust boundaries: ingress (external -> circuit) and egress (circuit -> external). Internal edges can optionally use TLS, but the circuit graph itself is the trust model.

This is "circuit trust" -- the graph defines who can talk to whom. The adapter enforces it. No certificates needed between internal nodes unless you want defense-in-depth.

### What to build

**TLS mode: `circuit`** -- TLS on ingress and egress adapters only. Internal edges are plaintext (assumes network isolation like VPC). This is the default for cloud deployments.

**TLS mode: `full`** -- TLS on every adapter, including internal. For zero-trust environments.

**TLS mode: `off`** -- No TLS anywhere. For local development.

**Implementation**: Python's `asyncio.start_server()` and `asyncio.open_connection()` both accept an `ssl` parameter natively. The adapter already uses these. Adding TLS is wrapping the existing connection code with an `ssl.SSLContext`.

**Control plane auth** -- Bearer token on `AdapterControlServer`. The management API (`/health`, `/metrics`, `/status`, `/routing`) currently has zero authentication. Add:
- Token from env var (`BATON_CONTROL_TOKEN`) or config
- 401 Unauthorized for missing/wrong token
- Optional: per-node tokens for multi-tenant circuits

**Contract-validated health** -- Health isn't just "HTTP 200." A service returning 200 with garbage data is unhealthy. If a node has a contract (OpenAPI spec), the health check can validate response schemas. This catches "green but wrong" failures that error-rate monitoring misses.

### Files to modify

- `src/baton/adapter.py` -- SSL context on `start()`, `open_connection()`, health checks
- `src/baton/adapter_control.py` -- bearer token auth middleware
- `src/baton/schemas.py` -- `TLSConfig`, `ControlAuthConfig` models
- `src/baton/lifecycle.py` -- propagate TLS/auth config to adapters on boot

### No-gos

- No custom CA infrastructure. Use standard PEM certs.
- No automatic cert generation or rotation (that's a separate tool's job).
- No breaking existing plaintext behavior -- TLS is opt-in.

---

## Cycle 3: Observability Bridge

### The insight

Baton already has a custom telemetry layer: `SignalRecord` per request, `AdapterMetrics` with percentiles, `TelemetryCollector` with Prometheus export. But this is a walled garden. Real deployments need to plug into existing observability stacks (Grafana, Jaeger, Datadog).

The clever part: baton's adapters see ALL traffic. They're the perfect place to inject trace context propagation without modifying any service code. The adapter reads incoming trace headers, creates child spans, and forwards them. Services don't need OpenTelemetry SDKs -- the mesh handles it.

### What to build

**OpenTelemetry trace propagation** -- adapters extract W3C `traceparent` headers from incoming requests, create a span for the proxy hop, and inject updated `traceparent` into outgoing requests. This gives you distributed tracing across the entire circuit without any service instrumentation.

**OTLP metric export** -- export `AdapterMetrics` as OTLP metrics to a collector endpoint. Reuse the existing `TelemetryCollector` but add an OTLP sink alongside the JSONL sink.

**OTLP trace export** -- export spans from the adapter's proxy operations to an OTLP collector.

**Grafana dashboard template** -- a JSON dashboard template that works with Prometheus/OTLP data. Shows: per-node throughput, latency percentiles, error rates, routing distribution, circuit topology visualization.

**Signal-based anomaly detection** -- instead of static thresholds (error rate > 5%), learn baseline behavior from the signal history and detect deviations. The `_latency_buffer` in `AdapterMetrics` already stores recent latencies. Add a simple z-score or percentile-shift detector. This feeds into the custodian's repair playbook.

**Telemetry equivalence classes** -- Span names derived from endpoint semantics, not raw HTTP paths. Derivable by default, overridable by intent.

The problem with OTEL defaults: `GET /users/{id}` and `GET /users/{id}/profile` merge into one bucket or explode into unbounded cardinality depending on parameterization. Neither is correct. The operator cares about semantic groups -- "user lookup" vs "profile fetch" -- because those map to different SLOs, different dashboards, different on-call rotations.

**Default derivation**: When no explicit class is declared, baton derives a telemetry class from the circuit topology:
- `{method}_{node}_{path_prefix}` -- e.g., `GET_api_users`, `POST_payments_charge`
- The node name IS the service boundary, so it naturally groups related endpoints
- Path is truncated to the first static segment (no parameter explosion)
- This produces sane defaults with predictable cardinality = O(nodes * methods * path_prefixes)

**Explicit override via contract or config**:
```yaml
nodes:
  - name: payments
    port: 8003
    telemetry:
      classes:
        - match: "POST /payments/charge"
          class: fraud-check
          slo_p95_ms: 200
          owner: fraud-team
        - match: "POST /payments/refund"
          class: refund-processing
          slo_p95_ms: 500
          owner: payments-team
```

When an override exists, the adapter uses `class` as the span name root instead of the derived default. The `slo_p95_ms` feeds into anomaly detection -- the custodian knows when a span class violates its budget without static threshold configuration. The `owner` field is metadata for alerting routing.

**Mock trace fidelity**: When baton collapses to mocks, mock servers emit spans with the same telemetry class structure. A developer running `baton up --mock` sees the same trace topology as production. This is unique -- no existing mesh preserves trace structure across mock/live boundaries.

**Edge-level telemetry**: Since baton puts policies on edges, each edge can carry its own telemetry class. The `api -> fraud-service` edge has a different span name than `api -> card-service`, even though both originate from `api`. The adapter creates the edge span automatically at the proxy hop.

### Files to modify

- `src/baton/adapter.py` -- trace header extraction/injection in `_handle_http_connection()`, telemetry class resolution
- `src/baton/telemetry.py` -- add OTLP export sink
- `src/baton/schemas.py` -- `ObservabilityConfig`, `TelemetryClass` models
- `src/baton/custodian.py` -- anomaly-aware repair decisions, SLO-based thresholds
- `src/baton/mock.py` -- emit mock traces with correct span structure
- New: `src/baton/otel.py` -- OpenTelemetry span/metric helpers, class derivation

### Dependencies

- `opentelemetry-api` and `opentelemetry-sdk` as optional extras (`pip install baton[otel]`)
- No dependency on specific collectors -- OTLP is the standard wire format

### No-gos

- No vendor lock-in. OTLP only, no direct Datadog/New Relic integrations.
- No replacing the existing JSONL telemetry. OTLP is additive.
- No requiring services to instrument themselves. The adapter handles it.

---

## Rabbit Holes

- **gRPC / HTTP/2 support**: The adapter currently does HTTP/1.1 and raw TCP. gRPC requires HTTP/2 framing. This is a significant protocol expansion and should be its own project, not part of production hardening.
- **Automatic certificate rotation**: Nice but complex. Let cert-manager or ACME handle it externally. Baton just reads cert files.
- **Multi-cluster federation**: Running circuits across multiple cloud regions/providers. Huge scope. Not now.
- **Custom protocol adapters** (protobuf, XML, SSH): Each is its own ProxyMode. Useful but not blocking production use. HTTP/TCP covers 90% of cases.

## Key Design Principles

1. **The circuit is the mesh.** No separate service discovery, no sidecar injection, no control plane server. The `baton.yaml` graph declares everything.
2. **Circuit trust.** The graph defines trust boundaries. Nodes connected by edges trust each other. TLS is for boundaries, not every hop.
3. **Adapters see everything.** Tracing, metrics, auth, rate limiting -- all happen at the adapter, not in service code. Services stay pure business logic.
4. **Edge-level policies.** Timeouts, retries, and circuit breakers belong to the relationship between services, not to individual services.
5. **Mock collapse is a superpower.** Production config + mock collapse = test any service in isolation with the full topology around it. No other mesh can do this.
6. **Git is the state store.** `baton export` -> commit -> `baton apply` elsewhere. No external state management.
7. **Derivable by default, overridable by intent.** Telemetry classes, span names, SLO thresholds -- generate sensible defaults from topology + contracts. Override only when someone has a semantic reason to.

## Existing Code to Reuse

- `src/baton/adapter.py` -- asyncio server/connection (already supports ssl parameter)
- `src/baton/adapter_control.py` -- management API (add auth to `_handle()`)
- `src/baton/config.py` -- YAML parser (extend `_parse_circuit()` / `_serialize_circuit()`)
- `src/baton/state.py` -- `.baton/` persistence (reuse for export/import)
- `src/baton/telemetry.py` -- metric collection (add OTLP sink)
- `src/baton/custodian.py` -- repair playbook (add anomaly detection)
- `src/baton/routing.py` -- routing builders (canary, ab_split, etc.)
- `src/baton/signals.py` -- signal aggregation + per-path stats

## Adoption Context

- Source files: 26
- Functions: 247
- Test files: 25
- Coverage: 51%
- Security findings: 4
