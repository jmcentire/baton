"""OpenTelemetry integration -- optional dependency.

Install with: pip install baton[otel]
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from baton.tracing import SpanData

if TYPE_CHECKING:
    from baton.schemas import ObservabilityConfig

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import StatusCode

    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False


def _create_otlp_metric_exporter(protocol: str, endpoint: str):
    """Create an OTLP metric exporter for the given protocol."""
    if protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter as GrpcMetricExporter,
        )

        return GrpcMetricExporter(endpoint=endpoint, insecure=True)
    else:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter as HttpMetricExporter,
        )

        return HttpMetricExporter(endpoint=endpoint)


class OtelSpanExporter:
    """Exports SpanData to OTLP collector via OpenTelemetry SDK."""

    def __init__(self, config: ObservabilityConfig):
        if not HAS_OTEL:
            raise ImportError("opentelemetry packages not installed")

        resource = Resource.create({"service.name": config.service_name or "baton"})
        self._provider = TracerProvider(resource=resource)

        protocol = config.otlp_protocol or "grpc"
        endpoint = config.otlp_endpoint or "http://localhost:4317"

        if protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as GrpcExporter,
            )

            exporter = GrpcExporter(endpoint=endpoint, insecure=True)
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter as HttpExporter,
            )

            exporter = HttpExporter(endpoint=endpoint)

        self._provider.add_span_processor(BatchSpanProcessor(exporter))
        self._tracer = self._provider.get_tracer("baton")

    def export(self, spans: list[SpanData]) -> None:
        """Convert SpanData to OTel spans and export."""
        for sd in spans:
            with self._tracer.start_span(sd.name) as span:
                for k, v in sd.attributes.items():
                    span.set_attribute(k, v)
                span.set_attribute("baton.node", sd.node_name)
                span.set_attribute("baton.trace_id", sd.trace_id)
                if sd.edge_label:
                    span.set_attribute("baton.edge", sd.edge_label)
                if sd.status == "error":
                    span.set_status(StatusCode.ERROR)

    def shutdown(self) -> None:
        self._provider.shutdown()


class OtelMetricExporter:
    """Exports adapter metrics to OTLP collector."""

    def __init__(self, config: ObservabilityConfig):
        if not HAS_OTEL:
            raise ImportError("opentelemetry packages not installed")
        self._config = config

        resource = Resource.create({"service.name": config.service_name or "baton"})

        protocol = config.otlp_protocol or "grpc"
        endpoint = config.otlp_endpoint or "http://localhost:4317"

        otlp_exporter = _create_otlp_metric_exporter(protocol, endpoint)
        reader = PeriodicExportingMetricReader(
            otlp_exporter, export_interval_millis=60_000,
        )
        self._provider = MeterProvider(resource=resource, metric_readers=[reader])
        self._meter = self._provider.get_meter("baton")

        # Counters -- track last-seen cumulative values to emit deltas
        self._requests_total = self._meter.create_counter(
            name="baton.requests_total",
            description="Total proxied requests",
        )
        self._requests_failed = self._meter.create_counter(
            name="baton.requests_failed",
            description="Total failed requests",
        )
        self._bytes_forwarded = self._meter.create_counter(
            name="baton.bytes_forwarded",
            description="Total bytes forwarded",
            unit="By",
        )
        self._status_2xx = self._meter.create_counter(
            name="baton.status_2xx",
            description="Total 2xx responses",
        )
        self._status_3xx = self._meter.create_counter(
            name="baton.status_3xx",
            description="Total 3xx responses",
        )
        self._status_4xx = self._meter.create_counter(
            name="baton.status_4xx",
            description="Total 4xx responses",
        )
        self._status_5xx = self._meter.create_counter(
            name="baton.status_5xx",
            description="Total 5xx responses",
        )

        # Gauge for active connections (use UpDownCounter for synchronous gauge)
        self._active_connections = self._meter.create_up_down_counter(
            name="baton.active_connections",
            description="Current active connections",
        )

        # Histogram for latency percentiles
        self._latency_p50 = self._meter.create_histogram(
            name="baton.latency_p50_ms",
            description="Latency p50 in milliseconds",
            unit="ms",
        )
        self._latency_p95 = self._meter.create_histogram(
            name="baton.latency_p95_ms",
            description="Latency p95 in milliseconds",
            unit="ms",
        )

        # Previous cumulative values per node, for computing deltas
        self._prev: dict[str, dict[str, int]] = {}

    def export(self, metrics: dict) -> None:
        """Export adapter metrics snapshot to OTLP collector.

        ``metrics`` is ``dataclasses.asdict(DashboardSnapshot)`` -- a dict
        with ``timestamp`` and ``nodes`` (a dict of node-name -> NodeSnapshot
        fields).
        """
        nodes = metrics.get("nodes", {})
        for node_name, node in nodes.items():
            attrs = {"baton.node": node_name}

            prev = self._prev.get(node_name, {})

            # Compute deltas for cumulative counters
            cur_total = node.get("requests_total", 0)
            cur_failed = node.get("requests_failed", 0)

            delta_total = max(0, cur_total - prev.get("requests_total", 0))
            delta_failed = max(0, cur_failed - prev.get("requests_failed", 0))

            if delta_total:
                self._requests_total.add(delta_total, attrs)
            if delta_failed:
                self._requests_failed.add(delta_failed, attrs)

            # Status code counters (not in NodeSnapshot directly, but we
            # can derive from error_rate * total -- however the snapshot
            # doesn't carry per-status-class counts).
            # NodeSnapshot does not include status_2xx..5xx or bytes_forwarded
            # individually, so we skip those counters when the data isn't
            # present.  The raw AdapterMetrics fields may be passed by
            # future callers; handle both cases gracefully.
            for field_name, counter in (
                ("bytes_forwarded", self._bytes_forwarded),
                ("status_2xx", self._status_2xx),
                ("status_3xx", self._status_3xx),
                ("status_4xx", self._status_4xx),
                ("status_5xx", self._status_5xx),
            ):
                cur = node.get(field_name, 0)
                if cur:
                    delta = max(0, cur - prev.get(field_name, 0))
                    if delta:
                        counter.add(delta, attrs)

            # Active connections -- report absolute value as delta from previous
            cur_active = node.get("active_connections", 0)
            prev_active = prev.get("active_connections", 0)
            diff = cur_active - prev_active
            if diff != 0:
                self._active_connections.add(diff, attrs)

            # Latency percentiles -- record as histogram observations
            p50 = node.get("latency_p50", 0.0)
            p95 = node.get("latency_p95", 0.0)
            if p50 > 0:
                self._latency_p50.record(p50, attrs)
            if p95 > 0:
                self._latency_p95.record(p95, attrs)

            # Store current values for next delta computation
            self._prev[node_name] = {
                "requests_total": cur_total,
                "requests_failed": cur_failed,
                "bytes_forwarded": node.get("bytes_forwarded", 0),
                "status_2xx": node.get("status_2xx", 0),
                "status_3xx": node.get("status_3xx", 0),
                "status_4xx": node.get("status_4xx", 0),
                "status_5xx": node.get("status_5xx", 0),
                "active_connections": cur_active,
            }

    def shutdown(self) -> None:
        self._provider.shutdown()
