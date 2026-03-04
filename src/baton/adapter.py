"""Async reverse proxy adapter.

Each adapter listens on a node's assigned address and forwards traffic
to whatever service is slotted in behind it. Supports HTTP and raw TCP.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import random

from baton.schemas import (
    EdgePolicy,
    HealthCheck,
    HealthVerdict,
    NodeRole,
    NodeSpec,
    ProxyMode,
    RoutingConfig,
    RoutingStrategy,
    SignalRecord,
    TelemetryClassRule,
)
from baton.tracing import (
    SpanData,
    SpanExporter,
    TraceContext,
    format_traceparent,
    generate_span_id,
    generate_trace_id,
    parse_traceparent,
    resolve_telemetry_class,
)

logger = logging.getLogger(__name__)


@dataclass
class BackendTarget:
    """Where the adapter forwards traffic."""

    host: str = "127.0.0.1"
    port: int = 0

    @property
    def is_configured(self) -> bool:
        return self.port > 0


@dataclass
class AdapterMetrics:
    """Lightweight counters."""

    requests_total: int = 0
    requests_failed: int = 0
    bytes_forwarded: int = 0
    last_request_at: float = 0.0
    last_latency_ms: float = 0.0
    status_2xx: int = 0
    status_3xx: int = 0
    status_4xx: int = 0
    status_5xx: int = 0
    active_connections: int = 0
    _latency_buffer: list = field(default_factory=list)

    _LATENCY_BUFFER_MAX = 1000

    def record_latency(self, latency_ms: float) -> None:
        self._latency_buffer.append(latency_ms)
        if len(self._latency_buffer) > self._LATENCY_BUFFER_MAX:
            self._latency_buffer = self._latency_buffer[-self._LATENCY_BUFFER_MAX:]

    def record_status(self, status_code: int) -> None:
        if 200 <= status_code < 300:
            self.status_2xx += 1
        elif 300 <= status_code < 400:
            self.status_3xx += 1
        elif 400 <= status_code < 500:
            self.status_4xx += 1
        elif 500 <= status_code < 600:
            self.status_5xx += 1

    def p50(self) -> float:
        return self._percentile(50)

    def p95(self) -> float:
        return self._percentile(95)

    def p99(self) -> float:
        return self._percentile(99)

    def _percentile(self, pct: int) -> float:
        if not self._latency_buffer:
            return 0.0
        s = sorted(self._latency_buffer)
        idx = int(len(s) * pct / 100)
        idx = min(idx, len(s) - 1)
        return s[idx]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Adapter:
    """Async reverse proxy for a single node.

    Lifecycle:
        adapter = Adapter(node_spec)
        await adapter.start()
        adapter.set_backend(target)
        adapter.set_backend(new_target)  # hot-swap
        await adapter.drain()
        await adapter.stop()
    """

    def __init__(self, node: NodeSpec, record_signals: bool = True, ssl_context: "ssl.SSLContext | None" = None):
        self._node = node
        self._backend = BackendTarget()
        self._routing: RoutingConfig | None = None
        self._server: asyncio.Server | None = None
        # Ingress nodes always record signals regardless of arg
        self._record_signals = record_signals or node.role == NodeRole.INGRESS
        self._signals: list[SignalRecord] = []
        self._metrics = AdapterMetrics()
        self._target_metrics: dict[str, AdapterMetrics] = {}
        self._draining = False
        self._active_connections = 0
        self._drain_event = asyncio.Event()
        self._policy: EdgePolicy | None = None
        self._cb_failures: dict[str, int] = {}      # target_key -> consecutive failures
        self._cb_open: dict[str, float] = {}         # target_key -> time.monotonic when opened
        self._ssl_context = ssl_context
        self._span_exporter: SpanExporter | None = None
        self._telemetry_rules: list[TelemetryClassRule] = []
        self._span_buffer: list[SpanData] = []

    @property
    def node(self) -> NodeSpec:
        return self._node

    @property
    def metrics(self) -> AdapterMetrics:
        return self._metrics

    @property
    def target_metrics(self) -> dict[str, AdapterMetrics]:
        return dict(self._target_metrics)

    @property
    def signals(self) -> list[SignalRecord]:
        return list(self._signals)

    def drain_signals(self) -> list[SignalRecord]:
        """Return and clear the signal buffer."""
        drained = self._signals[:]
        self._signals.clear()
        return drained

    @property
    def backend(self) -> BackendTarget:
        return self._backend

    @property
    def routing(self) -> RoutingConfig | None:
        return self._routing

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    def set_backend(self, target: BackendTarget) -> None:
        """Atomically swap the backend target."""
        if self._routing and self._routing.locked:
            raise RuntimeError("Cannot set backend: routing config is locked")
        self._backend = target
        self._draining = False
        self._drain_event.clear()

    def set_routing(self, config: RoutingConfig) -> None:
        """Set routing configuration. Raises if current config is locked."""
        if self._routing and self._routing.locked:
            raise RuntimeError("Cannot set routing: current config is locked")
        self._routing = config
        self._target_metrics = {}

    def clear_routing(self) -> None:
        """Remove routing configuration. Raises if locked."""
        if self._routing and self._routing.locked:
            raise RuntimeError("Cannot clear routing: config is locked")
        self._routing = None

    def set_policy(self, policy: EdgePolicy | None) -> None:
        """Set edge policy for timeout/retry/circuit-breaker enforcement."""
        self._policy = policy

    @property
    def policy(self) -> EdgePolicy | None:
        return self._policy

    def set_span_exporter(self, exporter: SpanExporter | None) -> None:
        """Set the span exporter for distributed tracing."""
        self._span_exporter = exporter

    def set_telemetry_rules(self, rules: list[TelemetryClassRule]) -> None:
        """Set telemetry class rules for this adapter."""
        self._telemetry_rules = list(rules)

    def drain_spans(self) -> list[SpanData]:
        """Return and clear the span buffer."""
        drained = self._span_buffer[:]
        self._span_buffer.clear()
        return drained

    async def start(self) -> None:
        """Start listening on the node's assigned address."""
        from baton.protocols import ConnectionContext, get_handler
        # Ensure all protocol handlers are registered
        import baton.protocols.http  # noqa: F401
        import baton.protocols.tcp  # noqa: F401
        import baton.protocols.protobuf  # noqa: F401
        import baton.protocols.soap  # noqa: F401

        handler_cls = get_handler(str(self._node.proxy_mode))
        if handler_cls is None:
            raise ValueError(f"No handler for proxy mode: {self._node.proxy_mode}")
        proto_handler = handler_cls()
        ctx = ConnectionContext(node=self._node, adapter=self)
        self._protocol_handler = proto_handler
        self._protocol_ctx = ctx

        async def _dispatch(reader, writer):
            await proto_handler.handle_connection(reader, writer, ctx)

        handler = _dispatch
        self._server = await asyncio.start_server(
            handler, self._node.host, self._node.port,
            ssl=self._ssl_context,
            limit=self.MAX_HEADER_SIZE,
        )
        logger.info(
            f"Adapter [{self._node.name}] listening on "
            f"{self._node.host}:{self._node.port} ({self._node.proxy_mode})"
        )

    async def drain(self, timeout: float = 30.0) -> None:
        """Stop accepting new connections, wait for active ones to finish."""
        self._draining = True
        if self._active_connections > 0:
            try:
                await asyncio.wait_for(self._drain_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    f"Adapter [{self._node.name}] drain timed out "
                    f"with {self._active_connections} active"
                )

    async def stop(self) -> None:
        """Shutdown the adapter server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def health_check(self) -> HealthCheck:
        """Check backend reachability via the registered protocol handler."""
        if not self._backend.is_configured:
            return HealthCheck(
                node_name=self._node.name,
                verdict=HealthVerdict.UNKNOWN,
                detail="No backend configured",
                timestamp=_now_iso(),
            )
        handler = getattr(self, "_protocol_handler", None)
        if handler is not None:
            metadata = dict(self._node.metadata) if self._node.metadata else {}
            metadata["_node_name"] = self._node.name
            metadata["_adapter_ref"] = self  # For HTTP handler delegation
            return await handler.health_check(
                self._backend.host, self._backend.port, metadata
            )
        # Fallback if start() wasn't called -- use mode-appropriate check
        if self._node.proxy_mode == ProxyMode.HTTP:
            return await self._http_health_check()
        return await self._tcp_health_check()

    async def _tcp_health_check(self) -> HealthCheck:
        """Check if the backend is reachable via TCP connect."""
        start = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._backend.host, self._backend.port),
                timeout=5.0,
            )
            writer.close()
            await writer.wait_closed()
            latency = (time.monotonic() - start) * 1000
            return HealthCheck(
                node_name=self._node.name,
                verdict=HealthVerdict.HEALTHY,
                latency_ms=latency,
                timestamp=_now_iso(),
            )
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return HealthCheck(
                node_name=self._node.name,
                verdict=HealthVerdict.UNHEALTHY,
                latency_ms=latency,
                detail=str(e),
                timestamp=_now_iso(),
            )

    _SAFE_PATH_RE = re.compile(r"^/[a-zA-Z0-9/_.\-~%]*$")

    async def _http_health_check(self) -> HealthCheck:
        """Check backend health via HTTP GET /health."""
        health_path = (self._node.metadata or {}).get("health_path", "/health")
        if not self._SAFE_PATH_RE.match(health_path):
            return HealthCheck(
                node_name=self._node.name,
                verdict=HealthVerdict.UNKNOWN,
                detail=f"Invalid health_path: {health_path!r}",
                timestamp=_now_iso(),
            )
        start = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._backend.host, self._backend.port),
                timeout=5.0,
            )
            request = (
                f"GET {health_path} HTTP/1.1\r\n"
                f"Host: {self._backend.host}:{self._backend.port}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode("ascii")
            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            writer.close()
            await writer.wait_closed()

            latency = (time.monotonic() - start) * 1000
            status_code = self._parse_status_code(response)

            if 200 <= status_code < 300:
                verdict = HealthVerdict.HEALTHY
            elif 500 <= status_code < 600:
                verdict = HealthVerdict.UNHEALTHY
            elif status_code > 0:
                verdict = HealthVerdict.DEGRADED
            else:
                # Could not parse status — fall back to TCP result (connected = healthy)
                verdict = HealthVerdict.HEALTHY

            return HealthCheck(
                node_name=self._node.name,
                verdict=verdict,
                latency_ms=latency,
                detail=f"HTTP {status_code}" if status_code else None,
                timestamp=_now_iso(),
            )
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return HealthCheck(
                node_name=self._node.name,
                verdict=HealthVerdict.UNHEALTHY,
                latency_ms=latency,
                detail=str(e),
                timestamp=_now_iso(),
            )

    def _select_backend(self, request_data: bytes | None = None) -> BackendTarget | None:
        """Select a backend based on routing config, or fall through to self._backend."""
        target, _ = self._select_backend_named(request_data)
        return target

    def _select_backend_named(
        self, request_data: bytes | None = None
    ) -> tuple[BackendTarget | None, str | None]:
        """Select a backend and return (target, target_name).

        target_name is the RoutingTarget.name (e.g. "stable", "canary") or None
        when no routing config is active.
        """
        if self._routing is None:
            return (self._backend if self._backend.is_configured else None, None)

        targets_by_name = {t.name: t for t in self._routing.targets}

        if self._routing.strategy in (RoutingStrategy.WEIGHTED, RoutingStrategy.CANARY):
            return self._select_weighted_named(self._routing.targets)
        elif self._routing.strategy == RoutingStrategy.HEADER and request_data:
            return self._select_by_header_named(request_data, self._routing, targets_by_name)

        return (self._backend if self._backend.is_configured else None, None)

    @staticmethod
    def _select_weighted(targets: list) -> BackendTarget:
        """Pick a target based on cumulative weights."""
        target, _ = Adapter._select_weighted_named(targets)
        return target

    @staticmethod
    def _select_weighted_named(targets: list) -> tuple[BackendTarget, str | None]:
        """Pick a target based on cumulative weights, returning (target, name)."""
        roll = random.randint(1, 100)
        cumulative = 0
        for t in targets:
            cumulative += t.weight
            if roll <= cumulative:
                return BackendTarget(host=t.host, port=t.port), t.name
        # Fallback to last target
        last = targets[-1]
        return BackendTarget(host=last.host, port=last.port), last.name

    def _select_by_header(
        self,
        request_data: bytes,
        config: RoutingConfig,
        targets_by_name: dict,
    ) -> BackendTarget:
        """Route based on header value matching rules."""
        target, _ = self._select_by_header_named(request_data, config, targets_by_name)
        return target

    def _select_by_header_named(
        self,
        request_data: bytes,
        config: RoutingConfig,
        targets_by_name: dict,
    ) -> tuple[BackendTarget, str | None]:
        """Route based on header value, returning (target, name)."""
        headers = self._parse_headers(request_data)
        for rule in config.rules:
            if headers.get(rule.header.lower()) == rule.value:
                t = targets_by_name.get(rule.target)
                if t:
                    return BackendTarget(host=t.host, port=t.port), t.name
        # Fall back to default target
        t = targets_by_name.get(config.default_target)
        if t:
            return BackendTarget(host=t.host, port=t.port), t.name
        return self._backend, None

    MAX_HEADERS = 100
    MAX_HEADER_VALUE_LEN = 8192

    @staticmethod
    def _parse_headers(data: bytes) -> dict[str, str]:
        """Extract header key:value pairs from raw HTTP request bytes."""
        result: dict[str, str] = {}
        try:
            header_section = data.split(b"\r\n\r\n", 1)[0]
            lines = header_section.split(b"\r\n")
            # Skip request line (first line), limit header count
            for line in lines[1:Adapter.MAX_HEADERS + 1]:
                if b":" in line:
                    key, val = line.split(b":", 1)
                    key_str = key.strip().decode("ascii", errors="replace").lower()
                    val_str = val.strip().decode("ascii", errors="replace")
                    if len(val_str) <= Adapter.MAX_HEADER_VALUE_LEN:
                        result[key_str] = val_str
        except Exception:
            pass
        return result

    def _decrement_connections(self) -> None:
        self._active_connections -= 1
        if self._draining and self._active_connections <= 0:
            self._drain_event.set()

    async def _handle_http_connection(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        """HTTP forwarding: read request, forward, return response."""
        if self._draining or (not self._backend.is_configured and self._routing is None):
            client_writer.write(
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Length: 0\r\n"
                b"Connection: close\r\n\r\n"
            )
            await client_writer.drain()
            client_writer.close()
            return

        self._active_connections += 1
        start = time.monotonic()
        try:
            request_data = await self._read_http_message(client_reader)
            if not request_data:
                return

            # Extract traceparent from inbound request
            headers = self._parse_headers(request_data)
            parent_ctx = parse_traceparent(headers.get("traceparent", ""))
            trace_id = parent_ctx.trace_id if parent_ctx else generate_trace_id()
            span_id = generate_span_id()

            target, target_name = self._select_backend_named(request_data)
            if target is None or not target.is_configured:
                client_writer.write(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )
                await client_writer.drain()
                return

            target_key = f"{target.host}:{target.port}"
            policy = self._policy
            conn_timeout_s = policy.timeout_ms / 1000 if policy else 30.0

            # Circuit breaker check
            if policy and policy.circuit_breaker_threshold > 0:
                failures = self._cb_failures.get(target_key, 0)
                if failures >= policy.circuit_breaker_threshold:
                    cooldown = policy.timeout_ms / 1000
                    opened_at = self._cb_open.get(target_key, 0)
                    if time.monotonic() - opened_at < cooldown:
                        client_writer.write(
                            b"HTTP/1.1 503 Service Unavailable\r\n"
                            b"Content-Length: 0\r\n"
                            b"Connection: close\r\n\r\n"
                        )
                        await client_writer.drain()
                        self._metrics.requests_failed += 1
                        return
                    # Cooldown expired -- allow a probe request through

            # Inject traceparent into outbound request
            child_ctx = TraceContext(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_ctx.span_id if parent_ctx else "",
            )
            outbound_data = _inject_traceparent(request_data, format_traceparent(child_ctx))

            max_attempts = 1 + (policy.retries if policy else 0)
            backoff_ms = policy.retry_backoff_ms if policy else 100
            response_data = None
            succeeded = False

            for attempt in range(max_attempts):
                backend_writer = None
                try:
                    backend_reader, backend_writer = await asyncio.wait_for(
                        asyncio.open_connection(target.host, target.port),
                        timeout=conn_timeout_s,
                    )
                    backend_writer.write(outbound_data)
                    await backend_writer.drain()

                    response_data = await self._read_http_message(backend_reader)
                    if not response_data:
                        # Connected but got no response -- treat as failure
                        raise OSError("Empty response from backend")

                    client_writer.write(response_data)
                    await client_writer.drain()

                    # Success -- reset circuit breaker
                    self._cb_failures[target_key] = 0
                    succeeded = True
                    break
                except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as conn_err:
                    self._cb_failures[target_key] = self._cb_failures.get(target_key, 0) + 1
                    if policy and policy.circuit_breaker_threshold > 0:
                        if self._cb_failures[target_key] >= policy.circuit_breaker_threshold:
                            self._cb_open[target_key] = time.monotonic()
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(backoff_ms * (attempt + 1) / 1000)
                    logger.debug(f"[{self._node.name}] attempt {attempt+1}/{max_attempts} failed: {conn_err}")
                finally:
                    if backend_writer:
                        backend_writer.close()
                        backend_writer = None

            if not succeeded:
                client_writer.write(
                    b"HTTP/1.1 502 Bad Gateway\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )
                await client_writer.drain()
                self._metrics.requests_failed += 1
                return

            latency = (time.monotonic() - start) * 1000
            self._metrics.requests_total += 1
            self._metrics.last_latency_ms = latency
            self._metrics.last_request_at = time.time()
            self._metrics.bytes_forwarded += len(request_data) + len(response_data or b"")
            self._metrics.record_latency(latency)
            status_code = self._parse_status_code(response_data) if response_data else 0
            if status_code:
                self._metrics.record_status(status_code)

            # Per-target metrics
            if target_name is not None:
                if target_name not in self._target_metrics:
                    self._target_metrics[target_name] = AdapterMetrics()
                tm = self._target_metrics[target_name]
                tm.requests_total += 1
                tm.last_latency_ms = latency
                tm.last_request_at = time.time()
                tm.bytes_forwarded += len(request_data) + len(response_data or b"")
                tm.record_latency(latency)
                if status_code:
                    tm.record_status(status_code)

            # Create span data for tracing
            method, path = self._parse_request_line(request_data)
            if self._span_exporter is not None:
                tel_class = resolve_telemetry_class(
                    method, path, self._node.name, self._telemetry_rules,
                )
                span = SpanData(
                    name=tel_class,
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_ctx.span_id if parent_ctx else "",
                    start_time_ns=int(start * 1e9),
                    end_time_ns=int(time.monotonic() * 1e9),
                    attributes={
                        "http.method": method,
                        "http.path": path,
                        "http.status_code": str(status_code),
                        "target": target_key,
                    },
                    status="ok" if 200 <= status_code < 400 else "error",
                    node_name=self._node.name,
                )
                self._span_buffer.append(span)

            if self._record_signals:
                status = self._parse_status_code(response_data) if response_data else 0
                self._signals.append(
                    SignalRecord(
                        node_name=self._node.name,
                        direction="inbound",
                        method=method,
                        path=path,
                        status_code=status,
                        body_bytes=len(response_data or b""),
                        latency_ms=latency,
                        timestamp=_now_iso(),
                        trace_id=trace_id,
                        span_id=span_id,
                    )
                )

        except Exception as e:
            self._metrics.requests_failed += 1
            logger.debug(f"[{self._node.name}] HTTP proxy error: {e}")
        finally:
            self._decrement_connections()
            client_writer.close()

    MAX_HEADER_SIZE = 16384  # 16KB

    @staticmethod
    async def _read_http_message(reader: asyncio.StreamReader) -> bytes | None:
        """Read a full HTTP/1.1 message (headers + body via Content-Length)."""
        try:
            headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30.0)
            if len(headers) > Adapter.MAX_HEADER_SIZE:
                return None
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionResetError):
            return None

        content_length = 0
        for line in headers.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                try:
                    content_length = int(line.split(b":", 1)[1].strip())
                except ValueError:
                    pass
                break

        body = b""
        if content_length > 0:
            try:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=30.0
                )
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                return None

        return headers + body

    @staticmethod
    def _parse_request_line(data: bytes) -> tuple[str, str]:
        """Extract method and path from the first line of an HTTP request."""
        try:
            first_line = data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
            parts = first_line.split(" ")
            if len(parts) >= 2:
                return parts[0], parts[1]
        except Exception:
            pass
        return "", ""

    @staticmethod
    def _parse_status_code(data: bytes | None) -> int:
        """Extract status code from HTTP response."""
        if not data:
            return 0
        try:
            first_line = data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
            parts = first_line.split(" ")
            if len(parts) >= 2:
                return int(parts[1])
        except Exception:
            pass
        return 0


def _inject_traceparent(request_data: bytes, traceparent: str) -> bytes:
    """Insert traceparent header into HTTP request bytes.

    Finds the \\r\\n\\r\\n boundary and inserts the header before it.
    Replaces existing traceparent header if present.
    """
    header_line = f"traceparent: {traceparent}\r\n".encode("ascii")
    # Remove existing traceparent header if present
    lines = request_data.split(b"\r\n")
    filtered = [line for line in lines if not line.lower().startswith(b"traceparent:")]
    request_data = b"\r\n".join(filtered)
    # Insert before the header/body boundary
    parts = request_data.split(b"\r\n\r\n", 1)
    if len(parts) == 2:
        return parts[0] + b"\r\n" + header_line + b"\r\n" + parts[1]
    return request_data
