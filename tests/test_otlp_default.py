"""Tests for OTLP-as-default behavior.

Covers: ObservabilityConfig defaults, multi-endpoint fan-out,
failure isolation, unreachable endpoint handling, config parsing
backward compatibility, and CLI dashboard de-emphasis note.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from baton.schemas import ObservabilityConfig, OtlpEndpointConfig
from baton.tracing import SpanData


# -- ObservabilityConfig defaults --


class TestObservabilityConfigDefaults:
    def test_otlp_enabled_true_by_default(self):
        config = ObservabilityConfig()
        assert config.otlp_enabled is True

    def test_default_endpoint_synthesized(self):
        config = ObservabilityConfig()
        assert config.otlp_endpoints is not None
        assert len(config.otlp_endpoints) == 1
        ep = config.otlp_endpoints[0]
        assert ep.name == "default"
        assert ep.endpoint == "localhost:4317"
        assert ep.protocol == "grpc"

    def test_otlp_disabled_no_synthesis(self):
        config = ObservabilityConfig(otlp_enabled=False)
        assert config.otlp_endpoints is None

    def test_explicit_endpoints_preserved(self):
        endpoints = [
            OtlpEndpointConfig(name="collector", endpoint="otel.example.com:4317", protocol="grpc"),
            OtlpEndpointConfig(name="chronicler", endpoint="localhost:4318", protocol="http"),
        ]
        config = ObservabilityConfig(otlp_endpoints=endpoints)
        assert len(config.otlp_endpoints) == 2
        assert config.otlp_endpoints[0].name == "collector"
        assert config.otlp_endpoints[1].name == "chronicler"

    def test_backward_compat_legacy_fields(self):
        """Legacy fields (enabled, sink, otlp_endpoint) still work."""
        config = ObservabilityConfig(
            enabled=True,
            sink="otel",
            otlp_endpoint="http://localhost:4317",
            otlp_protocol="grpc",
            service_name="myapp",
        )
        assert config.enabled is True
        assert config.sink == "otel"
        assert config.otlp_endpoint == "http://localhost:4317"


# -- Config parsing backward compatibility --


class TestConfigParsingBackwardCompat:
    def test_no_observability_section(self, project_dir: Path):
        """Existing baton.yaml without observability section uses defaults."""
        from baton.config import load_circuit_config
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [{"name": "api", "port": 8001}],
        }))
        config = load_circuit_config(project_dir)
        assert config.observability.otlp_enabled is True
        assert config.observability.otlp_endpoints is not None
        assert len(config.observability.otlp_endpoints) == 1

    def test_empty_observability_section(self, project_dir: Path):
        """Empty observability: {} uses defaults."""
        from baton.config import load_circuit_config
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [{"name": "api", "port": 8001}],
            "observability": {},
        }))
        config = load_circuit_config(project_dir)
        assert config.observability.otlp_enabled is True

    def test_legacy_observability_still_works(self, project_dir: Path):
        """Legacy observability config with old fields still parses."""
        from baton.config import load_circuit_config
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [{"name": "api", "port": 8001}],
            "observability": {
                "enabled": True,
                "sink": "otel",
                "otlp_endpoint": "http://collector:4317",
                "service_name": "myproject",
            },
        }))
        config = load_circuit_config(project_dir)
        assert config.observability.enabled is True
        assert config.observability.sink == "otel"
        assert config.observability.otlp_endpoint == "http://collector:4317"

    def test_multi_endpoint_config_parses(self, project_dir: Path):
        """New multi-endpoint observability config parses correctly."""
        from baton.config import load_circuit_config
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [{"name": "api", "port": 8001}],
            "observability": {
                "otlp_enabled": True,
                "otlp_endpoints": [
                    {"name": "collector", "endpoint": "localhost:4317", "protocol": "grpc"},
                    {"name": "chronicler", "endpoint": "localhost:4318", "protocol": "http"},
                ],
            },
        }))
        config = load_circuit_config(project_dir)
        assert config.observability.otlp_enabled is True
        assert len(config.observability.otlp_endpoints) == 2
        assert config.observability.otlp_endpoints[0].name == "collector"
        assert config.observability.otlp_endpoints[1].name == "chronicler"

    def test_otlp_disabled_config(self, project_dir: Path):
        """Explicitly disabling OTLP works."""
        from baton.config import load_circuit_config
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [{"name": "api", "port": 8001}],
            "observability": {
                "otlp_enabled": False,
            },
        }))
        config = load_circuit_config(project_dir)
        assert config.observability.otlp_enabled is False
        assert config.observability.otlp_endpoints is None

    def test_roundtrip_multi_endpoint(self, project_dir: Path):
        """Multi-endpoint config survives save/load roundtrip."""
        from baton.config import load_circuit_config, save_circuit_config
        from baton.schemas import CircuitConfig, NodeSpec

        endpoints = [
            OtlpEndpointConfig(name="collector", endpoint="otel.example.com:4317", protocol="grpc"),
            OtlpEndpointConfig(name="chronicler", endpoint="localhost:4318", protocol="http"),
        ]
        config = CircuitConfig(
            name="test",
            nodes=[NodeSpec(name="api", port=8001)],
            observability=ObservabilityConfig(
                otlp_enabled=True,
                otlp_endpoints=endpoints,
            ),
        )
        save_circuit_config(config, project_dir)
        loaded = load_circuit_config(project_dir)
        assert loaded.observability.otlp_enabled is True
        assert len(loaded.observability.otlp_endpoints) == 2
        assert loaded.observability.otlp_endpoints[0].name == "collector"

    def test_default_not_serialized(self, project_dir: Path):
        """Default OTLP config (single default endpoint) is not serialized."""
        from baton.config import save_circuit_config
        from baton.schemas import CircuitConfig, NodeSpec

        config = CircuitConfig(
            name="test",
            nodes=[NodeSpec(name="api", port=8001)],
        )
        save_circuit_config(config, project_dir)
        with open(project_dir / "baton.yaml") as f:
            raw = yaml.safe_load(f)
        # Default OTLP config should not appear in serialized output
        assert "otlp_endpoints" not in raw.get("observability", {})


# -- Multi-endpoint span exporter --


class TestMultiEndpointSpanExporter:
    def test_fanout_to_all_endpoints(self):
        """Spans are exported to all configured endpoints."""
        from baton.otel import MultiEndpointSpanExporter

        config = ObservabilityConfig(
            service_name="test",
            otlp_endpoints=[
                OtlpEndpointConfig(name="ep1", endpoint="localhost:4317", protocol="grpc"),
                OtlpEndpointConfig(name="ep2", endpoint="localhost:4318", protocol="http"),
            ],
        )

        with patch("baton.otel._create_otlp_span_exporter") as mock_factory:
            mock_exporter = MagicMock()
            mock_factory.return_value = mock_exporter
            exporter = MultiEndpointSpanExporter(config)

        # Should have created two providers/tracers
        assert len(exporter._tracers) == 2
        exporter.shutdown()

    def test_failure_isolation(self):
        """One failing endpoint doesn't block others."""
        from baton.otel import MultiEndpointSpanExporter, _EndpointHealth

        config = ObservabilityConfig(
            service_name="test",
            otlp_endpoints=[
                OtlpEndpointConfig(name="good", endpoint="localhost:4317", protocol="grpc"),
                OtlpEndpointConfig(name="bad", endpoint="localhost:4318", protocol="http"),
            ],
        )

        with patch("baton.otel._create_otlp_span_exporter") as mock_factory:
            mock_factory.return_value = MagicMock()
            exporter = MultiEndpointSpanExporter(config)

        # Make the second tracer raise on start_span
        good_tracer = MagicMock()
        good_health = _EndpointHealth("localhost:4317")
        bad_tracer = MagicMock()
        bad_tracer.start_span.side_effect = Exception("connection refused")
        bad_health = _EndpointHealth("localhost:4318")
        exporter._tracers = [(good_tracer, good_health), (bad_tracer, bad_health)]

        span = SpanData(name="test", trace_id="abc", span_id="def", node_name="api")
        # Should not raise
        exporter.export([span])

        # Good tracer should have been called
        good_tracer.start_span.assert_called_once_with("test")
        # Bad endpoint should be marked as failed
        assert bad_health.is_failed is True
        exporter.shutdown()

    def test_empty_endpoints_creates_empty_exporter(self):
        """No endpoints produces exporter with no tracers."""
        from baton.otel import MultiEndpointSpanExporter

        config = ObservabilityConfig(
            service_name="test",
            otlp_enabled=False,
        )
        # Force empty endpoints
        object.__setattr__(config, "otlp_endpoints", [])

        with patch("baton.otel._create_otlp_span_exporter"):
            exporter = MultiEndpointSpanExporter(config)

        assert len(exporter._tracers) == 0
        # Export with no tracers should be a no-op
        span = SpanData(name="test", trace_id="abc", span_id="def", node_name="api")
        exporter.export([span])  # no error
        exporter.shutdown()


# -- Endpoint health tracking --


class TestEndpointHealth:
    def test_first_failure_warns(self, caplog):
        from baton.otel import _EndpointHealth

        health = _EndpointHealth("localhost:4317")
        with caplog.at_level(logging.WARNING):
            health.record_failure("connection refused")

        assert health.is_failed is True
        assert health.failure_logged_at_warning is True
        assert "unreachable" in caplog.text.lower()

    def test_subsequent_failures_debug(self, caplog):
        from baton.otel import _EndpointHealth

        health = _EndpointHealth("localhost:4317")
        health.record_failure("connection refused")  # first: warning
        caplog.clear()

        with caplog.at_level(logging.DEBUG):
            health.record_failure("connection refused")  # second: debug

        assert health.is_failed is True
        # Should not have a WARNING level for the second failure
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 0

    def test_recovery_resets(self, caplog):
        from baton.otel import _EndpointHealth

        health = _EndpointHealth("localhost:4317")
        health.record_failure("connection refused")
        assert health.is_failed is True

        with caplog.at_level(logging.INFO):
            health.record_recovery()

        assert health.is_failed is False
        assert health.failure_logged_at_warning is False
        assert "recovered" in caplog.text.lower()


# -- CLI dashboard de-emphasis --


class TestDashboardDeEmphasis:
    def test_dashboard_help_contains_note(self):
        """Dashboard command help text includes the development aid note."""
        from baton.cli import main
        import io
        import sys

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            main(["dashboard", "--help"])
        except SystemExit:
            pass
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert "development aid" in output


# -- Span exporter factory --


class TestSpanExporterFactory:
    def test_otlp_enabled_creates_multi_endpoint(self):
        """When otlp_enabled=True and enabled=False, still creates MultiEndpointSpanExporter."""
        from baton.otel import MultiEndpointSpanExporter
        from baton.tracing import create_span_exporter

        config = ObservabilityConfig(enabled=False, otlp_enabled=True)
        with patch("baton.otel._create_otlp_span_exporter") as mock_factory:
            mock_factory.return_value = MagicMock()
            exporter = create_span_exporter("jsonl", config)

        assert isinstance(exporter, MultiEndpointSpanExporter)
        exporter.shutdown()

    def test_otlp_disabled_creates_null(self):
        """When both enabled=False and otlp_enabled=False, creates NullExporter."""
        from baton.tracing import NullExporter, create_span_exporter

        config = ObservabilityConfig(enabled=False, otlp_enabled=False)
        exporter = create_span_exporter("jsonl", config)
        assert isinstance(exporter, NullExporter)


# -- Pyproject.toml structure --


class TestPyprojectStructure:
    def test_otel_in_base_dependencies(self):
        """OTel packages are in base dependencies, not optional."""
        import tomllib

        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        deps = data["project"]["dependencies"]
        dep_names = [d.split(">=")[0].split("==")[0].strip() for d in deps]

        assert "opentelemetry-api" in dep_names
        assert "opentelemetry-sdk" in dep_names
        assert "opentelemetry-exporter-otlp-proto-grpc" in dep_names
        assert "opentelemetry-exporter-otlp-proto-http" in dep_names

    def test_otel_extra_is_empty(self):
        """The [otel] extra is an empty list for backward compat."""
        import tomllib

        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        otel_extra = data["project"]["optional-dependencies"]["otel"]
        assert otel_extra == []
