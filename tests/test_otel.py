"""Tests for OpenTelemetry integration (optional dependency)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from baton.schemas import ObservabilityConfig
from baton.tracing import SpanData


class TestOtelImportGuard:
    def test_otel_without_package_raises(self):
        """OtelSpanExporter raises ImportError when OTel is not installed."""
        with patch.dict("sys.modules", {
            "opentelemetry": None,
            "opentelemetry.sdk": None,
            "opentelemetry.sdk.trace": None,
        }):
            # Force reimport
            import importlib
            import baton.otel
            importlib.reload(baton.otel)

            if not baton.otel.HAS_OTEL:
                config = ObservabilityConfig(enabled=True)
                with pytest.raises(ImportError, match="opentelemetry"):
                    baton.otel.OtelSpanExporter(config)


class TestOtelMetricExporter:
    def test_metric_exporter_import_guard(self):
        """OtelMetricExporter raises ImportError when OTel is not installed."""
        with patch.dict("sys.modules", {
            "opentelemetry": None,
            "opentelemetry.sdk": None,
        }):
            import importlib
            import baton.otel
            importlib.reload(baton.otel)

            if not baton.otel.HAS_OTEL:
                config = ObservabilityConfig(enabled=True)
                with pytest.raises(ImportError, match="opentelemetry"):
                    baton.otel.OtelMetricExporter(config)
