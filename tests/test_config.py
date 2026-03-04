"""Tests for config loading and saving."""

from __future__ import annotations

from pathlib import Path

import pytest

import yaml

from baton.config import (
    add_service_path,
    load_circuit,
    load_circuit_config,
    load_circuit_from_services,
    save_circuit,
    save_circuit_config,
    _discover_service_dirs,
)
from baton.manifest import MANIFEST_FILENAME
from baton.schemas import (
    CircuitConfig,
    CircuitSpec,
    DeployConfig,
    EdgePolicy,
    EdgeSpec,
    NodeRole,
    NodeSpec,
    NodeTelemetryConfig,
    ObservabilityConfig,
    RoutingConfig,
    RoutingStrategy,
    RoutingTarget,
    SecurityConfig,
    TelemetryClassRule,
    TLSConfig,
    TLSMode,
)


class TestLoadCircuit:
    def test_load_empty(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text("name: empty\n")
        c = load_circuit(project_dir)
        assert c.name == "empty"
        assert c.nodes == []
        assert c.edges == []

    def test_load_with_nodes(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text(
            "name: test\nnodes:\n  - name: api\n    port: 8001\n  - name: db\n    port: 5432\n"
        )
        c = load_circuit(project_dir)
        assert len(c.nodes) == 2
        assert c.nodes[0].name == "api"
        assert c.nodes[1].port == 5432

    def test_load_with_edges(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text(
            "name: test\nnodes:\n  - name: api\n    port: 8001\n  - name: db\n    port: 5432\n"
            "edges:\n  - source: api\n    target: db\n"
        )
        c = load_circuit(project_dir)
        assert len(c.edges) == 1
        assert c.edges[0].source == "api"

    def test_missing_file(self, project_dir: Path):
        with pytest.raises(FileNotFoundError):
            load_circuit(project_dir)

    def test_empty_yaml(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text("")
        c = load_circuit(project_dir)
        assert c.name == "default"

    def test_tcp_mode(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text(
            "name: test\nnodes:\n  - name: db\n    port: 5432\n    proxy_mode: tcp\n"
        )
        c = load_circuit(project_dir)
        assert c.nodes[0].proxy_mode == "tcp"


class TestSaveCircuit:
    def test_roundtrip(self, project_dir: Path):
        circuit = CircuitSpec(
            name="roundtrip",
            nodes=[
                NodeSpec(name="api", port=8001),
                NodeSpec(name="db", port=5432, proxy_mode="tcp"),
            ],
            edges=[EdgeSpec(source="api", target="db")],
        )
        save_circuit(circuit, project_dir)
        loaded = load_circuit(project_dir)
        assert loaded.name == "roundtrip"
        assert len(loaded.nodes) == 2
        assert len(loaded.edges) == 1
        assert loaded.nodes[0].name == "api"
        assert loaded.nodes[1].proxy_mode == "tcp"

    def test_save_empty(self, project_dir: Path):
        circuit = CircuitSpec(name="empty")
        save_circuit(circuit, project_dir)
        loaded = load_circuit(project_dir)
        assert loaded.name == "empty"
        assert loaded.nodes == []

    def test_preserves_contract(self, project_dir: Path):
        circuit = CircuitSpec(
            name="test",
            nodes=[NodeSpec(name="api", port=8001, contract="specs/api.yaml")],
        )
        save_circuit(circuit, project_dir)
        loaded = load_circuit(project_dir)
        assert loaded.nodes[0].contract == "specs/api.yaml"

    def test_roundtrip_with_role(self, project_dir: Path):
        circuit = CircuitSpec(
            name="test",
            nodes=[
                NodeSpec(name="gateway", port=8001, role="ingress"),
                NodeSpec(name="stripe", port=8002, role="egress"),
                NodeSpec(name="api", port=8003),
            ],
        )
        save_circuit(circuit, project_dir)
        loaded = load_circuit(project_dir)
        assert loaded.nodes[0].role == NodeRole.INGRESS
        assert loaded.nodes[1].role == NodeRole.EGRESS
        assert loaded.nodes[2].role == NodeRole.SERVICE


class TestLoadCircuitFromServices:
    def test_derive_from_service_dirs(self, project_dir: Path):
        # Create service dirs with manifests
        api_dir = project_dir / "api"
        api_dir.mkdir()
        (api_dir / MANIFEST_FILENAME).write_text(
            yaml.dump({"name": "api", "dependencies": ["db"]})
        )
        db_dir = project_dir / "db"
        db_dir.mkdir()
        (db_dir / MANIFEST_FILENAME).write_text(
            yaml.dump({"name": "db", "proxy_mode": "tcp"})
        )

        circuit = load_circuit_from_services(project_dir, [api_dir, db_dir])
        assert len(circuit.nodes) == 2
        assert len(circuit.edges) == 1

    def test_derive_with_baton_yaml_name(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text("name: myapp\n")
        api_dir = project_dir / "api"
        api_dir.mkdir()
        (api_dir / MANIFEST_FILENAME).write_text(yaml.dump({"name": "api"}))

        circuit = load_circuit_from_services(project_dir, [api_dir])
        assert circuit.name == "myapp"

    def test_no_service_dirs(self, project_dir: Path):
        with pytest.raises(FileNotFoundError, match="No service directories"):
            load_circuit_from_services(project_dir)


class TestDiscoverServiceDirs:
    def test_from_yaml(self, project_dir: Path):
        api_dir = project_dir / "services" / "api"
        api_dir.mkdir(parents=True)
        (api_dir / MANIFEST_FILENAME).write_text(yaml.dump({"name": "api"}))

        (project_dir / "baton.yaml").write_text(
            yaml.dump({"name": "test", "services": ["services/api"]})
        )
        dirs = _discover_service_dirs(project_dir)
        assert len(dirs) == 1
        assert dirs[0] == project_dir / "services" / "api"

    def test_scan_subdirs(self, project_dir: Path):
        for name in ["api", "db"]:
            d = project_dir / name
            d.mkdir()
            (d / MANIFEST_FILENAME).write_text(yaml.dump({"name": name}))

        dirs = _discover_service_dirs(project_dir)
        assert len(dirs) == 2


class TestAddServicePath:
    def test_add_service(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text("name: test\n")
        add_service_path(project_dir, "./api")

        with open(project_dir / "baton.yaml") as f:
            raw = yaml.safe_load(f)
        assert "./api" in raw["services"]

    def test_add_idempotent(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text("name: test\n")
        add_service_path(project_dir, "./api")
        add_service_path(project_dir, "./api")

        with open(project_dir / "baton.yaml") as f:
            raw = yaml.safe_load(f)
        assert raw["services"].count("./api") == 1

    def test_missing_baton_yaml(self, project_dir: Path):
        with pytest.raises(FileNotFoundError):
            add_service_path(project_dir, "./api")


# -- Full CircuitConfig round-trip --


class TestLoadCircuitConfig:
    def test_full_config(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "full",
            "version": 2,
            "nodes": [
                {"name": "api", "port": 8001, "routing": {
                    "strategy": "weighted",
                    "targets": [
                        {"name": "a", "port": 28001, "weight": 80},
                        {"name": "b", "port": 28002, "weight": 20},
                    ],
                }},
                {"name": "db", "port": 5432, "proxy_mode": "tcp", "role": "egress"},
            ],
            "edges": [
                {"source": "api", "target": "db", "policy": {"timeout_ms": 5000, "retries": 3}},
            ],
            "deploy": {"provider": "gcp", "project": "my-proj", "region": "us-central1"},
            "security": {
                "tls": {"mode": "circuit", "cert": "cert.pem", "key": "key.pem"},
                "control": {"auth": True, "token_env": "BATON_TOKEN"},
            },
        }))
        config = load_circuit_config(project_dir)
        assert config.name == "full"
        assert config.version == 2
        assert len(config.nodes) == 2
        assert len(config.edges) == 1
        assert config.edges[0].policy is not None
        assert config.edges[0].policy.timeout_ms == 5000
        assert config.edges[0].policy.retries == 3
        assert "api" in config.routing
        assert config.routing["api"].strategy == RoutingStrategy.WEIGHTED
        assert config.deploy.provider == "gcp"
        assert config.deploy.project == "my-proj"
        assert config.security.tls.mode == TLSMode.CIRCUIT
        assert config.security.control.auth is True

    def test_backwards_compat_old_yaml(self, project_dir: Path):
        """Old YAML without routing/deploy/security loads fine."""
        (project_dir / "baton.yaml").write_text(
            "name: old\nnodes:\n  - name: api\n    port: 8001\nedges:\n  - source: api\n    target: api\n"
        )
        # This will fail validation (self-loop), but the parsing itself should work
        # Test with a valid config
        (project_dir / "baton.yaml").write_text(
            "name: old\nnodes:\n  - name: api\n    port: 8001\n"
        )
        config = load_circuit_config(project_dir)
        assert config.name == "old"
        assert len(config.nodes) == 1
        assert config.routing == {}
        assert config.deploy.provider == "local"
        assert config.security.tls.mode == TLSMode.OFF

    def test_missing_file(self, project_dir: Path):
        with pytest.raises(FileNotFoundError):
            load_circuit_config(project_dir)

    def test_empty_yaml(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text("")
        config = load_circuit_config(project_dir)
        assert config.name == "default"


class TestSaveCircuitConfig:
    def test_roundtrip(self, project_dir: Path):
        config = CircuitConfig(
            name="roundtrip",
            nodes=[
                NodeSpec(name="api", port=8001),
                NodeSpec(name="db", port=5432, proxy_mode="tcp", role="egress"),
            ],
            edges=[
                EdgeSpec(source="api", target="db", policy=EdgePolicy(timeout_ms=5000)),
            ],
            routing={"api": RoutingConfig(
                strategy=RoutingStrategy.WEIGHTED,
                targets=[
                    RoutingTarget(name="a", port=28001, weight=80),
                    RoutingTarget(name="b", port=28002, weight=20),
                ],
            )},
            deploy=DeployConfig(provider="gcp", project="my-proj"),
            security=SecurityConfig(
                tls=TLSConfig(mode=TLSMode.CIRCUIT, cert="cert.pem"),
            ),
        )
        save_circuit_config(config, project_dir)
        loaded = load_circuit_config(project_dir)
        assert loaded.name == "roundtrip"
        assert len(loaded.nodes) == 2
        assert len(loaded.edges) == 1
        assert loaded.edges[0].policy.timeout_ms == 5000
        assert "api" in loaded.routing
        assert loaded.routing["api"].strategy == RoutingStrategy.WEIGHTED
        assert loaded.deploy.provider == "gcp"
        assert loaded.security.tls.mode == TLSMode.CIRCUIT


class TestParseCircuitNewSections:
    def test_parse_circuit_ignores_routing_on_nodes(self, project_dir: Path):
        """_parse_circuit (used by load_circuit) doesn't crash on routing in nodes."""
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [
                {"name": "api", "port": 8001, "routing": {"strategy": "weighted", "targets": []}},
            ],
        }))
        circuit = load_circuit(project_dir)
        assert len(circuit.nodes) == 1
        assert circuit.nodes[0].name == "api"

    def test_parse_circuit_ignores_policy_on_edges(self, project_dir: Path):
        """_parse_circuit (used by load_circuit) doesn't crash on policy in edges."""
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [
                {"name": "api", "port": 8001},
                {"name": "db", "port": 5432},
            ],
            "edges": [
                {"source": "api", "target": "db", "policy": {"timeout_ms": 5000}},
            ],
        }))
        circuit = load_circuit(project_dir)
        assert len(circuit.edges) == 1
        assert circuit.edges[0].source == "api"

    def test_edge_policy_roundtrip_through_save_circuit(self, project_dir: Path):
        """save_circuit includes edge policy in YAML."""
        from baton.config import save_circuit, load_circuit_config
        circuit = CircuitSpec(
            name="test",
            nodes=[
                NodeSpec(name="api", port=8001),
                NodeSpec(name="db", port=5432),
            ],
            edges=[EdgeSpec(source="api", target="db", policy=EdgePolicy(retries=2))],
        )
        save_circuit(circuit, project_dir)
        # Read back as config to verify policy is in YAML
        config = load_circuit_config(project_dir)
        assert config.edges[0].policy is not None
        assert config.edges[0].policy.retries == 2


class TestTopLevelRouting:
    def test_top_level_routing_section(self, project_dir: Path):
        """Top-level routing section is parsed correctly."""
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [
                {"name": "api", "port": 8001},
            ],
            "routing": {
                "api": {
                    "strategy": "weighted",
                    "targets": [
                        {"name": "a", "port": 28001, "weight": 80},
                        {"name": "b", "port": 28002, "weight": 20},
                    ],
                },
            },
        }))
        config = load_circuit_config(project_dir)
        assert "api" in config.routing
        assert config.routing["api"].strategy == RoutingStrategy.WEIGHTED


class TestObservabilityConfig:
    def test_parse_observability(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [{"name": "api", "port": 8001}],
            "observability": {
                "enabled": True,
                "sink": "otel",
                "otlp_endpoint": "http://localhost:4317",
                "service_name": "myproject",
                "trace_sample_rate": 0.5,
            },
        }))
        config = load_circuit_config(project_dir)
        assert config.observability.enabled is True
        assert config.observability.sink == "otel"
        assert config.observability.otlp_endpoint == "http://localhost:4317"
        assert config.observability.service_name == "myproject"
        assert config.observability.trace_sample_rate == 0.5

    def test_default_observability(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [{"name": "api", "port": 8001}],
        }))
        config = load_circuit_config(project_dir)
        assert config.observability.enabled is False
        assert config.observability.sink == "jsonl"

    def test_observability_roundtrip(self, project_dir: Path):
        config = CircuitConfig(
            name="obs-test",
            nodes=[NodeSpec(name="api", port=8001)],
            observability=ObservabilityConfig(
                enabled=True,
                sink="otel",
                otlp_endpoint="http://collector:4317",
                service_name="test-svc",
            ),
        )
        save_circuit_config(config, project_dir)
        loaded = load_circuit_config(project_dir)
        assert loaded.observability.enabled is True
        assert loaded.observability.sink == "otel"
        assert loaded.observability.otlp_endpoint == "http://collector:4317"
        assert loaded.observability.service_name == "test-svc"

    def test_default_observability_not_serialized(self, project_dir: Path):
        config = CircuitConfig(
            name="no-obs",
            nodes=[NodeSpec(name="api", port=8001)],
        )
        save_circuit_config(config, project_dir)
        with open(project_dir / "baton.yaml") as f:
            raw = yaml.safe_load(f)
        assert "observability" not in raw


class TestNodeTelemetryConfig:
    def test_parse_node_telemetry(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [{
                "name": "api",
                "port": 8001,
                "telemetry": {
                    "classes": [
                        {
                            "match": "POST /payments/charge",
                            "class": "fraud-check",
                            "slo_p95_ms": 200,
                            "owner": "fraud-team",
                        },
                    ],
                },
            }],
        }))
        config = load_circuit_config(project_dir)
        assert "api" in config.node_telemetry
        classes = config.node_telemetry["api"].classes
        assert len(classes) == 1
        assert classes[0].match == "POST /payments/charge"
        assert classes[0].telemetry_class == "fraud-check"
        assert classes[0].slo_p95_ms == 200
        assert classes[0].owner == "fraud-team"

    def test_telemetry_roundtrip(self, project_dir: Path):
        config = CircuitConfig(
            name="tel-test",
            nodes=[NodeSpec(name="api", port=8001)],
            node_telemetry={
                "api": NodeTelemetryConfig(classes=[
                    TelemetryClassRule(
                        match="GET /health",
                        telemetry_class="healthcheck",
                        slo_p95_ms=50,
                    ),
                ]),
            },
        )
        save_circuit_config(config, project_dir)
        loaded = load_circuit_config(project_dir)
        assert "api" in loaded.node_telemetry
        classes = loaded.node_telemetry["api"].classes
        assert len(classes) == 1
        assert classes[0].telemetry_class == "healthcheck"
        assert classes[0].slo_p95_ms == 50

    def test_no_telemetry_on_node(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text(yaml.dump({
            "name": "test",
            "nodes": [{"name": "api", "port": 8001}],
        }))
        config = load_circuit_config(project_dir)
        assert config.node_telemetry == {}
