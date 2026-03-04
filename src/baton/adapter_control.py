"""Adapter control API.

A small HTTP server on each adapter's management port exposing
/health, /metrics, /status endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from baton.adapter import Adapter
from baton.schemas import HealthVerdict, SecurityConfig

logger = logging.getLogger(__name__)


class AdapterControlServer:
    """Management HTTP server for a single adapter."""

    def __init__(self, adapter: Adapter, security: SecurityConfig | None = None):
        self._adapter = adapter
        self._server: asyncio.Server | None = None
        self._security = security
        self._auth_required = False
        self._auth_token: str | None = None
        if security and security.control.auth:
            self._auth_required = True
            if security.control.token_env:
                self._auth_token = os.environ.get(security.control.token_env)
            if not self._auth_token:
                logger.warning(
                    f"Auth enabled but token not found (env: {security.control.token_env}). "
                    "All control API requests will be rejected."
                )

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    async def start(self) -> None:
        """Start the control server on the adapter's management port."""
        node = self._adapter.node
        ssl_ctx = None
        if self._security and self._security.tls.mode in ("circuit", "full"):
            from pathlib import Path as _Path
            cert = _Path(self._security.tls.cert) if self._security.tls.cert else None
            key = _Path(self._security.tls.key) if self._security.tls.key else None
            if cert and key and cert.exists() and key.exists():
                import ssl
                ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_ctx.load_cert_chain(str(cert), str(key))
        self._server = await asyncio.start_server(
            self._handle, node.host, node.management_port,
            ssl=ssl_ctx,
        )
        logger.info(
            f"Control [{node.name}] listening on "
            f"{node.host}:{node.management_port}"
        )

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an incoming HTTP request to the control API."""
        try:
            request_line = await asyncio.wait_for(
                reader.readline(), timeout=5.0
            )
            if not request_line:
                writer.close()
                return

            # Read and accumulate headers
            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                decoded = line.decode("ascii", errors="replace").strip()
                if ":" in decoded:
                    key, val = decoded.split(":", 1)
                    headers[key.strip().lower()] = val.strip()

            parts = request_line.decode("ascii", errors="replace").strip().split()
            method = parts[0] if parts else ""
            path = parts[1] if len(parts) > 1 else ""

            # Auth check (fail-closed: if auth required but token missing, reject all)
            if self._auth_required:
                if self._auth_token is None:
                    self._write_response(writer, 503, json.dumps({"error": "auth misconfigured"}))
                    await writer.drain()
                    writer.close()
                    return
                auth_val = headers.get("authorization", "")
                if not auth_val.startswith("Bearer ") or auth_val[7:] != self._auth_token:
                    self._write_response(writer, 401, json.dumps({"error": "unauthorized"}))
                    await writer.drain()
                    writer.close()
                    return

            if method == "GET" and path == "/health":
                body = await self._handle_health()
            elif method == "GET" and path == "/metrics":
                body = self._handle_metrics()
            elif method == "GET" and path == "/status":
                body = self._handle_status()
            elif method == "GET" and path == "/routing":
                body = self._handle_routing()
            else:
                body = json.dumps({"error": "not found"})
                self._write_response(writer, 404, body)
                await writer.drain()
                writer.close()
                return

            self._write_response(writer, 200, body)
            await writer.drain()
        except Exception as e:
            logger.debug(f"Control API error: {e}")
        finally:
            writer.close()

    async def _handle_health(self) -> str:
        health = await self._adapter.health_check()
        return json.dumps({
            "node": health.node_name,
            "verdict": str(health.verdict),
            "latency_ms": health.latency_ms,
            "detail": health.detail,
        })

    def _handle_metrics(self) -> str:
        m = self._adapter.metrics
        return json.dumps({
            "requests_total": m.requests_total,
            "requests_failed": m.requests_failed,
            "bytes_forwarded": m.bytes_forwarded,
            "last_latency_ms": m.last_latency_ms,
            "status_2xx": m.status_2xx,
            "status_3xx": m.status_3xx,
            "status_4xx": m.status_4xx,
            "status_5xx": m.status_5xx,
            "active_connections": m.active_connections,
            "latency_p50": m.p50(),
            "latency_p95": m.p95(),
            "latency_p99": m.p99(),
        })

    def _handle_status(self) -> str:
        node = self._adapter.node
        backend = self._adapter.backend
        routing = self._adapter.routing
        result = {
            "node": node.name,
            "listening": f"{node.host}:{node.port}",
            "mode": str(node.proxy_mode),
            "backend": f"{backend.host}:{backend.port}" if backend.is_configured else None,
            "running": self._adapter.is_running,
        }
        if routing:
            result["routing_strategy"] = str(routing.strategy)
            result["routing_locked"] = routing.locked
        return json.dumps(result)

    def _handle_routing(self) -> str:
        routing = self._adapter.routing
        if routing is None:
            backend = self._adapter.backend
            return json.dumps({
                "strategy": "single",
                "backend": f"{backend.host}:{backend.port}" if backend.is_configured else None,
            })
        return json.dumps(routing.model_dump())

    @staticmethod
    def _write_response(writer: asyncio.StreamWriter, status: int, body: str) -> None:
        reason = {200: "OK", 401: "Unauthorized", 404: "Not Found", 500: "Internal Server Error", 503: "Service Unavailable"}.get(
            status, "Unknown"
        )
        body_bytes = body.encode("utf-8")
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n"
            f"\r\n".encode("ascii")
        )
        writer.write(body_bytes)
