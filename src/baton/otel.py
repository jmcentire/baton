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

    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False


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

    def export(self, metrics: dict) -> None:
        # Metric export is a future extension; spans are the primary export
        pass

    def shutdown(self) -> None:
        pass
