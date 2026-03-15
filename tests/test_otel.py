"""Tests for OpenTelemetry integration (optional dependency)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from baton.schemas import ObservabilityConfig
from baton.tracing import SpanData


class TestOtelImportGuard:
    def test_otel_without_package_raises(self):
        """OtelSpanExporter raises ImportError when OTel is not installed."""
        import importlib
        import baton.otel

        with patch.dict("sys.modules", {
            "opentelemetry": None,
            "opentelemetry.sdk": None,
            "opentelemetry.sdk.trace": None,
        }):
            # Force reimport
            importlib.reload(baton.otel)

            if not baton.otel.HAS_OTEL:
                config = ObservabilityConfig(enabled=True)
                with pytest.raises(ImportError, match="opentelemetry"):
                    baton.otel.OtelSpanExporter(config)

        # Restore HAS_OTEL after patch exits
        importlib.reload(baton.otel)


class TestOtelMetricExporter:
    def test_metric_exporter_import_guard(self):
        """OtelMetricExporter raises ImportError when OTel is not installed."""
        import importlib
        import baton.otel

        with patch.dict("sys.modules", {
            "opentelemetry": None,
            "opentelemetry.sdk": None,
        }):
            importlib.reload(baton.otel)

            if not baton.otel.HAS_OTEL:
                config = ObservabilityConfig(enabled=True)
                with pytest.raises(ImportError, match="opentelemetry"):
                    baton.otel.OtelMetricExporter(config)

        # Restore HAS_OTEL after patch exits
        importlib.reload(baton.otel)

    def test_export_records_counters_and_gauges(self):
        """export() records metrics for each node with correct attributes."""
        config = ObservabilityConfig(
            enabled=True,
            otlp_endpoint="http://localhost:4317",
            otlp_protocol="grpc",
            service_name="test-baton",
        )

        with patch("baton.otel._create_otlp_metric_exporter") as mock_factory:
            mock_factory.return_value = MagicMock()
            exporter = _make_metric_exporter(config)

        # Mock all instruments
        exporter._requests_total = MagicMock()
        exporter._requests_failed = MagicMock()
        exporter._bytes_forwarded = MagicMock()
        exporter._status_2xx = MagicMock()
        exporter._status_3xx = MagicMock()
        exporter._status_4xx = MagicMock()
        exporter._status_5xx = MagicMock()
        exporter._active_connections = MagicMock()
        exporter._latency_p50 = MagicMock()
        exporter._latency_p95 = MagicMock()

        metrics = {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "nodes": {
                "api-gateway": {
                    "name": "api-gateway",
                    "role": "ingress",
                    "status": "listening",
                    "health": "healthy",
                    "requests_total": 100,
                    "requests_failed": 5,
                    "error_rate": 0.05,
                    "latency_p50": 12.5,
                    "latency_p95": 45.0,
                    "active_connections": 3,
                    "routing_strategy": "single",
                    "routing_locked": False,
                },
            },
        }

        exporter.export(metrics)

        attrs = {"baton.node": "api-gateway"}
        exporter._requests_total.add.assert_called_once_with(100, attrs)
        exporter._requests_failed.add.assert_called_once_with(5, attrs)
        exporter._active_connections.add.assert_called_once_with(3, attrs)
        exporter._latency_p50.record.assert_called_once_with(12.5, attrs)
        exporter._latency_p95.record.assert_called_once_with(45.0, attrs)

    def test_export_computes_deltas_on_second_call(self):
        """Second call to export() sends only the delta for counters."""
        config = ObservabilityConfig(
            enabled=True,
            otlp_endpoint="http://localhost:4317",
            service_name="test-baton",
        )

        with patch("baton.otel._create_otlp_metric_exporter") as mock_factory:
            mock_factory.return_value = MagicMock()
            exporter = _make_metric_exporter(config)

        exporter._requests_total = MagicMock()
        exporter._requests_failed = MagicMock()
        exporter._active_connections = MagicMock()
        exporter._latency_p50 = MagicMock()
        exporter._latency_p95 = MagicMock()

        node_data_1 = {
            "timestamp": "t1",
            "nodes": {
                "svc": {
                    "name": "svc",
                    "requests_total": 50,
                    "requests_failed": 2,
                    "active_connections": 5,
                    "latency_p50": 10.0,
                    "latency_p95": 20.0,
                },
            },
        }
        node_data_2 = {
            "timestamp": "t2",
            "nodes": {
                "svc": {
                    "name": "svc",
                    "requests_total": 80,
                    "requests_failed": 3,
                    "active_connections": 2,
                    "latency_p50": 11.0,
                    "latency_p95": 22.0,
                },
            },
        }

        exporter.export(node_data_1)
        exporter.export(node_data_2)

        attrs = {"baton.node": "svc"}
        # First call: delta from 0 -> 50, second: 50 -> 80
        assert exporter._requests_total.add.call_args_list == [
            call(50, attrs),
            call(30, attrs),
        ]
        assert exporter._requests_failed.add.call_args_list == [
            call(2, attrs),
            call(1, attrs),
        ]
        # Active connections: 0->5 then 5->2
        assert exporter._active_connections.add.call_args_list == [
            call(5, attrs),
            call(-3, attrs),
        ]

    def test_export_multiple_nodes(self):
        """export() handles multiple nodes in a single snapshot."""
        config = ObservabilityConfig(
            enabled=True,
            otlp_endpoint="http://localhost:4317",
            service_name="test-baton",
        )

        with patch("baton.otel._create_otlp_metric_exporter") as mock_factory:
            mock_factory.return_value = MagicMock()
            exporter = _make_metric_exporter(config)

        exporter._requests_total = MagicMock()
        exporter._requests_failed = MagicMock()
        exporter._active_connections = MagicMock()
        exporter._latency_p50 = MagicMock()
        exporter._latency_p95 = MagicMock()

        metrics = {
            "timestamp": "t1",
            "nodes": {
                "alpha": {
                    "name": "alpha",
                    "requests_total": 10,
                    "requests_failed": 0,
                    "active_connections": 1,
                    "latency_p50": 5.0,
                    "latency_p95": 0.0,
                },
                "beta": {
                    "name": "beta",
                    "requests_total": 20,
                    "requests_failed": 1,
                    "active_connections": 0,
                    "latency_p50": 0.0,
                    "latency_p95": 30.0,
                },
            },
        }

        exporter.export(metrics)

        total_calls = exporter._requests_total.add.call_args_list
        assert call(10, {"baton.node": "alpha"}) in total_calls
        assert call(20, {"baton.node": "beta"}) in total_calls

    def test_export_empty_nodes(self):
        """export() handles an empty nodes dict gracefully."""
        config = ObservabilityConfig(
            enabled=True,
            otlp_endpoint="http://localhost:4317",
            service_name="test-baton",
        )

        with patch("baton.otel._create_otlp_metric_exporter") as mock_factory:
            mock_factory.return_value = MagicMock()
            exporter = _make_metric_exporter(config)

        exporter._requests_total = MagicMock()

        exporter.export({"timestamp": "t1", "nodes": {}})
        exporter._requests_total.add.assert_not_called()

    def test_export_optional_fields(self):
        """export() records status code and bytes counters when present."""
        config = ObservabilityConfig(
            enabled=True,
            otlp_endpoint="http://localhost:4317",
            service_name="test-baton",
        )

        with patch("baton.otel._create_otlp_metric_exporter") as mock_factory:
            mock_factory.return_value = MagicMock()
            exporter = _make_metric_exporter(config)

        exporter._requests_total = MagicMock()
        exporter._requests_failed = MagicMock()
        exporter._bytes_forwarded = MagicMock()
        exporter._status_2xx = MagicMock()
        exporter._status_3xx = MagicMock()
        exporter._status_4xx = MagicMock()
        exporter._status_5xx = MagicMock()
        exporter._active_connections = MagicMock()
        exporter._latency_p50 = MagicMock()
        exporter._latency_p95 = MagicMock()

        metrics = {
            "timestamp": "t1",
            "nodes": {
                "svc": {
                    "name": "svc",
                    "requests_total": 100,
                    "requests_failed": 10,
                    "bytes_forwarded": 5000,
                    "status_2xx": 80,
                    "status_3xx": 5,
                    "status_4xx": 5,
                    "status_5xx": 10,
                    "active_connections": 0,
                    "latency_p50": 0.0,
                    "latency_p95": 0.0,
                },
            },
        }

        exporter.export(metrics)

        attrs = {"baton.node": "svc"}
        exporter._bytes_forwarded.add.assert_called_once_with(5000, attrs)
        exporter._status_2xx.add.assert_called_once_with(80, attrs)
        exporter._status_3xx.add.assert_called_once_with(5, attrs)
        exporter._status_4xx.add.assert_called_once_with(5, attrs)
        exporter._status_5xx.add.assert_called_once_with(10, attrs)

    def test_shutdown_calls_provider(self):
        """shutdown() delegates to the MeterProvider."""
        config = ObservabilityConfig(
            enabled=True,
            otlp_endpoint="http://localhost:4317",
            service_name="test-baton",
        )

        with patch("baton.otel._create_otlp_metric_exporter") as mock_factory:
            mock_factory.return_value = MagicMock()
            exporter = _make_metric_exporter(config)

        exporter._provider = MagicMock()
        exporter.shutdown()
        exporter._provider.shutdown.assert_called_once()


def _make_metric_exporter(config: ObservabilityConfig):
    """Helper to construct OtelMetricExporter with mocked OTLP exporter."""
    from baton.otel import OtelMetricExporter

    return OtelMetricExporter(config)
