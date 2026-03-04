"""Mock server generation from contract specs.

Generates asyncio HTTP servers that serve valid responses for endpoints
defined in OpenAPI or JSON Schema specs. A single MockServer can serve
multiple ports simultaneously (for collapsed circuits).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import string
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from baton.tracing import SpanExporter

logger = logging.getLogger(__name__)


def generate_instance(schema: dict) -> Any:
    """Generate a random valid instance from a JSON Schema."""
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]

    schema_type = schema.get("type", "object")

    if schema_type == "string":
        fmt = schema.get("format", "")
        if fmt == "date":
            return "2026-01-01"
        if fmt == "date-time":
            return "2026-01-01T00:00:00Z"
        if fmt == "email":
            return "test@example.com"
        if fmt == "uri" or fmt == "url":
            return "https://example.com"
        length = schema.get("minLength", 5)
        return "".join(random.choices(string.ascii_lowercase, k=length))

    if schema_type == "integer":
        lo = schema.get("minimum", 1)
        hi = schema.get("maximum", 100)
        return random.randint(lo, hi)

    if schema_type == "number":
        return round(random.uniform(0, 100), 2)

    if schema_type == "boolean":
        return True

    if schema_type == "array":
        items = schema.get("items", {"type": "string"})
        count = schema.get("minItems", 1)
        return [generate_instance(items) for _ in range(count)]

    if schema_type == "object":
        props = schema.get("properties", {})
        required = set(schema.get("required", list(props.keys())))
        obj = {}
        for name, prop_schema in props.items():
            if name in required:
                obj[name] = generate_instance(prop_schema)
        return obj

    return None


def parse_openapi(spec_path: str) -> dict[str, dict[str, Any]]:
    """Parse an OpenAPI 3.x spec and return route table.

    Returns: {path: {METHOD: response_body}}
    """
    path = Path(spec_path)
    with open(path) as f:
        if path.suffix in (".yaml", ".yml"):
            spec = yaml.safe_load(f)
        else:
            spec = json.load(f)

    if not spec or "paths" not in spec:
        return {}

    components = spec.get("components", {}).get("schemas", {})
    routes: dict[str, dict[str, Any]] = {}

    for path_str, methods in spec["paths"].items():
        routes[path_str] = {}
        for method, operation in methods.items():
            if method.startswith("x-") or method == "parameters":
                continue
            method = method.upper()

            # Find the success response
            responses = operation.get("responses", {})
            success_resp = responses.get("200") or responses.get("201") or {}
            content = success_resp.get("content", {})
            json_content = content.get("application/json", {})
            resp_schema = json_content.get("schema", {})

            # Resolve $ref
            if "$ref" in resp_schema:
                ref_name = resp_schema["$ref"].split("/")[-1]
                resp_schema = components.get(ref_name, {})

            # Generate response body
            if "example" in json_content:
                body = json_content["example"]
            elif "example" in resp_schema:
                body = resp_schema["example"]
            elif resp_schema:
                body = generate_instance(resp_schema)
            else:
                body = {}

            routes[path_str][method] = body

    return routes


def parse_json_schema(spec_path: str) -> dict[str, dict[str, Any]]:
    """Parse a JSON Schema and return a single-endpoint route table."""
    with open(spec_path) as f:
        schema = json.load(f)

    body = generate_instance(schema)
    return {"/": {"GET": body}}


def load_routes(spec_path: str) -> dict[str, dict[str, Any]]:
    """Load routes from a spec file (auto-detect format)."""
    path = Path(spec_path)
    if not path.exists():
        logger.warning(f"Contract spec not found: {spec_path}")
        return {}

    # Try OpenAPI first
    try:
        with open(path) as f:
            if path.suffix in (".yaml", ".yml"):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
    except Exception:
        return {}

    if isinstance(data, dict) and ("openapi" in data or "paths" in data):
        return parse_openapi(spec_path)
    elif isinstance(data, dict) and ("type" in data or "properties" in data):
        return parse_json_schema(spec_path)
    else:
        return {}


class MockServer:
    """In-process mock HTTP server serving canned responses.

    Can serve routes for multiple ports simultaneously (collapsed mode).
    """

    def __init__(
        self,
        span_exporter: "SpanExporter | None" = None,
        node_name: str = "",
    ):
        self._route_tables: dict[int, dict[str, dict[str, Any]]] = {}
        self._servers: list[asyncio.Server] = []
        self._span_exporter = span_exporter
        self._node_name = node_name
        self._span_buffer: list = []

    def add_routes(self, port: int, routes: dict[str, dict[str, Any]]) -> None:
        """Register routes for a port."""
        self._route_tables[port] = routes

    def add_default_routes(self, port: int) -> None:
        """Add a default health endpoint for a port with no contract."""
        self._route_tables[port] = {
            "/": {"GET": {"status": "mock", "port": port}},
            "/health": {"GET": {"status": "ok"}},
        }

    async def start(self, host: str = "127.0.0.1") -> None:
        """Start HTTP servers for all registered ports."""
        for port, routes in self._route_tables.items():
            server = await asyncio.start_server(
                lambda r, w, p=port: self._handle(r, w, p),
                host,
                port,
            )
            self._servers.append(server)
            logger.info(f"Mock server listening on {host}:{port} ({len(routes)} routes)")

    async def stop(self) -> None:
        for s in self._servers:
            s.close()
            await s.wait_closed()
        self._servers.clear()

    @property
    def is_running(self) -> bool:
        return len(self._servers) > 0

    def drain_spans(self) -> list:
        """Return and clear the span buffer."""
        drained = self._span_buffer[:]
        self._span_buffer.clear()
        return drained

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        port: int,
    ) -> None:
        """Handle an HTTP request: match route, return canned response."""
        try:
            start = time.monotonic()
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not request_line:
                writer.close()
                return

            # Read remaining headers and extract traceparent
            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                if b":" in line:
                    key, val = line.split(b":", 1)
                    headers[key.strip().decode("ascii", errors="replace").lower()] = (
                        val.strip().decode("ascii", errors="replace")
                    )

            parts = request_line.decode("ascii", errors="replace").strip().split()
            method = parts[0] if parts else "GET"
            path = parts[1] if len(parts) > 1 else "/"

            routes = self._route_tables.get(port, {})
            route = routes.get(path, {})
            body = route.get(method)

            if body is None:
                # Try without trailing slash
                alt_path = path.rstrip("/") if path != "/" else path
                route = routes.get(alt_path, {})
                body = route.get(method)

            status_code = 200
            if body is None:
                status_code = 404
                resp_body = json.dumps({"error": "not found", "path": path}).encode()
                writer.write(
                    f"HTTP/1.1 404 Not Found\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(resp_body)}\r\n"
                    f"Connection: close\r\n"
                    f"\r\n".encode("ascii")
                )
                writer.write(resp_body)
            else:
                resp_body = json.dumps(body).encode()
                writer.write(
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(resp_body)}\r\n"
                    f"Connection: close\r\n"
                    f"\r\n".encode("ascii")
                )
                writer.write(resp_body)

            await writer.drain()

            # Create span if exporter is configured
            if self._span_exporter:
                from baton.tracing import (
                    SpanData,
                    generate_span_id,
                    generate_trace_id,
                    parse_traceparent,
                )

                parent_ctx = parse_traceparent(headers.get("traceparent", ""))
                trace_id = parent_ctx.trace_id if parent_ctx else generate_trace_id()
                span_id = generate_span_id()
                span = SpanData(
                    name=f"mock_{self._node_name}_{method}",
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_ctx.span_id if parent_ctx else "",
                    start_time_ns=int(start * 1e9),
                    end_time_ns=int(time.monotonic() * 1e9),
                    attributes={
                        "http.method": method,
                        "http.path": path,
                        "http.status_code": str(status_code),
                        "mock": "true",
                    },
                    status="ok" if status_code < 400 else "error",
                    node_name=self._node_name,
                )
                self._span_buffer.append(span)

        except Exception as e:
            logger.debug(f"Mock server error: {e}")
        finally:
            writer.close()
