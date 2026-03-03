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

    def __init__(self, node: NodeSpec, record_signals: bool = False):
        self._node = node
        self._backend = BackendTarget()
        self._routing: RoutingConfig | None = None
        self._server: asyncio.Server | None = None
        self._record_signals = record_signals
        self._signals: list[SignalRecord] = []
        self._metrics = AdapterMetrics()
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
    def signals(self) -> list[SignalRecord]:
        return list(self._signals)

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
        """Check if the backend service is reachable via TCP connect."""
        if not self._backend.is_configured:
            return HealthCheck(
                node_name=self._node.name,
                verdict=HealthVerdict.UNKNOWN,
                detail="No backend configured",
                timestamp=_now_iso(),
            )
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

    def _select_backend(self, request_data: bytes | None = None) -> BackendTarget | None:
        """Select a backend based on routing config, or fall through to self._backend."""
        if self._routing is None:
            return self._backend if self._backend.is_configured else None

        targets_by_name = {t.name: t for t in self._routing.targets}

        if self._routing.strategy in (RoutingStrategy.WEIGHTED, RoutingStrategy.CANARY):
            return self._select_weighted(self._routing.targets)
        elif self._routing.strategy == RoutingStrategy.HEADER and request_data:
            return self._select_by_header(request_data, self._routing, targets_by_name)

        return self._backend if self._backend.is_configured else None

    @staticmethod
    def _select_weighted(targets: list) -> BackendTarget:
        """Pick a target based on cumulative weights."""
        roll = random.randint(1, 100)
        cumulative = 0
        for t in targets:
            cumulative += t.weight
            if roll <= cumulative:
                return BackendTarget(host=t.host, port=t.port)
        # Fallback to last target
        last = targets[-1]
        return BackendTarget(host=last.host, port=last.port)

    def _select_by_header(
        self,
        request_data: bytes,
        config: RoutingConfig,
        targets_by_name: dict,
    ) -> BackendTarget:
        """Route based on header value matching rules."""
        headers = self._parse_headers(request_data)
        for rule in config.rules:
            if headers.get(rule.header.lower()) == rule.value:
                t = targets_by_name.get(rule.target)
                if t:
                    return BackendTarget(host=t.host, port=t.port)
        # Fall back to default target
        t = targets_by_name.get(config.default_target)
        if t:
            return BackendTarget(host=t.host, port=t.port)
        return self._backend

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

            target = self._select_backend(request_data)
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
