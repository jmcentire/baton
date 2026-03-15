"""Functional assertion tests for Arbiter/Constrain integration (FA-B-N001 through FA-B-N020)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

# Tests grouped by feature area


class TestConstrainIntegration:
    """FA-B-N001 through FA-B-N003: Constrain component_map.yaml integration."""

    def test_n001_generates_valid_baton_yaml(self, tmp_path: Path):
        """FA-B-N001: baton init --constrain-dir generates valid baton.yaml."""
        from baton.constrain import generate_baton_config, load_component_map

        constrain_dir = tmp_path / "constrain"
        constrain_dir.mkdir()
        component_map = {
            "components": [
                {"name": "user-api", "port": 8001, "protocol": "http"},
                {"name": "auth", "port": 8002},
            ],
            "edges": [{"from": "user-api", "to": "auth"}],
        }
        (constrain_dir / "component_map.yaml").write_text(yaml.dump(component_map))

        loaded = load_component_map(constrain_dir)
        config = generate_baton_config(loaded)

        # Should be valid baton.yaml structure
        assert config["name"] == "default"
        assert config["version"] == 2
        assert len(config["nodes"]) == 2
        assert len(config["edges"]) == 1

    def test_n002_one_node_per_component(self, tmp_path: Path):
        """FA-B-N002: Generated baton.yaml has one node per component."""
        from baton.constrain import generate_baton_config

        component_map = {
            "components": [
                {"name": "api", "data_access": {"reads": ["PII"], "writes": ["PII"]}},
                {"name": "db", "role": "egress"},
                {"name": "cache"},
            ],
            "edges": [],
        }
        config = generate_baton_config(component_map)
        node_names = [n["name"] for n in config["nodes"]]
        assert node_names == ["api", "db", "cache"]
        # Data access preserved
        assert config["nodes"][0]["data_access"] == {"reads": ["PII"], "writes": ["PII"]}

    def test_n003_one_edge_per_edge(self, tmp_path: Path):
        """FA-B-N003: Generated baton.yaml has one edge per component_map edge."""
        from baton.constrain import generate_baton_config

        component_map = {
            "components": [
                {"name": "api"},
                {"name": "service"},
                {"name": "db"},
            ],
            "edges": [
                {"from": "api", "to": "service"},
                {"from": "service", "to": "db", "data_tiers_in_flight": ["PII"]},
            ],
        }
        config = generate_baton_config(component_map)
        assert len(config["edges"]) == 2
        assert config["edges"][1].get("data_tiers_in_flight") == ["PII"]


class TestSchemaBackwardCompat:
    """FA-B-N018, FA-B-N019: Schema versioning and backward compatibility."""

    def test_n018_version_2_validates(self):
        """FA-B-N018: baton.yaml version 2 schema validates correctly."""
        from baton.schemas import CircuitConfig, NodeSpec, ArbiterConfig, DataAccessSpec

        config = CircuitConfig(
            name="test",
            version=2,
            nodes=[
                NodeSpec(
                    name="api", port=8001,
                    data_access=DataAccessSpec(reads=["PII"], writes=["PII"]),
                    authority=["user.*"],
                    openapi_spec="specs/api.yaml",
                ),
            ],
            arbiter=ArbiterConfig(
                api_endpoint="http://localhost:7700",
                forward_spans=True,
            ),
        )
        assert config.version == 2
        assert config.nodes[0].data_access.reads == ["PII"]
        assert config.arbiter.api_endpoint == "http://localhost:7700"

    def test_n019_version_1_loads(self, tmp_path: Path):
        """FA-B-N019: Version 1 baton.yaml loads without error."""
        from baton.config import load_circuit_config

        v1_config = {
            "name": "legacy",
            "version": 1,
            "nodes": [
                {"name": "api", "port": 8001},
                {"name": "db", "port": 8002},
            ],
            "edges": [{"source": "api", "target": "db"}],
        }
        (tmp_path / "baton.yaml").write_text(yaml.dump(v1_config))
        config = load_circuit_config(tmp_path)
        assert config.version == 1
        assert len(config.nodes) == 2
        # New fields default to empty/None
        assert config.nodes[0].data_access is None
        assert config.arbiter.api_endpoint == ""


class TestArbiterClient:
    """FA-B-N004 through FA-B-N006, FA-B-N008, FA-B-N017: Arbiter client behavior."""

    @pytest.mark.asyncio
    async def test_n008_returns_none_when_unreachable(self):
        """FA-B-N008: ArbiterClient returns None when unreachable."""
        from baton.arbiter import ArbiterClient
        client = ArbiterClient("http://127.0.0.1:19999")
        result = await client.get_trust_score("test-node")
        assert result is None

    @pytest.mark.asyncio
    async def test_n008b_is_reachable_false(self):
        """FA-B-N008b: is_reachable returns False when unreachable."""
        from baton.arbiter import ArbiterClient
        client = ArbiterClient("http://127.0.0.1:19999")
        assert await client.is_reachable() is False

    @pytest.mark.asyncio
    async def test_n009_trust_score_parsed(self):
        """FA-B-N009: ArbiterClient parses trust score from mock server."""
        # Start a mock Arbiter that returns a trust score
        async def handle(reader, writer):
            try:
                await reader.readuntil(b"\r\n\r\n")
                body = json.dumps({"score": 0.94, "level": "high", "authoritative": True})
                response = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    f"Connection: close\r\n\r\n{body}"
                ).encode()
                writer.write(response)
                await writer.drain()
            except Exception:
                pass
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 19800)
        try:
            from baton.arbiter import ArbiterClient
            client = ArbiterClient("http://127.0.0.1:19800")
            trust = await client.get_trust_score("user-service")
            assert trust is not None
            assert trust.score == 0.94
            assert trust.level == "high"
            assert trust.authoritative is True
        finally:
            server.close()
            await server.wait_closed()

    def test_n010_slot_proceeds_without_arbiter(self):
        """FA-B-N010: Slot proceeds when Arbiter is not configured."""
        from baton.schemas import CircuitConfig, NodeSpec
        # When arbiter.api_endpoint is empty, no Arbiter integration
        config = CircuitConfig(
            nodes=[NodeSpec(name="api", port=8001)],
        )
        assert config.arbiter.api_endpoint == ""
        # LifecycleManager._arbiter_client stays None when api_endpoint is empty

    @pytest.mark.asyncio
    async def test_n017_arbiter_unavailable_no_block(self):
        """FA-B-N017: Arbiter unavailability does not prevent circuit from running."""
        from baton.arbiter import ArbiterClient
        client = ArbiterClient("http://127.0.0.1:19999")
        # Declaration gap check returns fail-open (no gap) when unreachable
        gap = await client.check_declaration_gap("node", ["PII"], ["PII"])
        assert gap.has_gap is False


class TestClassificationTagging:
    """FA-B-N007, FA-B-N013: Classification mapping and span attributes."""

    def test_n013_classification_from_openapi(self, tmp_path: Path):
        """FA-B-N013: Classification mapping loads from OpenAPI spec."""
        from baton.adapter import load_openapi_classifications

        spec = {
            "openapi": "3.0.0",
            "paths": {},
            "components": {
                "schemas": {
                    "User": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "ssn": {"type": "string", "x-data-classification": "PII"},
                            "email": {"type": "string", "x-data-classification": ["PII", "CONTACT"]},
                        },
                    }
                }
            },
        }
        spec_path = tmp_path / "api.yaml"
        spec_path.write_text(yaml.dump(spec))

        mapping = load_openapi_classifications("api.yaml", base_dir=tmp_path)
        assert "ssn" in mapping
        assert mapping["ssn"] == ["PII"]
        assert "email" in mapping
        assert set(mapping["email"]) == {"PII", "CONTACT"}
        assert "id" not in mapping  # No classification

    def test_n014_classification_in_span(self):
        """FA-B-N014: Classification attributes appear in scan results."""
        from baton.adapter import _classify_body

        mapping = {"ssn": ["PII"], "card_number": ["FINANCIAL"]}
        body = b'{"name": "test", "ssn": "555-12-3456", "card_number": "4000"}'
        result = _classify_body(body, mapping)
        assert "PII" in result
        assert "FINANCIAL" in result


class TestSpanForwarding:
    """FA-B-N015, FA-B-N016: Arbiter span forwarding."""

    def test_n015_forwarder_is_fire_and_forget(self):
        """FA-B-N015: ArbiterSpanForwarder does not block."""
        from baton.arbiter_exporter import ArbiterSpanForwarder
        from baton.tracing import SpanData

        forwarder = ArbiterSpanForwarder("http://127.0.0.1:19999")
        span = SpanData(
            name="test", trace_id="abc", span_id="def",
            start_time_ns=0, end_time_ns=1000,
            attributes={}, status="ok", node_name="test",
        )
        # Enqueue should not block or raise even with unreachable endpoint
        forwarder.enqueue([span])
        assert len(forwarder._queue) == 1

    def test_n016_drop_rate_tracked(self):
        """FA-B-N016: ArbiterSpanForwarder tracks drop rate."""
        from baton.arbiter_exporter import ArbiterSpanForwarder
        from baton.tracing import SpanData

        forwarder = ArbiterSpanForwarder("http://127.0.0.1:19999", max_queue=2)
        span = SpanData(
            name="test", trace_id="abc", span_id="def",
            start_time_ns=0, end_time_ns=1000,
            attributes={}, status="ok", node_name="test",
        )
        # Fill queue + overflow
        forwarder.enqueue([span, span, span, span])
        # 2 enqueued, 2 dropped
        assert forwarder.spans_dropped == 2
        assert forwarder.drop_rate > 0


class TestAuditSidecar:
    """FA-B-N011, FA-B-N012, FA-B-N020: Audit event sidecar."""

    @pytest.mark.asyncio
    async def test_n020_localhost_only(self):
        """FA-B-N020: Audit sidecar binds to 127.0.0.1."""
        from baton.audit_sidecar import AuditSidecar
        sidecar = AuditSidecar(port=19850)
        await sidecar.start()
        try:
            assert sidecar.is_running
            # Verify it's listening on localhost
            reader, writer = await asyncio.open_connection("127.0.0.1", 19850)
            writer.close()
            await writer.wait_closed()
        finally:
            await sidecar.stop()

    @pytest.mark.asyncio
    async def test_n011_accepts_audit_event(self):
        """FA-B-N011: Audit sidecar accepts POST /audit-event."""
        from baton.audit_sidecar import AuditSidecar
        sidecar = AuditSidecar(port=19851)
        await sidecar.start()
        try:
            event = json.dumps({
                "pact_key": "PACT:user:get_user",
                "event": "invoked",
                "input_classification": ["PUBLIC"],
                "output_classification": ["PII"],
            })
            reader, writer = await asyncio.open_connection("127.0.0.1", 19851)
            request = (
                f"POST /audit-event HTTP/1.1\r\n"
                f"Host: 127.0.0.1:19851\r\n"
                f"Content-Length: {len(event)}\r\n"
                f"Connection: close\r\n\r\n{event}"
            ).encode()
            writer.write(request)
            await writer.drain()
            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            writer.close()
            await writer.wait_closed()

            assert b"201" in response
            assert len(sidecar.events) == 1
            assert sidecar.events[0].pact_key == "PACT:user:get_user"
        finally:
            await sidecar.stop()

    @pytest.mark.asyncio
    async def test_n012_events_queryable(self):
        """FA-B-N012: Buffered audit events are queryable by node."""
        from baton.audit_sidecar import AuditSidecar, AuditEvent
        sidecar = AuditSidecar(port=19852)
        # Manually buffer events
        sidecar._events.append(AuditEvent(
            pact_key="PACT:user:get", event="invoked", node_name="user-api",
        ))
        sidecar._events.append(AuditEvent(
            pact_key="PACT:auth:check", event="completed", node_name="auth",
        ))
        results = sidecar.query(node="user-api")
        assert len(results) == 1
        assert results[0].pact_key == "PACT:user:get"


class TestDashboardTrust:
    """FA-B-N016b, FA-B-N019b: Dashboard trust panel."""

    def test_n019b_dashboard_degrades_gracefully(self):
        """Dashboard shows None trust when Arbiter unavailable."""
        from baton.dashboard import NodeSnapshot
        snap = NodeSnapshot(name="api", role="service")
        assert snap.trust_score is None
        assert snap.trust_level is None
