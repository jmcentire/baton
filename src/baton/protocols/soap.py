"""SOAP protocol handler -- HTTP wrapper with SOAPAction awareness.

Proxies SOAP/XML traffic over HTTP. Extracts SOAPAction headers for
routing awareness and detects SOAP faults in health checks.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from baton.protocols import ConnectionContext, register_handler
from baton.schemas import HealthCheck, HealthVerdict

logger = logging.getLogger(__name__)

_SOAP_FAULT_RE = re.compile(rb"<(?:\w+:)?Fault\b", re.IGNORECASE)
_SAFE_PATH_RE = re.compile(r"^/[a-zA-Z0-9/_.\-~%]*$")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class SOAPHandler:
    """HTTP-based SOAP proxy with SOAPAction header awareness.

    Forwards SOAP requests as HTTP, extracts SOAPAction for signal recording,
    and detects SOAP faults in health check responses.
    """

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        ctx: ConnectionContext,
    ) -> None:
        adapter = ctx.adapter
        if adapter._draining or (not adapter._backend.is_configured and adapter._routing is None):
            writer.write(
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Length: 0\r\n"
                b"Connection: close\r\n\r\n"
            )
            await writer.drain()
            writer.close()
            return

        adapter._active_connections += 1
        start = time.monotonic()
        backend_writer = None
        try:
            request_data = await _read_http_message(reader)
            if not request_data:
                return

            target = adapter._select_backend(request_data)
            if target is None or not target.is_configured:
                writer.write(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )
                await writer.drain()
                return

            conn_timeout = adapter._policy.timeout_ms / 1000 if adapter._policy else 30.0
            backend_reader, backend_writer = await asyncio.wait_for(
                asyncio.open_connection(target.host, target.port),
                timeout=conn_timeout,
            )
            backend_writer.write(request_data)
            await backend_writer.drain()

            response_data = await _read_http_message(backend_reader)
            if not response_data:
                writer.write(
                    b"HTTP/1.1 502 Bad Gateway\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )
                await writer.drain()
                adapter._metrics.requests_failed += 1
                return

            writer.write(response_data)
            await writer.drain()

            latency = (time.monotonic() - start) * 1000
            adapter._metrics.requests_total += 1
            adapter._metrics.last_latency_ms = latency
            adapter._metrics.record_latency(latency)
            adapter._metrics.bytes_forwarded += len(request_data) + len(response_data)

            # Extract SOAPAction for signal recording
            soap_action = _extract_soap_action(request_data)
            if adapter._record_signals:
                from baton.schemas import SignalRecord
                adapter._signals.append(
                    SignalRecord(
                        node_name=ctx.node.name,
                        direction="inbound",
                        method="POST",
                        path=soap_action or "/soap",
                        status_code=_parse_status_code(response_data),
                        body_bytes=len(response_data),
                        latency_ms=latency,
                        timestamp=_now_iso(),
                    )
                )

        except Exception as e:
            adapter._metrics.requests_failed += 1
            logger.debug(f"[{ctx.node.name}] SOAP proxy error: {e}")
        finally:
            adapter._decrement_connections()
            writer.close()
            if backend_writer:
                backend_writer.close()

    async def health_check(
        self, host: str, port: int, metadata: dict[str, str]
    ) -> HealthCheck:
        """SOAP health check: HTTP GET to health path, detect SOAP faults."""
        node_name = metadata.get("_node_name", "")
        health_path = metadata.get("health_path", "/health")
        if not _SAFE_PATH_RE.match(health_path):
            return HealthCheck(
                node_name=node_name,
                verdict=HealthVerdict.UNKNOWN,
                detail=f"Invalid health_path: {health_path!r}",
                timestamp=_now_iso(),
            )

        start = time.monotonic()
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5.0
            )
            request = (
                f"GET {health_path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("ascii")
            w.write(request)
            await w.drain()

            response = await asyncio.wait_for(r.read(8192), timeout=5.0)
            w.close()
            await w.wait_closed()

            latency = (time.monotonic() - start) * 1000
            status_code = _parse_status_code(response)

            # Check for SOAP fault in response body
            if _SOAP_FAULT_RE.search(response):
                return HealthCheck(
                    node_name=node_name,
                    verdict=HealthVerdict.DEGRADED,
                    latency_ms=latency,
                    detail="SOAP fault detected in health response",
                    timestamp=_now_iso(),
                )

            if 200 <= status_code < 300:
                verdict = HealthVerdict.HEALTHY
            elif 500 <= status_code < 600:
                verdict = HealthVerdict.UNHEALTHY
            else:
                verdict = HealthVerdict.DEGRADED

            return HealthCheck(
                node_name=node_name,
                verdict=verdict,
                latency_ms=latency,
                detail=f"HTTP {status_code}",
                timestamp=_now_iso(),
            )
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return HealthCheck(
                node_name=node_name,
                verdict=HealthVerdict.UNHEALTHY,
                latency_ms=latency,
                detail=str(e),
                timestamp=_now_iso(),
            )


def _extract_soap_action(data: bytes) -> str:
    """Extract SOAPAction header value from HTTP request."""
    try:
        header_section = data.split(b"\r\n\r\n", 1)[0]
        for line in header_section.split(b"\r\n"):
            if line.lower().startswith(b"soapaction:"):
                val = line.split(b":", 1)[1].strip().decode("ascii", errors="replace")
                return val.strip('"')
    except Exception:
        pass
    return ""


def _parse_status_code(data: bytes) -> int:
    """Extract HTTP status code from response."""
    try:
        first_line = data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        parts = first_line.split(" ")
        if len(parts) >= 2:
            return int(parts[1])
    except Exception:
        pass
    return 0


async def _read_http_message(reader: asyncio.StreamReader) -> bytes | None:
    """Read an HTTP message (headers + body via Content-Length)."""
    try:
        headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30.0)
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


register_handler("soap", SOAPHandler)
