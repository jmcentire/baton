"""Audit event sidecar for service-to-circuit communication.

Exposes a local HTTP endpoint (bound to 127.0.0.1 only) for services
to POST audit events. Events are correlated with adapter spans and
optionally forwarded to Arbiter.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AuditEvent:
    """A structured audit event from a service."""

    __slots__ = ("pact_key", "event", "input_classification",
                 "output_classification", "side_effects", "timestamp",
                 "node_name")

    def __init__(
        self,
        pact_key: str = "",
        event: str = "",
        input_classification: list[str] | None = None,
        output_classification: list[str] | None = None,
        side_effects: list[str] | None = None,
        timestamp: str = "",
        node_name: str = "",
    ):
        self.pact_key = pact_key
        self.event = event
        self.input_classification = input_classification or []
        self.output_classification = output_classification or []
        self.side_effects = side_effects or []
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        self.node_name = node_name

    def to_dict(self) -> dict:
        return {
            "pact_key": self.pact_key,
            "event": self.event,
            "input_classification": self.input_classification,
            "output_classification": self.output_classification,
            "side_effects": self.side_effects,
            "timestamp": self.timestamp,
            "node_name": self.node_name,
        }


class AuditSidecar:
    """Local HTTP server for receiving audit events from services.

    Binds to 127.0.0.1 only — not accessible from outside the host.
    """

    def __init__(self, port: int = 9000, max_buffer: int = 10000):
        self._port = port
        self._server: asyncio.Server | None = None
        self._events: deque[AuditEvent] = deque(maxlen=max_buffer)

    @property
    def port(self) -> int:
        return self._port

    @property
    def events(self) -> list[AuditEvent]:
        return list(self._events)

    def drain_events(self) -> list[AuditEvent]:
        """Return and clear all buffered events."""
        drained = list(self._events)
        self._events.clear()
        return drained

    def query(self, node: str | None = None, last_n: int = 100) -> list[AuditEvent]:
        """Query buffered audit events."""
        results = list(self._events)
        if node:
            results = [e for e in results if e.node_name == node]
        return results[-last_n:]

    async def start(self) -> None:
        """Start the audit sidecar HTTP server on localhost only."""
        self._server = await asyncio.start_server(
            self._handle, "127.0.0.1", self._port,
        )
        logger.info(f"Audit sidecar listening on 127.0.0.1:{self._port}")

    async def stop(self) -> None:
        """Stop the audit sidecar."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an incoming audit event POST."""
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not request_line:
                writer.close()
                return

            # Read headers
            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                decoded = line.decode("ascii", errors="replace").strip()
                if ":" in decoded:
                    key, val = decoded.split(":", 1)
                    headers[key.strip().lower()] = val.strip()

            # Read body
            content_length = int(headers.get("content-length", "0"))
            body = b""
            if content_length > 0:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=5.0,
                )

            parts = request_line.decode("ascii", errors="replace").strip().split()
            method = parts[0] if parts else ""
            path = parts[1] if len(parts) > 1 else ""

            if method == "POST" and path == "/audit-event":
                response_body = self._handle_audit_event(body)
                self._write_response(writer, 201, response_body)
            elif method == "GET" and path == "/health":
                self._write_response(writer, 200, '{"status": "ok"}')
            else:
                self._write_response(writer, 404, '{"error": "not found"}')

            await writer.drain()
        except Exception as e:
            logger.debug(f"Audit sidecar error: {e}")
        finally:
            writer.close()

    def _handle_audit_event(self, body: bytes) -> str:
        """Parse and buffer an audit event."""
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return '{"error": "invalid JSON"}'

        event = AuditEvent(
            pact_key=data.get("pact_key", ""),
            event=data.get("event", ""),
            input_classification=data.get("input_classification", []),
            output_classification=data.get("output_classification", []),
            side_effects=data.get("side_effects", []),
            timestamp=data.get("ts", data.get("timestamp", "")),
            node_name=data.get("node_name", ""),
        )
        self._events.append(event)
        return json.dumps(event.to_dict())

    @staticmethod
    def _write_response(writer: asyncio.StreamWriter, status: int, body: str) -> None:
        reason = {200: "OK", 201: "Created", 404: "Not Found"}.get(status, "Unknown")
        body_bytes = body.encode("utf-8")
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n"
            f"\r\n".encode("ascii")
        )
        writer.write(body_bytes)
