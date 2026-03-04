"""Dashboard HTTP server.

Serves the dashboard API and static UI files over a single
asyncio HTTP server (same raw pattern as adapter_control.py).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from baton.adapter import Adapter
from baton.dashboard import collect
from baton.schemas import CircuitSpec, CircuitState
from baton.signals import SignalAggregator

logger = logging.getLogger(__name__)


class DashboardServer:
    """HTTP server for the Baton dashboard API and static UI."""

    def __init__(
        self,
        adapters: dict[str, Adapter],
        state: CircuitState,
        circuit: CircuitSpec,
        signal_aggregator: SignalAggregator | None = None,
        static_dir: str | Path | None = None,
        host: str = "127.0.0.1",
        port: int = 9900,
    ):
        self._adapters = adapters
        self._state = state
        self._circuit = circuit
        self._signal_aggregator = signal_aggregator
        self._static_dir = Path(static_dir) if static_dir else None
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    async def start(self) -> None:
        """Start the dashboard server."""
        self._server = await asyncio.start_server(
            self._handle, self._host, self._port
        )
        logger.info(f"Dashboard server listening on {self._host}:{self._port}")

    async def stop(self) -> None:
        """Stop the dashboard server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an incoming HTTP request."""
        try:
            request_line = await asyncio.wait_for(
                reader.readline(), timeout=5.0
            )
            if not request_line:
                writer.close()
                return

            # Discard remaining headers
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break

            parts = request_line.decode("ascii", errors="replace").strip().split()
            method = parts[0] if parts else ""
            raw_path = parts[1] if len(parts) > 1 else ""

            parsed = urlparse(raw_path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if method == "GET" and path == "/api/snapshot":
                body = await self._handle_snapshot()
                self._write_json_response(writer, 200, body)
            elif method == "GET" and path == "/api/topology":
                body = self._handle_topology()
                self._write_json_response(writer, 200, body)
            elif method == "GET" and path == "/api/signals":
                last_n = int(query.get("last_n", ["50"])[0])
                body = self._handle_signals(last_n=last_n)
                self._write_json_response(writer, 200, body)
            elif method == "GET" and path == "/api/signals/stats":
                body = self._handle_signal_stats()
                self._write_json_response(writer, 200, body)
            elif method == "GET":
                # Serve static files
                await self._handle_static(writer, path)
                await writer.drain()
                writer.close()
                return
            else:
                body = json.dumps({"error": "not found"})
                self._write_json_response(writer, 404, body)

            await writer.drain()
        except Exception as e:
            logger.debug(f"Dashboard server error: {e}")
        finally:
            writer.close()

    async def _handle_snapshot(self) -> str:
        """Return dashboard.collect() as JSON."""
        snapshot = await collect(self._adapters, self._state, self._circuit)
        return json.dumps(dataclasses.asdict(snapshot))

    def _handle_topology(self) -> str:
        """Return circuit nodes and edges as JSON."""
        nodes = []
        for n in self._circuit.nodes:
            nodes.append({
                "name": n.name,
                "port": n.port,
                "role": str(n.role),
                "host": n.host,
            })
        edges = []
        for e in self._circuit.edges:
            edges.append({
                "source": e.source,
                "target": e.target,
                "label": e.label,
            })
        return json.dumps({"nodes": nodes, "edges": edges})

    def _handle_signals(self, last_n: int = 50) -> str:
        """Return recent signals as JSON."""
        if not self._signal_aggregator:
            return json.dumps([])
        signals = self._signal_aggregator.query(last_n=last_n)
        return json.dumps([s.model_dump() for s in signals])

    def _handle_signal_stats(self) -> str:
        """Return per-path signal statistics as JSON."""
        if not self._signal_aggregator:
            return json.dumps({})
        stats = self._signal_aggregator.path_stats()
        return json.dumps({
            path: {
                "path": s.path,
                "count": s.count,
                "avg_latency_ms": round(s.avg_latency_ms, 2),
                "error_count": s.error_count,
                "error_rate": round(s.error_rate, 4),
            }
            for path, s in stats.items()
        })

    async def _handle_static(
        self, writer: asyncio.StreamWriter, path: str
    ) -> None:
        """Serve static files from the static directory."""
        if not self._static_dir:
            self._write_json_response(
                writer, 404, json.dumps({"error": "no static directory configured"})
            )
            return

        # Default to index.html
        if path in ("/", ""):
            path = "/index.html"

        # Sanitize: prevent directory traversal
        file_path = (self._static_dir / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(self._static_dir.resolve())):
            self._write_json_response(
                writer, 403, json.dumps({"error": "forbidden"})
            )
            return

        if not file_path.exists() or file_path.is_dir():
            self._write_json_response(
                writer, 404, json.dumps({"error": "not found"})
            )
            return

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        body = file_path.read_bytes()
        reason = "OK"
        writer.write(
            f"HTTP/1.1 200 {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n".encode("ascii")
        )
        writer.write(body)

    @staticmethod
    def _write_json_response(
        writer: asyncio.StreamWriter, status: int, body: str
    ) -> None:
        """Write an HTTP JSON response."""
        reason = {200: "OK", 403: "Forbidden", 404: "Not Found", 500: "Internal Server Error"}.get(
            status, "Unknown"
        )
        body_bytes = body.encode("utf-8")
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: application/json\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n"
            f"\r\n".encode("ascii")
        )
        writer.write(body_bytes)
