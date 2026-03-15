"""Tests for distributed tracing core."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from baton.schemas import ObservabilityConfig, TelemetryClassRule
from baton.tracing import (
    JsonlExporter,
    NullExporter,
    SpanData,
    TraceContext,
    create_span_exporter,
    derive_telemetry_class,
    format_traceparent,
    generate_span_id,
    generate_trace_id,
    parse_traceparent,
    resolve_telemetry_class,
)


class TestGenerateIds:
    def test_trace_id_is_32_hex(self):
        tid = generate_trace_id()
        assert len(tid) == 32
        int(tid, 16)  # should not raise

    def test_span_id_is_16_hex(self):
        sid = generate_span_id()
        assert len(sid) == 16
        int(sid, 16)

    def test_ids_are_unique(self):
        ids = {generate_trace_id() for _ in range(100)}
        assert len(ids) == 100

    def test_span_ids_are_unique(self):
        ids = {generate_span_id() for _ in range(100)}
        assert len(ids) == 100


class TestParseTraceparent:
    def test_valid_sampled(self):
        header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        ctx = parse_traceparent(header)
        assert ctx is not None
        assert ctx.trace_id == "0af7651916cd43dd8448eb211c80319c"
        assert ctx.span_id == "b7ad6b7169203331"
        assert ctx.sampled is True

    def test_valid_not_sampled(self):
        header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-00"
        ctx = parse_traceparent(header)
        assert ctx is not None
        assert ctx.sampled is False

    def test_empty_string(self):
        assert parse_traceparent("") is None

    def test_invalid_version(self):
        assert parse_traceparent("01-abc-def-01") is None

    def test_wrong_part_count(self):
        assert parse_traceparent("00-abc-def") is None

    def test_wrong_trace_id_length(self):
        assert parse_traceparent("00-short-b7ad6b7169203331-01") is None

    def test_wrong_span_id_length(self):
        assert parse_traceparent("00-0af7651916cd43dd8448eb211c80319c-short-01") is None

    def test_whitespace_stripped(self):
        header = "  00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01  "
        ctx = parse_traceparent(header)
        assert ctx is not None
        assert ctx.trace_id == "0af7651916cd43dd8448eb211c80319c"


class TestFormatTraceparent:
    def test_sampled(self):
        ctx = TraceContext(
            trace_id="0af7651916cd43dd8448eb211c80319c",
            span_id="b7ad6b7169203331",
            sampled=True,
        )
        assert format_traceparent(ctx) == "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"

    def test_not_sampled(self):
        ctx = TraceContext(
            trace_id="0af7651916cd43dd8448eb211c80319c",
            span_id="b7ad6b7169203331",
            sampled=False,
        )
        assert format_traceparent(ctx) == "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-00"

    def test_roundtrip(self):
        original = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        ctx = parse_traceparent(original)
        assert format_traceparent(ctx) == original


class TestDeriveTelemetryClass:
    def test_basic(self):
        result = derive_telemetry_class("GET", "api", "/users/123")
        assert result == "GET_api_users"

    def test_root_path(self):
        result = derive_telemetry_class("POST", "service", "/")
        assert result == "POST_service_root"

    def test_empty_path(self):
        result = derive_telemetry_class("GET", "api", "")
        assert result == "GET_api_root"

    def test_deep_path(self):
        result = derive_telemetry_class("PUT", "api", "/users/123/orders/456")
        assert result == "PUT_api_users"


class TestResolveTelemetryClass:
    def test_matches_rule(self):
        rules = [
            TelemetryClassRule(match="POST /payments/charge", telemetry_class="fraud-check"),
        ]
        result = resolve_telemetry_class("POST", "/payments/charge", "api", rules)
        assert result == "fraud-check"

    def test_falls_back_to_derived(self):
        rules = [
            TelemetryClassRule(match="POST /payments/charge", telemetry_class="fraud-check"),
        ]
        result = resolve_telemetry_class("GET", "/health", "api", rules)
        assert result == "GET_api_health"

    def test_empty_rules(self):
        result = resolve_telemetry_class("GET", "/health", "api", [])
        assert result == "GET_api_health"

    def test_first_match_wins(self):
        rules = [
            TelemetryClassRule(match="GET /health", telemetry_class="first"),
            TelemetryClassRule(match="GET /health", telemetry_class="second"),
        ]
        result = resolve_telemetry_class("GET", "/health", "api", rules)
        assert result == "first"


class TestNullExporter:
    def test_export_is_noop(self):
        exporter = NullExporter()
        exporter.export([SpanData(name="test", trace_id="a" * 32, span_id="b" * 16)])
        exporter.shutdown()  # should not raise


class TestJsonlExporter:
    def test_export_writes_file(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        exporter = JsonlExporter(d)
        span = SpanData(
            name="test-span",
            trace_id="a" * 32,
            span_id="b" * 16,
            node_name="api",
        )
        exporter.export([span])

        path = d / ".baton" / "spans.jsonl"
        assert path.exists()
        data = json.loads(path.read_text().strip())
        assert data["name"] == "test-span"
        assert data["trace_id"] == "a" * 32
        assert data["node_name"] == "api"

    def test_export_multiple(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        exporter = JsonlExporter(d)
        spans = [
            SpanData(name=f"span-{i}", trace_id="a" * 32, span_id=f"{i:016x}")
            for i in range(3)
        ]
        exporter.export(spans)

        path = d / ".baton" / "spans.jsonl"
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 3


class TestCreateSpanExporter:
    def test_null_exporter(self):
        config = ObservabilityConfig(enabled=True)
        exporter = create_span_exporter("null", config)
        assert isinstance(exporter, NullExporter)

    def test_disabled_returns_null(self):
        config = ObservabilityConfig(enabled=False)
        exporter = create_span_exporter("jsonl", config)
        assert isinstance(exporter, NullExporter)

    def test_jsonl_exporter(self, project_dir: Path):
        config = ObservabilityConfig(enabled=True)
        exporter = create_span_exporter("jsonl", config, project_dir)
        assert isinstance(exporter, JsonlExporter)

    def test_unknown_raises(self):
        config = ObservabilityConfig(enabled=True)
        with pytest.raises(ValueError, match="Unknown span exporter"):
            create_span_exporter("unknown", config)

    def test_otel_without_package(self):
        config = ObservabilityConfig(enabled=True, otlp_endpoint="http://localhost:4317")
        with patch.dict("sys.modules", {"baton.otel": None}):
            with pytest.raises(ImportError, match="OpenTelemetry not installed"):
                create_span_exporter("otel", config)
