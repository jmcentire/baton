# === Baton Adapter - Async Reverse Proxy (src_baton_adapter) v1 ===
#  Dependencies: asyncio, logging, time, datetime, random, baton.schemas
# Async reverse proxy adapter that listens on a node's assigned address and forwards traffic to backend services. Supports both HTTP and raw TCP proxying with routing strategies, health checks, metrics collection, and signal recording.

# Module invariants:
#   - AdapterMetrics._LATENCY_BUFFER_MAX = 1000
#   - Ingress nodes always record signals regardless of record_signals parameter
#   - Backend port must be > 0 to be considered configured
#   - HTTP health check uses /health as default path unless overridden in node metadata
#   - TCP health check timeout is 5.0 seconds
#   - HTTP message read timeout is 30.0 seconds
#   - Default drain timeout is 30.0 seconds
#   - Pipe buffer size is 65536 bytes

class BackendTarget:
    """Where the adapter forwards traffic"""
    host: str                                # required, Backend host address
    port: int                                # required, Backend port number

class AdapterMetrics:
    """Lightweight request and latency counters"""
    requests_total: int                      # required
    requests_failed: int                     # required
    bytes_forwarded: int                     # required
    last_request_at: float                   # required
    last_latency_ms: float                   # required
    status_2xx: int                          # required
    status_3xx: int                          # required
    status_4xx: int                          # required
    status_5xx: int                          # required
    active_connections: int                  # required
    _latency_buffer: list                    # required, Buffer storing recent latency values

class Adapter:
    """Async reverse proxy for a single node with routing, health checks, and metrics"""
    pass

def _now_iso() -> str:
    """
    Get current UTC timestamp in ISO format

    Postconditions:
      - Returns ISO 8601 formatted UTC timestamp string

    Side effects: Reads system time
    Idempotent: no
    """
    ...

def is_configured() -> bool:
    """
    Check if backend target has a valid port configured

    Postconditions:
      - Returns True if port > 0, False otherwise

    Side effects: none
    Idempotent: no
    """
    ...

def record_latency(
    self: AdapterMetrics,
    latency_ms: float,
) -> None:
    """
    Record a latency measurement and maintain bounded buffer

    Postconditions:
      - Latency appended to buffer
      - Buffer trimmed to max 1000 entries if exceeded

    Side effects: Mutates _latency_buffer
    Idempotent: no
    """
    ...

def record_status(
    self: AdapterMetrics,
    status_code: int,
) -> None:
    """
    Increment the appropriate HTTP status code counter based on status code

    Postconditions:
      - Increments status_2xx, status_3xx, status_4xx, or status_5xx based on code range

    Side effects: Mutates status counter fields
    Idempotent: no
    """
    ...

def p50(
    self: AdapterMetrics,
) -> float:
    """
    Calculate 50th percentile latency

    Postconditions:
      - Returns 50th percentile of latency buffer, or 0.0 if empty

    Side effects: none
    Idempotent: no
    """
    ...

def p95(
    self: AdapterMetrics,
) -> float:
    """
    Calculate 95th percentile latency

    Postconditions:
      - Returns 95th percentile of latency buffer, or 0.0 if empty

    Side effects: none
    Idempotent: no
    """
    ...

def p99(
    self: AdapterMetrics,
) -> float:
    """
    Calculate 99th percentile latency

    Postconditions:
      - Returns 99th percentile of latency buffer, or 0.0 if empty

    Side effects: none
    Idempotent: no
    """
    ...

def _percentile(
    self: AdapterMetrics,
    pct: int,
) -> float:
    """
    Calculate percentile from latency buffer

    Postconditions:
      - Returns percentile value from sorted buffer, or 0.0 if buffer empty

    Side effects: none
    Idempotent: no
    """
    ...

def __init__(
    self: Adapter,
    node: NodeSpec,
    record_signals: bool = True,
) -> None:
    """
    Initialize Adapter with node specification and optional signal recording

    Postconditions:
      - Adapter initialized with node spec
      - Signal recording enabled if record_signals=True or node.role==INGRESS
      - Empty backend target created
      - Metrics initialized
      - Server not started

    Side effects: Creates asyncio.Event
    Idempotent: no
    """
    ...

def node(
    self: Adapter,
) -> NodeSpec:
    """
    Get the NodeSpec for this adapter

    Postconditions:
      - Returns the NodeSpec

    Side effects: none
    Idempotent: no
    """
    ...

def metrics(
    self: Adapter,
) -> AdapterMetrics:
    """
    Get the adapter metrics

    Postconditions:
      - Returns the AdapterMetrics instance

    Side effects: none
    Idempotent: no
    """
    ...

def target_metrics(
    self: Adapter,
) -> dict[str, AdapterMetrics]:
    """
    Get per-target metrics dictionary

    Postconditions:
      - Returns copy of target_metrics dictionary

    Side effects: none
    Idempotent: no
    """
    ...

def signals(
    self: Adapter,
) -> list[SignalRecord]:
    """
    Get copy of signal records

    Postconditions:
      - Returns copy of signal buffer

    Side effects: none
    Idempotent: no
    """
    ...

def drain_signals(
    self: Adapter,
) -> list[SignalRecord]:
    """
    Return and clear the signal buffer

    Postconditions:
      - Returns copy of signal buffer
      - Signal buffer is cleared

    Side effects: Clears internal signal buffer
    Idempotent: no
    """
    ...

def backend(
    self: Adapter,
) -> BackendTarget:
    """
    Get current backend target

    Postconditions:
      - Returns current BackendTarget

    Side effects: none
    Idempotent: no
    """
    ...

def routing(
    self: Adapter,
) -> RoutingConfig | None:
    """
    Get current routing configuration

    Postconditions:
      - Returns current RoutingConfig or None

    Side effects: none
    Idempotent: no
    """
    ...

def is_running(
    self: Adapter,
) -> bool:
    """
    Check if adapter server is running

    Postconditions:
      - Returns True if server exists and is serving, False otherwise

    Side effects: none
    Idempotent: no
    """
    ...

def set_backend(
    self: Adapter,
    target: BackendTarget,
) -> None:
    """
    Atomically swap the backend target

    Preconditions:
      - Routing config is not locked

    Postconditions:
      - Backend updated to new target
      - Draining flag cleared
      - Drain event cleared

    Errors:
      - RoutingLocked (RuntimeError): _routing is not None and _routing.locked

    Side effects: Updates backend target, Clears draining state
    Idempotent: no
    """
    ...

def set_routing(
    self: Adapter,
    config: RoutingConfig,
) -> None:
    """
    Set routing configuration

    Preconditions:
      - Current routing config is not locked

    Postconditions:
      - Routing config updated
      - Target metrics cleared

    Errors:
      - RoutingLocked (RuntimeError): _routing is not None and _routing.locked

    Side effects: Updates routing config, Clears target metrics
    Idempotent: no
    """
    ...

def clear_routing(
    self: Adapter,
) -> None:
    """
    Remove routing configuration

    Preconditions:
      - Current routing config is not locked

    Postconditions:
      - Routing config set to None

    Errors:
      - RoutingLocked (RuntimeError): _routing is not None and _routing.locked

    Side effects: Clears routing config
    Idempotent: no
    """
    ...

def start(
    self: Adapter,
) -> None:
    """
    Start listening on the node's assigned address

    Postconditions:
      - Server started on node's host:port
      - Server is listening for connections

    Side effects: Creates asyncio.Server, Binds to network socket, Logs startup message
    Idempotent: no
    """
    ...

def drain(
    self: Adapter,
    timeout: float = 30.0,
) -> None:
    """
    Stop accepting new connections and wait for active ones to finish

    Postconditions:
      - Draining flag set
      - Waits for active connections to complete or timeout

    Side effects: Sets draining flag, May wait for connections, May log warning on timeout
    Idempotent: no
    """
    ...

def stop(
    self: Adapter,
) -> None:
    """
    Shutdown the adapter server

    Postconditions:
      - Server closed and cleaned up
      - Server set to None

    Side effects: Closes server socket, Waits for server shutdown
    Idempotent: no
    """
    ...

def health_check(
    self: Adapter,
) -> HealthCheck:
    """
    Check backend reachability using HTTP or TCP based on proxy mode

    Postconditions:
      - Returns HealthCheck with verdict UNKNOWN/HEALTHY/UNHEALTHY/DEGRADED

    Side effects: May attempt network connection to backend
    Idempotent: no
    """
    ...

def _tcp_health_check(
    self: Adapter,
) -> HealthCheck:
    """
    Check if backend is reachable via TCP connect

    Postconditions:
      - Returns HealthCheck with HEALTHY verdict on successful connection
      - Returns UNHEALTHY verdict on connection failure
      - Includes latency measurement

    Side effects: Opens TCP connection to backend, Closes connection
    Idempotent: no
    """
    ...

def _http_health_check(
    self: Adapter,
) -> HealthCheck:
    """
    Check backend health via HTTP GET to health endpoint

    Postconditions:
      - Returns HealthCheck with verdict based on HTTP status code
      - 2xx=HEALTHY, 5xx=UNHEALTHY, other=DEGRADED
      - Includes latency measurement

    Side effects: Opens HTTP connection, Sends GET request, Reads response, Closes connection
    Idempotent: no
    """
    ...

def _select_backend(
    self: Adapter,
    request_data: bytes | None = None,
) -> BackendTarget | None:
    """
    Select a backend based on routing config or fall through to default

    Postconditions:
      - Returns selected BackendTarget or None

    Side effects: none
    Idempotent: no
    """
    ...

def _select_backend_named(
    self: Adapter,
    request_data: bytes | None = None,
) -> tuple[BackendTarget | None, str | None]:
    """
    Select a backend and return both target and name

    Postconditions:
      - Returns (target, target_name) tuple
      - target_name is routing target name or None

    Side effects: none
    Idempotent: no
    """
    ...

def _select_weighted(
    targets: list,
) -> BackendTarget:
    """
    Pick a target based on cumulative weights

    Postconditions:
      - Returns BackendTarget selected by weighted random selection

    Side effects: Uses random number generation
    Idempotent: no
    """
    ...

def _select_weighted_named(
    targets: list,
) -> tuple[BackendTarget, str | None]:
    """
    Pick a target based on cumulative weights, returning target and name

    Postconditions:
      - Returns (target, name) selected by weighted random selection
      - Falls back to last target if roll exceeds all weights

    Side effects: Uses random number generation
    Idempotent: no
    """
    ...

def _select_by_header(
    self: Adapter,
    request_data: bytes,
    config: RoutingConfig,
    targets_by_name: dict,
) -> BackendTarget:
    """
    Route based on header value matching rules

    Postconditions:
      - Returns target matching header rule or default target

    Side effects: none
    Idempotent: no
    """
    ...

def _select_by_header_named(
    self: Adapter,
    request_data: bytes,
    config: RoutingConfig,
    targets_by_name: dict,
) -> tuple[BackendTarget, str | None]:
    """
    Route based on header value, returning target and name

    Postconditions:
      - Returns (target, name) matching header rule or default
      - Falls back to self._backend if no match

    Side effects: none
    Idempotent: no
    """
    ...

def _parse_headers(
    data: bytes,
) -> dict[str, str]:
    """
    Extract header key:value pairs from raw HTTP request bytes

    Postconditions:
      - Returns dictionary of lowercase header keys to values
      - Returns empty dict on parse error

    Side effects: none
    Idempotent: no
    """
    ...

def _decrement_connections(
    self: Adapter,
) -> None:
    """
    Decrement active connection count and signal drain event if needed

    Postconditions:
      - Active connections decremented
      - Drain event set if draining and connections reach 0

    Side effects: Mutates connection counter, May set drain event
    Idempotent: no
    """
    ...

def _handle_tcp_connection(
    self: Adapter,
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
) -> None:
    """
    Generic TCP forwarding with bidirectional byte pipe

    Postconditions:
      - Traffic forwarded bidirectionally until EOF
      - Metrics updated
      - Connections closed

    Side effects: Opens backend connection, Forwards bytes, Updates metrics, Logs errors
    Idempotent: no
    """
    ...

def _handle_http_connection(
    self: Adapter,
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
) -> None:
    """
    HTTP forwarding: read request, forward to backend, return response

    Postconditions:
      - Request forwarded to selected backend
      - Response returned to client
      - Metrics updated
      - Signals recorded if enabled

    Side effects: Reads HTTP request, Selects backend, Forwards request, Updates metrics, Records signals, Logs errors
    Idempotent: no
    """
    ...

def _pipe(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """
    Copy bytes from reader to writer until EOF

    Postconditions:
      - All available bytes copied from reader to writer until EOF

    Side effects: Reads from reader, Writes to writer
    Idempotent: no
    """
    ...

def _read_http_message(
    reader: asyncio.StreamReader,
) -> bytes | None:
    """
    Read a full HTTP/1.1 message including headers and body via Content-Length

    Postconditions:
      - Returns complete HTTP message (headers + body) or None on timeout/error

    Side effects: Reads from stream
    Idempotent: no
    """
    ...

def _parse_request_line(
    data: bytes,
) -> tuple[str, str]:
    """
    Extract HTTP method and path from first line of request

    Postconditions:
      - Returns (method, path) tuple
      - Returns ('', '') on parse error

    Side effects: none
    Idempotent: no
    """
    ...

def _parse_status_code(
    data: bytes | None,
) -> int:
    """
    Extract HTTP status code from response

    Postconditions:
      - Returns status code integer
      - Returns 0 if data is None or parse fails

    Side effects: none
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['BackendTarget', 'AdapterMetrics', 'Adapter', '_now_iso', 'is_configured', 'record_latency', 'record_status', 'p50', 'p95', 'p99', '_percentile', 'node', 'metrics', 'target_metrics', 'signals', 'drain_signals', 'backend', 'routing', 'is_running', 'set_backend', 'set_routing', 'clear_routing', 'start', 'drain', 'stop', 'health_check', '_tcp_health_check', '_http_health_check', '_select_backend', '_select_backend_named', '_select_weighted', '_select_weighted_named', '_select_by_header', '_select_by_header_named', '_parse_headers', '_decrement_connections', '_handle_tcp_connection', '_handle_http_connection', '_pipe', '_read_http_message', '_parse_request_line', '_parse_status_code']
