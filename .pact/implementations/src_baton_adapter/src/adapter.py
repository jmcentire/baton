"""Async reverse proxy adapter.

Each adapter listens on a node's assigned address and forwards traffic
to whatever service is slotted in behind it. Supports HTTP and raw TCP.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import random

from baton.schemas import (
    HealthCheck,
    HealthVerdict,
    NodeRole,
    NodeSpec,
    ProxyMode,
    RoutingConfig,
    RoutingStrategy,
    SignalRecord,
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

    def __init__(self, node: NodeSpec, record_signals: bool = True):
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

    async def start(self) -> None:
        """Start listening on the node's assigned address."""
        handler = (
            self._handle_http_connection
            if self._node.proxy_mode == ProxyMode.HTTP
            else self._handle_tcp_connection
        )
        self._server = await asyncio.start_server(
            handler, self._node.host, self._node.port
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
        """Check backend reachability. Uses HTTP for HTTP-mode, TCP otherwise."""
        if not self._backend.is_configured:
            return HealthCheck(
                node_name=self._node.name,
                verdict=HealthVerdict.UNKNOWN,
                detail="No backend configured",
                timestamp=_now_iso(),
            )
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

    async def _http_health_check(self) -> HealthCheck:
        """Check backend health via HTTP GET /health."""
        health_path = (self._node.metadata or {}).get("health_path", "/health")
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

    @staticmethod
    def _parse_headers(data: bytes) -> dict[str, str]:
        """Extract header key:value pairs from raw HTTP request bytes."""
        result: dict[str, str] = {}
        try:
            header_section = data.split(b"\r\n\r\n", 1)[0]
            lines = header_section.split(b"\r\n")
            # Skip request line (first line)
            for line in lines[1:]:
                if b":" in line:
                    key, val = line.split(b":", 1)
                    result[key.strip().decode("ascii", errors="replace").lower()] = (
                        val.strip().decode("ascii", errors="replace")
                    )
        except Exception:
            pass
        return result

    def _decrement_connections(self) -> None:
        self._active_connections -= 1
        if self._draining and self._active_connections <= 0:
            self._drain_event.set()

    async def _handle_tcp_connection(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        """Generic TCP forwarding: bidirectional byte pipe."""
        if self._draining or not self._backend.is_configured:
            client_writer.close()
            return

        self._active_connections += 1
        backend_writer = None
        try:
            backend_reader, backend_writer = await asyncio.open_connection(
                self._backend.host, self._backend.port
            )
            await asyncio.gather(
                self._pipe(client_reader, backend_writer),
                self._pipe(backend_reader, client_writer),
            )
            self._metrics.requests_total += 1
        except Exception as e:
            self._metrics.requests_failed += 1
            logger.debug(f"[{self._node.name}] TCP proxy error: {e}")
        finally:
            self._decrement_connections()
            client_writer.close()
            if backend_writer:
                backend_writer.close()

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
        backend_writer = None
        try:
            request_data = await self._read_http_message(client_reader)
            if not request_data:
                return

            target, target_name = self._select_backend_named(request_data)
            if target is None or not target.is_configured:
                client_writer.write(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )
                await client_writer.drain()
                return

            backend_reader, backend_writer = await asyncio.open_connection(
                target.host, target.port
            )
            backend_writer.write(request_data)
            await backend_writer.drain()

            response_data = await self._read_http_message(backend_reader)
            if response_data:
                client_writer.write(response_data)
                await client_writer.drain()

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

            if self._record_signals:
                method, path = self._parse_request_line(request_data)
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
                    )
                )

        except Exception as e:
            self._metrics.requests_failed += 1
            logger.debug(f"[{self._node.name}] HTTP proxy error: {e}")
        finally:
            self._decrement_connections()
            client_writer.close()
            if backend_writer:
                backend_writer.close()

    @staticmethod
    async def _pipe(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Copy bytes from reader to writer until EOF."""
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass

    @staticmethod
    async def _read_http_message(reader: asyncio.StreamReader) -> bytes | None:
        """Read a full HTTP/1.1 message (headers + body via Content-Length)."""
        try:
            headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30.0)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError):
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
