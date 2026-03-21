"""Distributed tracing core -- trace context propagation and span export.

All OTel-specific code lives in otel.py. This module has zero external dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from baton.schemas import ObservabilityConfig, TelemetryClassRule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TraceContext:
    """Parsed W3C traceparent context."""

    trace_id: str
    span_id: str
    parent_span_id: str = ""
    sampled: bool = True


@dataclass
class SpanData:
    """A completed span ready for export."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str = ""
    start_time_ns: int = 0
    end_time_ns: int = 0
    attributes: dict[str, str] = field(default_factory=dict)
    status: str = "ok"
    node_name: str = ""
    edge_label: str = ""


class SpanExporter(Protocol):
    """Protocol for span export backends."""

    def export(self, spans: list[SpanData]) -> None: ...
    def shutdown(self) -> None: ...


class MetricExporter(Protocol):
    """Protocol for metric export backends."""

    def export(self, metrics: dict) -> None: ...
    def shutdown(self) -> None: ...


class NullExporter:
    """No-op exporter (default when observability is disabled)."""

    def export(self, spans: list[SpanData]) -> None:
        pass

    def shutdown(self) -> None:
        pass


class JsonlExporter:
    """Writes spans to .baton/spans.jsonl."""

    def __init__(self, project_dir: str | Path):
        self._project_dir = Path(project_dir)

    def export(self, spans: list[SpanData]) -> None:
        from baton.state import append_jsonl

        for span in spans:
            data = {
                "name": span.name,
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "start_time_ns": span.start_time_ns,
                "end_time_ns": span.end_time_ns,
                "attributes": span.attributes,
                "status": span.status,
                "node_name": span.node_name,
                "edge_label": span.edge_label,
            }
            append_jsonl(self._project_dir, "spans.jsonl", data)

    def shutdown(self) -> None:
        pass


def generate_trace_id() -> str:
    """Generate a random 32-char hex trace ID."""
    return os.urandom(16).hex()


def generate_span_id() -> str:
    """Generate a random 16-char hex span ID."""
    return os.urandom(8).hex()


def parse_traceparent(header: str) -> TraceContext | None:
    """Parse W3C traceparent header: 00-{trace_id}-{span_id}-{flags}."""
    if not header:
        return None
    parts = header.strip().split("-")
    if len(parts) != 4 or parts[0] != "00":
        return None
    trace_id = parts[1]
    span_id = parts[2]
    if len(trace_id) != 32 or len(span_id) != 16:
        return None
    return TraceContext(
        trace_id=trace_id,
        span_id=span_id,
        sampled=(parts[3] == "01"),
    )


def format_traceparent(ctx: TraceContext) -> str:
    """Format a TraceContext as W3C traceparent header value."""
    flags = "01" if ctx.sampled else "00"
    return f"00-{ctx.trace_id}-{ctx.span_id}-{flags}"


def derive_telemetry_class(method: str, node_name: str, path: str) -> str:
    """Default telemetry class derivation: {METHOD}_{node}_{path_prefix}.

    Path is truncated to first static segment (no parameter explosion).
    """
    prefix = path.strip("/").split("/")[0] if path.strip("/") else "root"
    return f"{method}_{node_name}_{prefix}"


def resolve_telemetry_class(
    method: str,
    path: str,
    node_name: str,
    rules: list[TelemetryClassRule],
) -> str:
    """Match against explicit rules, fall back to derived default."""
    request_key = f"{method} {path}"
    for rule in rules:
        if rule.match == request_key:
            return rule.telemetry_class
    return derive_telemetry_class(method, node_name, path)


def create_span_exporter(
    sink: str,
    config: ObservabilityConfig,
    project_dir: str | Path = "",
) -> SpanExporter:
    """Factory: create exporter by name.

    When OTLP is enabled (otlp_enabled=True, the default), creates a
    multi-endpoint span exporter that fans out to all configured endpoints.
    Unreachable endpoints are handled gracefully (fire-and-forget).
    """
    if sink == "null":
        return NullExporter()
    if not config.enabled:
        # observability.enabled is False, but otlp_enabled may be True
        if config.otlp_enabled and config.otlp_endpoints:
            from baton.otel import MultiEndpointSpanExporter
            return MultiEndpointSpanExporter(config)
        return NullExporter()
    if sink == "jsonl":
        return JsonlExporter(project_dir)
    if sink == "otel":
        from baton.otel import OtelSpanExporter
        return OtelSpanExporter(config)
    raise ValueError(f"Unknown span exporter: {sink}")
